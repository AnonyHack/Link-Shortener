import os
import asyncio
import logging
import requests
from functools import wraps
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    filters
)
from pymongo import MongoClient
from typing import Dict, Any

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('url_shortener_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Bot configuration from environment variables
CONFIG = {
    'token': os.getenv('TELEGRAM_BOT_TOKEN'),
    'admin_ids': [int(id) for id in os.getenv('ADMIN_IDS', '').split(',') if id],
    'welcome_credits': 15,
    'cost_per_url': 5,
    'referral_bonus': 5,
}

# MongoDB connection
client = MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('DATABASE_NAME', 'url_shortener_bot')]

# Collections
users_collection = db['users']
stats_collection = db['stats']

# Initialize database with default stats if empty
if stats_collection.count_documents({}) == 0:
    stats_collection.insert_one({
        'total_urls_created': 0,
        'total_credits_used': 0
    })

# Force join configuration
REQUIRED_CHANNELS = ["megahubbots"]

# Conversation states
WAITING_FOR_URL, WAITING_FOR_EMOJI_URL, WAITING_FOR_EMOJIS, WAITING_FOR_STATS_URL = range(4)

# ==============================================
# Database Management Functions (MongoDB)
# ==============================================

def get_user(user_id: int) -> Dict[str, Any]:
    """Get user data or create new user record if doesn't exist"""
    user = users_collection.find_one({'user_id': user_id})
    
    if not user:
        user = {
            'user_id': user_id,
            'credits': CONFIG['welcome_credits'],
            'urls_created': 0,
            'referral_code': f"ref{user_id}",
            'referred_by': None,
            'referral_count': 0
        }
        users_collection.insert_one(user)
        logger.info(f"Created new user: {user_id}")
    
    return user

def update_user(user_id: int, update_data: Dict[str, Any]):
    """Update user data in MongoDB"""
    users_collection.update_one(
        {'user_id': user_id},
        {'$set': update_data}
    )

def get_stats() -> Dict[str, Any]:
    """Get statistics from MongoDB"""
    return stats_collection.find_one()

def update_stats(update_data: Dict[str, Any]):
    """Update statistics in MongoDB"""
    stats_collection.update_one(
        {},
        {'$inc': update_data}
    )

def is_admin(user_id: int) -> bool:
    """Check if user has admin privileges"""
    return user_id in CONFIG['admin_ids']

def has_sufficient_credits(user_id: int) -> bool:
    """Check if user has enough credits for URL shortening"""
    user = get_user(user_id)
    return user['credits'] >= CONFIG['cost_per_url']

def deduct_credits(user_id: int):
    """Subtract credits after successful URL shortening"""
    users_collection.update_one(
        {'user_id': user_id},
        {
            '$inc': {
                'credits': -CONFIG['cost_per_url'],
                'urls_created': 1
            }
        }
    )
    update_stats({
        'total_urls_created': 1,
        'total_credits_used': CONFIG['cost_per_url']
    })
    logger.info(f"Deducted credits from user {user_id}")

def add_credits(user_id: int, amount: int):
    """Add credits to user's balance"""
    users_collection.update_one(
        {'user_id': user_id},
        {'$inc': {'credits': amount}}
    )
    logger.info(f"Added {amount} credits to user {user_id}")

def handle_referral(user_id: int, ref_code: str):
    """Process referral link usage with MongoDB"""
    referring_user = users_collection.find_one({'referral_code': ref_code})
    
    if referring_user and not users_collection.find_one({'user_id': user_id}):
        # Create new user
        get_user(user_id)
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'referred_by': ref_code}}
        )
        
        # Update referring user
        users_collection.update_one(
            {'user_id': referring_user['user_id']},
            {
                '$inc': {
                    'referral_count': 1,
                    'credits': CONFIG['referral_bonus']
                }
            }
        )
        
        # Notify the referring user
        notification = f"""
🎉 𝙉𝙚𝙬 𝙍𝙚𝙛𝙚𝙧𝙧𝙖𝙡!
👤 𝚂𝚘𝚖𝚎𝚘𝚗𝚎 𝚓𝚘𝚒𝚗𝚎𝚍 𝚞𝚜𝚒𝚗𝚐 𝚢𝚘𝚞𝚛 𝚛𝚎𝚏𝚎𝚛𝚛𝚊𝚕 𝚕𝚒𝚗𝚔!
➕ 𝚈𝚘𝚞 𝚛𝚎𝚌𝚎𝚒𝚟𝚎𝚍 {CONFIG['referral_bonus']} 𝚌𝚛𝚎𝚍𝚒𝚝𝚜
💰 𝚈𝚘𝚞𝚛 𝚗𝚎𝚠 𝚋𝚊𝚕𝚊𝚗𝚌𝚎: {referring_user['credits'] + CONFIG['referral_bonus']} 𝚌𝚛𝚎𝚍𝚒𝚝𝚜
"""
        asyncio.run_coroutine_threadsafe(
            notify_user(Application.builder().token(CONFIG['token']).build().bot, 
            referring_user['user_id'], 
            notification),
            asyncio.get_event_loop()
        )
        logger.info(f"New referral: {user_id} referred by {ref_code}")

async def notify_user(bot, user_id: int, message: str):
    """Helper function to send notifications to users"""
    try:
        await bot.send_message(chat_id=user_id, text=message)
    except Exception as e:
        logger.error(f"Failed to send notification to user {user_id}: {e}")

# ==============================================
# Channel Membership Verification
# ==============================================

async def is_user_member(user_id, bot):
    """Check if user is member of all required channels"""
    for channel in REQUIRED_CHANNELS:
        try:
            chat_member = await bot.get_chat_member(chat_id=f"@{channel}", user_id=user_id)
            if chat_member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            logger.error(f"Error checking channel membership: {e}")
            return False
    return True

async def ask_user_to_join(update: Update):
    """Show join buttons to user"""
    channel_buttons = [
        {"label": "𝐌𝐀𝐈𝐍 𝐂𝐇𝐀𝐍𝐍𝐄𝐋", "url": "https://t.me/Freenethubz"},
        {"label": "𝐂𝐇𝐀𝐍𝐍𝐄𝐋 𝐀𝐍𝐍𝐎𝐔𝐍𝐂𝐄𝐌𝐄𝐍𝐓", "url": "https://t.me/megahubbots"},
    ]
    
    buttons = [[InlineKeyboardButton(button["label"], url=button["url"])] for button in channel_buttons]
    buttons.append([InlineKeyboardButton("✅ 𝗩𝗲𝗿𝗶𝗳𝘆 𝗠𝗲𝗺𝗯𝗲𝗿𝘀𝗵𝗶𝗽", callback_data="verify_membership")])
    reply_markup = InlineKeyboardMarkup(buttons)
    
    await update.message.reply_text(
        "🚨 ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ʙᴏᴛ, ʏᴏᴜ ᴍᴜꜱᴛ ᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟꜱ ꜰɪʀꜱᴛ! 🚨"
        "ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴꜱ ʙᴇʟᴏᴡ ᴛᴏ ᴊᴏɪɴ, ᴛʜᴇɴ ᴘʀᴇꜱꜱ "
        "✅ 𝗩𝗲𝗿𝗶𝗳𝘆 𝗠𝗲𝗺𝗯𝗲𝗿𝘀𝗵𝗶𝗽' ᴛᴏ ᴠᴇʀɪꜰʏ.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def verify_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle membership verification callback"""
    query = update.callback_query
    await query.answer()
    
    if await is_user_member(query.from_user.id, context.bot):
        await query.message.edit_text("✅ 𝙑𝙚𝙧𝙞𝙛𝙞𝙘𝙖𝙩𝙞𝙤𝙣 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡! 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤𝙬 𝙪𝙨𝙚 𝙖𝙡𝙡 𝙗𝙤𝙩 𝙘𝙤𝙢𝙢𝙖𝙣𝙙𝙨.")
    else:
        await query.answer("❌ 𝙔𝙤𝙪 𝙝𝙖𝙫𝙚𝙣'𝙩 𝙟𝙤𝙞𝙣𝙚𝙙 𝙖𝙡𝙡 𝙘𝙝𝙖𝙣𝙣𝙚𝙡𝙨 𝙮𝙚𝙩!", show_alert=True)

def channel_required(func):
    """Decorator to enforce channel membership before executing any command"""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # Always allow admin commands
        if is_admin(user_id):
            return await func(update, context, *args, **kwargs)
            
        # Check channel membership
        if not await is_user_member(user_id, context.bot):
            await ask_user_to_join(update)
            return
        
        # If user is member, proceed with original command
        return await func(update, context, *args, **kwargs)
    return wrapped

# ==============================================
# Telegram Bot Command Handlers
# ==============================================

@channel_required
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user_id = update.effective_user.id
    
    # Process referral if included in start command
    if context.args and len(context.args) > 0:
        handle_referral(user_id, context.args[0])
    
    user = get_user(user_id)
    links_available = user['credits'] // CONFIG['cost_per_url']
    
    welcome_msg = f"""
👋 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 𝗟𝗶𝗻𝗸 𝗦𝗵𝗼𝗿𝘁𝗲𝗻𝗲𝗿 𝗕𝗼𝘁!
🔹 ʏᴏᴜ ᴄᴀɴ ꜱʜᴏʀᴛᴇɴ {links_available} ᴜʀʟꜱ ᴡɪᴛʜ ʏᴏᴜʀ ᴄᴜʀʀᴇɴᴛ ᴄʀᴇᴅɪᴛꜱ
🔹 ᴜꜱᴇ /profile ᴛᴏ ᴄʜᴇᴄᴋ ʏᴏᴜʀ ꜱᴛᴀᴛᴜꜱ
🔹 ᴜꜱᴇ /short_longurl ᴛᴏ ꜱʜᴏʀᴛᴇɴ ᴜʀʟꜱ
🔹 ᴜꜱᴇ /short_emoji ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴇᴍᴏᴊɪ ᴜʀʟꜱ
🔹 ᴜꜱᴇ /url_stats ᴛᴏ ᴄʜᴇᴄᴋ ᴜʀʟ ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ
🔹 ᴜꜱᴇ /referral ᴛᴏ ᴇᴀʀɴ ᴍᴏʀᴇ ᴄʀᴇᴅɪᴛꜱ
"""
    if is_admin(user_id):
        welcome_msg += """
👑 Admin Commands:
/stats - ᴠɪᴇᴡ ʙᴏᴛ ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ
/broadcast - ꜱᴇɴᴅ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ᴀʟʟ ᴜꜱᴇʀꜱ
/addcredits - ᴀᴅᴅ ᴄʀᴇᴅɪᴛꜱ ᴛᴏ �ᴜꜱᴇʀ
/removecredits - ʀᴇᴍᴏᴠᴇ ᴄʀᴇᴅɪᴛꜱ ꜰʀᴏᴍ ᴜꜱᴇʀ
"""
    await update.message.reply_text(welcome_msg)
    logger.info(f"Sent welcome message to user {user_id}")

# [Include all your other command handlers here (profile, buy_credits, referral, etc.) 
# with the same implementation as before, just using the MongoDB functions instead of file operations]


@channel_required
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /profile command - show user statistics"""
    user = get_user(update.effective_user.id)
    links_available = user['credits'] // CONFIG['cost_per_url']
    
    profile_msg = f"""
👤 𝗬𝗼𝘂𝗿 𝗣𝗿𝗼𝗳𝗶𝗹𝗲

🆔 𝐔𝐬𝐞𝐫 𝐈𝐃: {update.effective_user.id}
💰 𝐂𝐫𝐞𝐝𝐢𝐭𝐬: {user['credits']}
🎟 𝐋𝐢𝐧𝐤𝐬 𝐀𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞: {links_available}
📊 𝐓𝐨𝐭𝐚𝐥 𝐔𝐑𝐋𝐬 𝐜𝐫𝐞𝐚𝐭𝐞𝐝: {user['urls_created']}
🔗 𝐑𝐞𝐟𝐞𝐫𝐫𝐚𝐥𝐬: {user['referral_count']}
"""
    await update.message.reply_text(profile_msg)
    logger.info(f"Displayed profile for user {update.effective_user.id}")

@channel_required
async def buy_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /buycredits command - show credit packages"""
    keyboard = [[InlineKeyboardButton("Contact Developer", url="t.me/Silando")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    credits_msg = """
💳 𝐂𝐫𝐞𝐝𝐢𝐭𝐬 𝐏𝐚𝐜𝐤𝐚𝐠𝐞𝐬

🌀 10 ᴄʀᴇᴅɪᴛꜱ - $0.3 
💠 100 ᴄʀᴇᴅɪᴛꜱ - $2 
🌀 200 ᴄʀᴇᴅɪᴛꜱ - $3 
💠 500 ᴄʀᴇᴅɪᴛꜱ - $10  

📞 𝘊𝘰𝘯𝘵𝘢𝘤𝘵 𝘚𝘪𝘭𝘢𝘯𝘥𝘰 𝘋𝘦𝘷 𝘵𝘰 𝘉𝘶𝘺.
"""
    await update.message.reply_text(credits_msg, reply_markup=reply_markup)
    logger.info(f"Sent credit packages to user {update.effective_user.id}")

@channel_required
async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /referral command - show user's referral link"""
    user = get_user(update.effective_user.id)
    ref_link = f"https://t.me/{context.bot.username}?start={user['referral_code']}"
    
    ref_msg = f"""
📢 𝐑𝐞𝐟𝐞𝐫𝐫𝐚𝐥 𝐏𝐫𝐨𝐠𝐫𝐚𝐦

🔗 𝘠𝘰𝘶𝘳 𝘳𝘦𝘧𝘦𝘳𝘳𝘢𝘭 𝘭𝘪𝘯𝘬:
『 {ref_link} 』

💎 ʏᴏᴜ ɢᴇᴛ {CONFIG['referral_bonus']} ᴄʀᴇᴅɪᴛꜱ ꜰᴏʀ ᴇᴀᴄʜ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟ ʀᴇꜰᴇʀʀᴀʟ!
📊 ᴛᴏᴛᴀʟ ʀᴇꜰᴇʀʀᴀʟꜱ: {user['referral_count']}
"""
    await update.message.reply_text(ref_msg)
    logger.info(f"Sent referral info to user {update.effective_user.id}")
    

# ==============================================
# URL Shortening Features
# ==============================================

@channel_required
async def short_longurl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start URL shortening conversation"""
    user_id = update.effective_user.id
    if not has_sufficient_credits(user_id):
        await update.message.reply_text(
            f"❌ ʏᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴇɴᴏᴜɢʜ ᴄʀᴇᴅɪᴛꜱ. ᴄᴜʀʀᴇɴᴛ ᴄʀᴇᴅɪᴛꜱ: {get_user(user_id)['credits']}"
        )
        return ConversationHandler.END
    
    await update.message.reply_text("⚠️ ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴍᴇ ᴛʜᴇ ᴜʀʟ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ꜱʜᴏʀᴛᴇɴ:")
    return WAITING_FOR_URL

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process URL for shortening"""
    user_id = update.effective_user.id
    url = update.message.text
    
    try:
        if not url.startswith(('http://', 'https://')):
            raise ValueError("ᴜʀʟ ᴍᴜꜱᴛ ꜱᴛᴀʀᴛ ᴡɪᴛʜ http:// or https://")
        
        payload = {"url": url}
        headers = {"Accept": "application/json"}
        response = requests.post("https://spoo.me", data=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        short_url = response.json().get("short_url")
        if not short_url:
            raise ValueError("No short URL returned from API")
        
        deduct_credits(user_id)
        
        success_msg = f"""
┏━━◤ [✓] 𝐋𝐢𝐧𝐤 𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐞𝐝 ◥━━┓
『 {short_url} 』
"""
        await update.message.reply_text(success_msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    return ConversationHandler.END

# [Include all other URL shortening handlers (short_emoji, handle_emoji_url, etc.) 
# with the same implementation as before]

@channel_required
async def short_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start emoji URL shortening conversation"""
    user_id = update.effective_user.id
    if not has_sufficient_credits(user_id):
        await update.message.reply_text(
            f"❌ ʏᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴇɴᴏᴜɢʜ ᴄʀᴇᴅɪᴛꜱ. ᴄᴜʀʀᴇɴᴛ ᴄʀᴇᴅɪᴛꜱ: {get_user(user_id)['credits']}"
        )
        return ConversationHandler.END
    
    await update.message.reply_text("🎭 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴍᴇ ᴛʜᴇ ᴜʀʟ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ꜱʜᴏʀᴛᴇɴ ᴡɪᴛʜ ᴇᴍᴏᴊɪꜱ:")
    return WAITING_FOR_EMOJI_URL

async def handle_emoji_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process URL for emoji shortening"""
    user_id = update.effective_user.id
    url = update.message.text
    context.user_data['url_to_shorten'] = url
    
    await update.message.reply_text("😊 ɴᴏᴡ ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴍᴇ ᴛʜᴇ ᴇᴍᴏᴊɪꜱ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴜꜱᴇ:")
    return WAITING_FOR_EMOJIS

async def handle_emojis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process emojis and create shortened URL"""
    user_id = update.effective_user.id
    emojis = update.message.text
    url = context.user_data['url_to_shorten']
    
    try:
        if not emojis.strip():
            raise ValueError("Emoji sequence cannot be empty")
        
        # Use the same payload structure as the working script
        payload = {
            "url": url,
            "emojies": emojis  # Note: The API expects "emojies" not "emojis"
        }
        headers = {"Accept": "application/json"}
        
        response = requests.post(
            "https://spoo.me/emoji",
            data=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        
        short_url = response.json().get("short_url")
        if not short_url:
            raise ValueError("No short URL returned from API")
        
        deduct_credits(user_id)
        
        success_msg = f"""
┏━━◤ [✓] 𝐄𝐦𝐨𝐣𝐢 𝐋𝐢𝐧𝐤 ◥━━┓
『 {short_url} 』
"""
        await update.message.reply_text(success_msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    return ConversationHandler.END

@channel_required
async def url_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start URL statistics conversation"""
    await update.message.reply_text("📊 ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴍᴇ ᴛʜᴇ ꜱʜᴏʀᴛ ᴜʀʟ ᴛᴏ ɢᴇᴛ ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ:")
    return WAITING_FOR_STATS_URL

async def handle_stats_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retrieve and display URL statistics"""
    short_url = update.message.text
    
    try:
        if "spoo.me/" not in short_url:
            raise ValueError("ᴘʟᴇᴀꜱᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ Spoo.me URL")
        
        short_code = short_url.split("spoo.me/")[-1].split("/")[0]
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        # Try multiple endpoints with POST request
        endpoints = [
            f"https://spoo.me/stats/{short_code}",
            "https://spoo.me/stats",
            f"https://spoo.me/api/stats/{short_code}"
        ]
        
        response = None
        for endpoint in endpoints:
            try:
                response = requests.post(endpoint, data={"short_code": short_code}, headers=headers, timeout=10)
                if response.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                continue
        
        if not response or response.status_code != 200:
            raise ValueError("Failed to retrieve statistics")
        
        stats = response.json()
        stats_msg = f"""
```┏━━◤ 𝐔𝐑𝐋 𝐒𝐓𝐀𝐓𝐈𝐒𝐓𝐈𝐂𝐒 ◥━━┓
●━━━━━━━━━━━━━━━━━━━━●
╰┈➤ ꜱʜᴏʀᴛ ᴜʀʟ: https://spoo.me/{short_code}
●━━━━━━━━━━━━━━━━━━━━●
╰┈➤ ᴏʀɪɢɪɴᴀʟ ᴜʀʟ: {stats.get('url', 'N/A')}
●━━━━━━━━━━━━━━━━━━━━●
╰┈➤ ᴛᴏᴛᴀʟ ᴄʟɪᴄᴋꜱ: {stats.get('total-clicks', 0)}
●━━━━━━━━━━━━━━━━━━━━●
╰┈➤ ᴜɴɪQᴜᴇ ᴄʟɪᴄᴋꜱ: {stats.get('total_unique_clicks', 0)}
●━━━━━━━━━━━━━━━━━━━━●
╰┈➤ ᴄʀᴇᴀᴛᴇᴅ: {stats.get('creation-date', 'N/A')}
●━━━━━━━━━━━━━━━━━━━━●
╰┈➤ ʟᴀꜱᴛ ᴄʟɪᴄᴋ: {stats.get('last-click', 'N/A')}
●━━━━━━━━━━━━━━━━━━━━●
╰┈➤ ʙʀᴏᴡꜱᴇʀ: {stats.get('last-click-browser', 'N/A')}
●━━━━━━━━━━━━━━━━━━━━●
╰┈➤ ᴏꜱ: {stats.get('last-click-os', 'N/A')}
●━━━━━━━━━━━━━━━━━━━━● ```
"""
        await update.message.reply_text(stats_msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    return ConversationHandler.END


# ==============================================
# Admin Commands
# ==============================================

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin statistics (/stats command)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ This command is for admins only")
        return
    
    stats = get_stats()
    total_users = users_collection.count_documents({})
    
    stats_msg = f"""
📊 𝐀𝐝𝐦𝐢𝐧 𝐒𝐭𝐚𝐭𝐢𝐬𝐭𝐢𝐜𝐬
👥 ᴛᴏᴛᴀʟ ᴜꜱᴇʀꜱ: {total_users}
🔗 ᴛᴏᴛᴀʟ ᴜʀʟꜱ ᴄʀᴇᴀᴛᴇᴅ: {stats['total_urls_created']}
💰 ᴛᴏᴛᴀʟ ᴄʀᴇᴅɪᴛꜱ ᴜꜱᴇᴅ: {stats['total_credits_used']}
"""
    await update.message.reply_text(stats_msg)


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all users (/broadcast command)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ This command is for admins only")
        return
    
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /broadcast your_message_here")
        return
    
    message = ' '.join(context.args)
    sent_count = 0
    
    for user in users_collection.find({}, {'user_id': 1}):
        user_id = user['user_id']
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
    
    total_users = users_collection.count_documents({})
    await update.message.reply_text(f"📢 Broadcast sent to {sent_count}/{total_users} users")

async def add_credits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add credits to user (/addcredits command)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ This command is for admins only")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("⚠️ Usage: /addcredits user_id amount")
        return
    
    user_id, amount = context.args
    try:
        amount = int(amount)
        add_credits(int(user_id), amount)
        await update.message.reply_text(f"✅ Added {amount} credits to user {user_id}")
        
        # Notify the user
        notification = f"""
📢 𝐀𝐝𝐦𝐢𝐧 𝐍𝐨𝐭𝐢𝐟𝐢𝐜𝐚𝐭𝐢𝐨𝐧

➕ ʏᴏᴜ ʀᴇᴄᴇɪᴠᴇᴅ {amount} ᴄʀᴇᴅɪᴛꜱ ꜰʀᴏᴍ ᴀᴅᴍɪɴ!
💰 ʏᴏᴜʀ ɴᴇᴡ ʙᴀʟᴀɴᴄᴇ: {get_user(int(user_id))['credits']} ᴄʀᴇᴅɪᴛꜱ
"""
        await notify_user(context.bot, int(user_id), notification)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def remove_credits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove credits from user (/removecredits command)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ This command is for admins only")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("⚠️ Usage: /removecredits user_id amount")
        return
    
    user_id, amount = context.args
    try:
        amount = int(amount)
        user = get_user(int(user_id))
        user['credits'] = max(0, user['credits'] - amount)
        # No need to call save_database() as MongoDB automatically saves changes
        await update.message.reply_text(f"✅ Removed {amount} credits from user {user_id}")
        
        # Notify the user
        notification = f"""
📢 𝐀𝐝𝐦𝐢𝐧 𝐍𝐨𝐭𝐢𝐟𝐢𝐜𝐚𝐭𝐢𝐨𝐧

➖ {amount} ᴄʀᴇᴅɪᴛꜱ ᴡᴇʀᴇ ʀᴇᴍᴏᴠᴇᴅ ʙʏ ᴀᴅᴍɪɴ
💰 ʏᴏᴜʀ ɴᴇᴡ ʙᴀʟᴀɴᴄᴇ: {user['credits']} ᴄʀᴇᴅɪᴛꜱ
"""
        await notify_user(context.bot, int(user_id), notification)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ==============================================
# Bot Setup and Startup
# ==============================================

def main() -> None:
    """Start the bot with all handlers configured."""
    application = Application.builder().token(CONFIG['token']).build()
    
    # Add conversation handlers
    conv_handler_url = ConversationHandler(
        entry_points=[CommandHandler('short_longurl', short_longurl)],
        states={
            WAITING_FOR_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url)],
        },
        fallbacks=[]
    )
    conv_handler_emoji = ConversationHandler(
        entry_points=[CommandHandler('short_emoji', short_emoji)],
        states={
            WAITING_FOR_EMOJI_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_emoji_url)],
            WAITING_FOR_EMOJIS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_emojis)],
        },
        fallbacks=[]
    )
    
    conv_handler_stats = ConversationHandler(
        entry_points=[CommandHandler('url_stats', url_stats)],
        states={
            WAITING_FOR_STATS_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_stats_url)],
        },
        fallbacks=[]
    )
    
    
    # Add all handlers with the channel requirement
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('profile', profile))
    application.add_handler(CommandHandler('buycredits', buy_credits))
    application.add_handler(CommandHandler('referral', referral))
    
    # Add conversation handlers (they'll check membership in their entry points)
    application.add_handler(conv_handler_url)
    application.add_handler(conv_handler_emoji)
    application.add_handler(conv_handler_stats)
    
    # Admin handlers don't need the decorator (handled in decorator logic)
    application.add_handler(CommandHandler('stats', admin_stats))
    application.add_handler(CommandHandler('broadcast', broadcast))
    application.add_handler(CommandHandler('addcredits', add_credits_cmd))
    application.add_handler(CommandHandler('removecredits', remove_credits_cmd))
    
    # Add callback handler for membership verification
    application.add_handler(CallbackQueryHandler(verify_membership, pattern="^verify_membership$"))
    
    # Start the bot
    application.run_polling()
    logger.info("Bot started and running")

if __name__ == '__main__':
    main()
