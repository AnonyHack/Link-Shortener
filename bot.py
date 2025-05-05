import os
import json
import asyncio
import logging
import requests
from functools import wraps
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

# ==============================================
# Initialization and Configuration
# ==============================================

# Configure logging to track bot activity and errors
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('url_shortener_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Bot configuration - replace with your actual values
CONFIG = {
    'token': '7514902513:AAFjNOE7V2LeBnFWXz5a2OwdByS8e-EcHnk',  # Get from @BotFather
    'admin_ids': [5962658076, 6211392720],          # Your Telegram user ID
    'welcome_credits': 15,               # Credits for new users
    'cost_per_url': 5,                   # Credits per URL shortening
    'referral_bonus': 5,                 # Credits for successful referral
    'database_file': 'user_data.json'     # File to store user data
}

# ==============================================
# Database Management Functions
# ==============================================

def load_database():
    """Load user data from JSON file or create new database if none exists"""
    try:
        if os.path.exists(CONFIG['database_file']):
            with open(CONFIG['database_file'], 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load database: {e}")
    
    # Return fresh database structure if file doesn't exist or error occurs
    return {
        'users': {},
        'stats': {
            'total_urls_created': 0,
            'total_credits_used': 0
        },
        'referrals': {}
    }

def save_database():
    """Save current database state to file"""
    try:
        with open(CONFIG['database_file'], 'w') as f:
            json.dump(DB, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save database: {e}")

# Initialize database
DB = load_database()

# === FORCE JOIN CONFIGURATION ===
REQUIRED_CHANNELS = ["megahubbots"]  # Replace with your channel usernames

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
      #  {"label": "BACKUP CHANNEL", "url": "https://t.me/Freenethubchannel"},
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
        # No need to restart - the next command will work automatically
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
# Helper Functions
# ==============================================

def is_admin(user_id: int) -> bool:
    """Check if user has admin privileges"""
    return user_id in CONFIG['admin_ids']

def get_user(user_id: int) -> dict:
    """Get user data or create new user record if doesn't exist"""
    if str(user_id) not in DB['users']:
        DB['users'][str(user_id)] = {
            'credits': CONFIG['welcome_credits'],
            'urls_created': 0,
            'referral_code': f"ref{user_id}",
            'referred_by': None,
            'referral_count': 0
        }
        save_database()
        logger.info(f"Created new user: {user_id}")
    return DB['users'][str(user_id)]

def has_sufficient_credits(user_id: int) -> bool:
    """Check if user has enough credits for URL shortening"""
    user = get_user(user_id)
    return user['credits'] >= CONFIG['cost_per_url']

def deduct_credits(user_id: int):
    """Subtract credits after successful URL shortening"""
    user = get_user(user_id)
    user['credits'] -= CONFIG['cost_per_url']
    user['urls_created'] += 1
    DB['stats']['total_urls_created'] += 1
    DB['stats']['total_credits_used'] += CONFIG['cost_per_url']
    save_database()
    logger.info(f"Deducted credits from user {user_id}. Remaining: {user['credits']}")

def add_credits(user_id: int, amount: int):
    """Add credits to user's balance"""
    user = get_user(user_id)
    user['credits'] += amount
    save_database()
    logger.info(f"Added {amount} credits to user {user_id}. New total: {user['credits']}")

def handle_referral(user_id: int, ref_code: str):
    """Process referral link usage"""
    # Find referring user
    referring_user = next(
        (u for u in DB['users'].values() if u['referral_code'] == ref_code),
        None
    )
    
    if referring_user and str(user_id) not in DB['users']:
        # New user came through referral link
        get_user(user_id)  # Create user record
        DB['users'][str(user_id)]['referred_by'] = ref_code
        referring_user['referral_count'] += 1
        referring_user['credits'] += CONFIG['referral_bonus']
        save_database()
        
        # Notify the referring user
        notification = f"""
🎉 𝙉𝙚𝙬 𝙍𝙚𝙛𝙚𝙧𝙧𝙖𝙡!

👤 𝚂𝚘𝚖𝚎𝚘𝚗𝚎 𝚓𝚘𝚒𝚗𝚎𝚍 𝚞𝚜𝚒𝚗𝚐 𝚢𝚘𝚞𝚛 𝚛𝚎𝚏𝚎𝚛𝚛𝚊𝚕 𝚕𝚒𝚗𝚔!
➕ 𝚈𝚘𝚞 𝚛𝚎𝚌𝚎𝚒𝚟𝚎𝚍 {CONFIG['referral_bonus']} 𝚌𝚛𝚎𝚍𝚒𝚝𝚜
💰 𝚈𝚘𝚞𝚛 𝚗𝚎𝚠 𝚋𝚊𝚕𝚊𝚗𝚌𝚎: {referring_user['credits']} 𝚌𝚛𝚎𝚍𝚒𝚝𝚜
"""
        asyncio.run_coroutine_threadsafe(
            notify_user(Application.builder().token(CONFIG['token']).build().bot, 
                      int(next(k for k, v in DB['users'].items() if v['referral_code'] == ref_code)), 
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
# Telegram Bot Command Handlers (Basic Commands)
# ==============================================
@channel_required
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - welcome message and referral processing"""
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
    
    # Add admin commands section if user is admin
    if is_admin(user_id):
        welcome_msg += """
👑 Admin Commands:
/stats - ᴠɪᴇᴡ ʙᴏᴛ ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ
/broadcast - ꜱᴇɴᴅ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ᴀʟʟ ᴜꜱᴇʀꜱ
/addcredits - ᴀᴅᴅ ᴄʀᴇᴅɪᴛꜱ ᴛᴏ ᴜꜱᴇʀ
/removecredits - ʀᴇᴍᴏᴠᴇ ᴄʀᴇᴅɪᴛꜱ ꜰʀᴏᴍ ᴜꜱᴇʀ
"""
    
    welcome_msg += """
📝 ʜᴏᴡ ᴛᴏ ꜱʜᴏʀᴛᴇɴ ᴜʀʟꜱ:
ᴇxᴀᴍᴘʟᴇ:
1) ꜱᴇɴᴅ /short_longurl 
2) ᴛʜᴇɴ ꜱᴇɴᴅ ʏᴏᴜʀ ᴜʀʟ https://example.com
"""
    await update.message.reply_text(welcome_msg)
    logger.info(f"Sent welcome message to user {user_id}")

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

# Conversation states
WAITING_FOR_URL, WAITING_FOR_EMOJI_URL, WAITING_FOR_EMOJIS, WAITING_FOR_STATS_URL = range(4)

@channel_required
async def short_longurl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start URL shortening conversation"""
    user_id = update.effective_user.id
    if not has_sufficient_credits(user_id):
        await update.message.reply_text(
            f"❌ ʏᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴇɴᴏᴜɢʜ ᴄʀᴇᴅɪᴛꜱ. ᴄᴜʀʀᴇɴᴛ ᴄʀᴇᴅɪᴛꜱ: {get_user(user_id)['credits']}"
        )
        logger.warning(f"User {user_id} tried to shorten URL with insufficient credits")
        return ConversationHandler.END
    
    await update.message.reply_text("⚠️ ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴍᴇ ᴛʜᴇ ᴜʀʟ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ꜱʜᴏʀᴛᴇɴ:")
    logger.info(f"User {user_id} started URL shortening")
    return WAITING_FOR_URL

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process URL for shortening"""
    user_id = update.effective_user.id
    url = update.message.text
    
    try:
        # Validate URL format
        if not url.startswith(('http://', 'https://')):
            raise ValueError("ᴜʀʟ ᴍᴜꜱᴛ ꜱᴛᴀʀᴛ ᴡɪᴛʜ http:// or https://")
        
        # Call Spoo.me API
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
        logger.info(f"Successfully shortened URL for user {user_id}")
    except Exception as e:
        error_msg = f"❌ Error: {str(e)}"
        await update.message.reply_text(error_msg)
        logger.error(f"URL shortening failed for user {user_id}: {e}")
    
    return ConversationHandler.END

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
    
    stats_msg = f"""
📊 𝐀𝐝𝐦𝐢𝐧 𝐒𝐭𝐚𝐭𝐢𝐬𝐭𝐢𝐜𝐬

👥 ᴛᴏᴛᴀʟ ᴜꜱᴇʀꜱ: {len(DB['users'])}
🔗 ᴛᴏᴛᴀʟ ᴜʀʟꜱ ᴄʀᴇᴀᴛᴇᴅ: {DB['stats']['total_urls_created']}
💰 ᴛᴏᴛᴀʟ ᴄʀᴇᴅɪᴛꜱ ᴜꜱᴇᴅ: {DB['stats']['total_credits_used']}
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
    
    for user_id in DB['users']:
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
    
    await update.message.reply_text(f"📢 Broadcast sent to {sent_count}/{len(DB['users'])} users")

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
        save_database()
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