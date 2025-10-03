import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
from telegram.constants import ParseMode

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

OWNER_ID = 6291633980
BOT_TOKEN = '8360747994:AAE10LHzvxgksDE-TuF3-nMJQVDqKbvL7Vs'
OWNER_NAME = "صُـ,ـقٌـ,ـر"
CHANNEL_LINK = "https://t.me/Haraaaaaabwsalam"

DATA_FILE = 'bot_data.json'
STATS_FILE = 'stats.json'

REPLY_STATE, BROADCAST_STATE, WELCOME_STATE, ADD_ADMIN_STATE, REMOVE_ADMIN_STATE, BAN_STATE, UNBAN_STATE, ADD_VIP_STATE, REMOVE_VIP_STATE, ADD_WARNING_STATE, REMOVE_WARNING_STATE, ADMIN_PERMISSIONS_STATE, ADD_CHANNEL_STATE, REMOVE_CHANNEL_STATE = range(14)

PERMISSION_KEYS = {
    'manage_users': '🚫 إدارة المستخدمين (حظر/فك حظر)',
    'manage_vip': '⭐ إدارة VIP',
    'manage_warnings': '⚠️ إدارة التحذيرات',
    'manage_admins': '👥 إدارة الإداريين',
    'broadcast': '📢 البث الجماعي',
    'view_stats': '📊 عرض الإحصائيات',
    'auto_replies': '🤖 الردود التلقائية',
    'welcome_msg': '📝 رسالة الترحيب',
    'maintenance': '🔧 وضع الصيانة',
    'reply_messages': '💬 الرد على الرسائل'
}

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            if not data.get('data_version'):
                data['data_version'] = 1
                
            if data.get('data_version') == 1:
                if isinstance(data.get('admins'), list) and len(data['admins']) > 0 and isinstance(data['admins'][0], str):
                    old_admins = data['admins']
                    data['admins'] = []
                    for admin_id in old_admins:
                        user_info = data['users'].get(admin_id, {})
                        data['admins'].append({
                            'user_id': admin_id,
                            'username': user_info.get('username', 'لا يوجد'),
                            'full_access': False,
                            'permissions': {
                                'manage_users': True,
                                'manage_vip': True,
                                'manage_warnings': True,
                                'manage_admins': False,
                                'broadcast': False,
                                'view_stats': True,
                                'auto_replies': False,
                                'welcome_msg': False,
                                'maintenance': False,
                                'reply_messages': True
                            }
                        })
                    data['data_version'] = 2
                    save_data(data)
                    logger.info(f"Migrated {len(old_admins)} admins to new permission system")
            
            return data
            
    return {
        'data_version': 2,
        'users': {},
        'admins': [],
        'banned': [],
        'vip': [],
        'messages': {},
        'warnings': {},
        'auto_reply': {},
        'welcome_msg': 'مرحباً بك! 👋\nيمكنك الآن إرسال رسالتك للمالك',
        'welcome_enabled': True,
        'maintenance': False,
        'replies_enabled': True,
        'force_subscribe': {
            'enabled': False,
            'channels': []
        }
    }

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'total_messages': 0,
        'total_users': 0,
        'messages_today': 0,
        'last_reset': str(datetime.now().date())
    }

def save_stats(stats):
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

bot_data = load_data()
stats = load_stats()

async def resolve_user_identifier(identifier: str, context: ContextTypes.DEFAULT_TYPE):
    original_identifier = identifier.strip()
    
    if original_identifier.isdigit():
        return original_identifier
    
    clean_identifier = original_identifier
    if clean_identifier.startswith('@'):
        clean_identifier = clean_identifier[1:]
    
    if clean_identifier.startswith('https://t.me/'):
        clean_identifier = clean_identifier.replace('https://t.me/', '')
    elif clean_identifier.startswith('t.me/'):
        clean_identifier = clean_identifier.replace('t.me/', '')
    
    for user_id, user_info in bot_data['users'].items():
        if user_info.get('username', '').lower() == clean_identifier.lower():
            return user_id
    
    try:
        chat = await context.bot.get_chat('@' + clean_identifier)
        return str(chat.id)
    except Exception as e:
        logger.error(f"Failed to resolve user identifier '{original_identifier}': {e}")
        pass
    
    return None

async def fetch_user_info(user_id: str, context: ContextTypes.DEFAULT_TYPE, from_update: Update = None):
    if from_update and from_update.message and from_update.message.forward_from:
        forwarded_user = from_update.message.forward_from
        user_info = {
            'name': forwarded_user.full_name or forwarded_user.first_name or 'مجهول',
            'username': forwarded_user.username or 'لا يوجد',
            'join_date': str(datetime.now()),
            'message_count': 0
        }
        if str(user_id) not in bot_data['users']:
            bot_data['users'][str(user_id)] = user_info
        else:
            bot_data['users'][str(user_id)]['name'] = user_info['name']
            bot_data['users'][str(user_id)]['username'] = user_info['username']
        save_data(bot_data)
        return user_info
    
    try:
        chat = await context.bot.get_chat(int(user_id))
        user_info = {
            'name': chat.full_name or chat.first_name or f'User_{user_id[:8]}',
            'username': chat.username or 'لا يوجد',
            'join_date': str(datetime.now()),
            'message_count': 0
        }
        
        if str(user_id) not in bot_data['users']:
            bot_data['users'][str(user_id)] = user_info
        else:
            bot_data['users'][str(user_id)]['name'] = user_info['name']
            bot_data['users'][str(user_id)]['username'] = user_info['username']
        
        save_data(bot_data)
        return user_info
    except Exception as e:
        logger.info(f"Could not fetch user info for {user_id}, user hasn't interacted with bot: {e}")
        if str(user_id) in bot_data['users']:
            return bot_data['users'][str(user_id)]
        
        placeholder_info = {
            'name': f'User_{user_id[:8]}',
            'username': 'لا يوجد',
            'join_date': str(datetime.now()),
            'message_count': 0
        }
        bot_data['users'][str(user_id)] = placeholder_info
        save_data(bot_data)
        return placeholder_info

def is_banned(user_id: int) -> bool:
    return str(user_id) in bot_data['banned']

async def check_user_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    if user_id == OWNER_ID:
        return True, None
    
    if not bot_data.get('force_subscribe', {}).get('enabled', False):
        return True, None
    
    channels = bot_data.get('force_subscribe', {}).get('channels', [])
    if not channels:
        return True, None
    
    not_subscribed = []
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(channel['id'], user_id)
            if member.status in ['left', 'kicked']:
                not_subscribed.append(channel)
        except Exception as e:
            logger.error(f"Error checking subscription for channel {channel.get('name', channel['id'])}: {e}")
            not_subscribed.append(channel)
    
    if not_subscribed:
        return False, not_subscribed
    return True, None

async def send_force_subscribe_message(update: Update, not_subscribed_channels: list):
    keyboard = []
    for channel in not_subscribed_channels:
        channel_name = channel.get('username', channel['name'])
        if channel.get('username'):
            keyboard.append([InlineKeyboardButton(f"📺 {channel_name}", url=f"https://t.me/{channel['username'].replace('@', '')}")])
    
    text = "⚠️ <b>يجب الاشتراك في القنوات التالية أولاً:</b>\n\n"
    text += "\n".join([f"📺 {ch.get('username', ch['name'])}" for ch in not_subscribed_channels])
    text += "\n\n<i>بعد الاشتراك، أرسل /start للبدء</i>"
    
    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

def get_admin_record(user_id: int):
    if user_id == OWNER_ID:
        return {
            'user_id': str(OWNER_ID),
            'username': OWNER_NAME,
            'full_access': True,
            'is_owner': True,
            'permissions': {key: True for key in PERMISSION_KEYS.keys()}
        }
    
    for admin in bot_data['admins']:
        if str(admin['user_id']) == str(user_id):
            return admin
    return None

def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    return any(str(admin['user_id']) == str(user_id) for admin in bot_data['admins'])

def has_permission(user_id: int, permission: str) -> bool:
    admin_record = get_admin_record(user_id)
    if not admin_record:
        return False
    
    if admin_record.get('full_access') or admin_record.get('is_owner'):
        return True
    
    return admin_record.get('permissions', {}).get(permission, False)

def is_vip(user_id: int) -> bool:
    return str(user_id) in bot_data['vip']

def format_user_link(user_id: str, name: str = None, username: str = None) -> str:
    if not name:
        user_info = bot_data['users'].get(user_id, {})
        name = user_info.get('name', 'مجهول')
        username = user_info.get('username', 'لا يوجد')
    
    link = f'<a href="tg://openmessage?user_id={user_id}">{name}</a>'
    if username and username != 'لا يوجد':
        return f'{link} (@{username})'
    return link

async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else 0
    
    if user_id != OWNER_ID:
        if update.message:
            await update.message.reply_text("⛔ عذراً، هذا الأمر للمالك فقط!")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("📊 الإحصائيات", callback_data="stats"),
            InlineKeyboardButton("👥 المستخدمين", callback_data="users_list")
        ],
        [
            InlineKeyboardButton("📢 إذاعة رسالة", callback_data="broadcast"),
            InlineKeyboardButton("📨 الرسائل المعلقة", callback_data="pending_msgs")
        ],
        [
            InlineKeyboardButton("🔨 الإداريين", callback_data="admins_panel"),
            InlineKeyboardButton("🚫 المحظورين", callback_data="banned_list")
        ],
        [
            InlineKeyboardButton("⭐ VIP", callback_data="vip_panel")
        ],
        [
            InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings"),
            InlineKeyboardButton("🔧 الصيانة", callback_data="maintenance")
        ],
        [
            InlineKeyboardButton("📝 رسالة الترحيب", callback_data="welcome_msg"),
            InlineKeyboardButton("⚠️ التحذيرات", callback_data="warnings_panel")
        ],
        [
            InlineKeyboardButton("📺 القنوات الإجبارية", callback_data="force_subscribe_panel")
        ],
        [
            InlineKeyboardButton("📤 تصدير البيانات", callback_data="export_data"),
            InlineKeyboardButton("📈 تقرير مفصل", callback_data="detailed_report")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
🎛️ <b>لوحة تحكم البوت</b>

👤 المالك: {OWNER_NAME}
🆔 ID: <code>{OWNER_ID}</code>
📢 القناة: {CHANNEL_LINK}

━━━━━━━━━━━━━━━
اختر من القائمة أدناه:
    """
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    user = update.effective_user
    user_id = user.id
    
    if is_banned(user_id):
        await update.message.reply_text("🚫 أنت محظور من استخدام البوت!")
        return
    
    if bot_data['maintenance'] and user_id != OWNER_ID:
        await update.message.reply_text("🔧 البوت في وضع الصيانة حالياً")
        return
    
    is_subscribed, not_subscribed_channels = await check_user_subscribed(user_id, context)
    if not is_subscribed and not_subscribed_channels:
        await send_force_subscribe_message(update, not_subscribed_channels)
        return
    
    is_new_user = str(user_id) not in bot_data['users']
    
    if is_new_user:
        bot_data['users'][str(user_id)] = {
            'name': user.full_name,
            'username': user.username or 'لا يوجد',
            'join_date': str(datetime.now()),
            'message_count': 0
        }
        save_data(bot_data)
        stats['total_users'] += 1
        save_stats(stats)
    
    if user_id == OWNER_ID:
        await owner_panel(update, context)
        return
    
    keyboard = [
        [KeyboardButton("📨 إرسال رسالة")],
        [KeyboardButton("ℹ️ معلومات")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    if is_new_user and bot_data.get('welcome_enabled', True):
        welcome_text = f"""
{bot_data['welcome_msg']}

━━━━━━━━━━━━━━━
👤 اسمك: {user.full_name}
🆔 ID: <code>{user_id}</code>

📢 قناة المالك: {CHANNEL_LINK}
        """
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        simple_text = f"""
👋 مرحباً {user.full_name}!

يمكنك إرسال رسالتك للمالك من خلال الأزرار أدناه.

📢 قناة المالك: {CHANNEL_LINK}
        """
        await update.message.reply_text(simple_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    today = str(datetime.now().date())
    if stats['last_reset'] != today:
        stats['messages_today'] = 0
        stats['last_reset'] = today
        save_stats(stats)
    
    text = f"""
📊 <b>إحصائيات البوت</b>

👥 إجمالي المستخدمين: {len(bot_data['users'])}
📨 إجمالي الرسائل: {stats['total_messages']}
📩 رسائل اليوم: {stats['messages_today']}

🔨 عدد الإداريين: {len(bot_data['admins'])}
🚫 المحظورين: {len(bot_data['banned'])}
⭐ VIP: {len(bot_data['vip'])}

📅 آخر تحديث: {datetime.now().strftime('%Y-%m-%d %H:%M')}
    """
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("📋 قائمة كاملة", callback_data="full_users_list"),
            InlineKeyboardButton("🆕 الجدد", callback_data="new_users")
        ],
        [
            InlineKeyboardButton("💬 الأكثر نشاطاً", callback_data="active_users"),
            InlineKeyboardButton("😴 غير نشط", callback_data="inactive_users")
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]
    ]
    
    text = f"👥 <b>إدارة المستخدمين</b>\n\nإجمالي: {len(bot_data['users'])} مستخدم"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def full_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    users_text = ""
    for user_id, user_info in list(bot_data['users'].items())[:20]:
        users_text += f"• {user_info['name']} - <code>{user_id}</code>\n"
    
    if not users_text:
        users_text = "لا يوجد مستخدمين"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="users_list")]]
    text = f"📋 <b>قائمة المستخدمين</b>\n\n{users_text}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def new_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    sorted_users = sorted(bot_data['users'].items(), key=lambda x: x[1]['join_date'], reverse=True)[:10]
    users_text = ""
    for user_id, user_info in sorted_users:
        users_text += f"• {user_info['name']} - <code>{user_id}</code>\n"
    
    if not users_text:
        users_text = "لا يوجد مستخدمين"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="users_list")]]
    text = f"🆕 <b>المستخدمين الجدد</b>\n\n{users_text}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def active_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    sorted_users = sorted(bot_data['users'].items(), key=lambda x: x[1].get('message_count', 0), reverse=True)[:10]
    users_text = ""
    for user_id, user_info in sorted_users:
        msg_count = user_info.get('message_count', 0)
        users_text += f"• {user_info['name']} - {msg_count} رسالة\n"
    
    if not users_text:
        users_text = "لا يوجد مستخدمين"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="users_list")]]
    text = f"💬 <b>الأكثر نشاطاً</b>\n\n{users_text}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def inactive_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    sorted_users = sorted(bot_data['users'].items(), key=lambda x: x[1].get('message_count', 0))[:10]
    users_text = ""
    for user_id, user_info in sorted_users:
        msg_count = user_info.get('message_count', 0)
        users_text += f"• {user_info['name']} - {msg_count} رسالة\n"
    
    if not users_text:
        users_text = "لا يوجد مستخدمين"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="users_list")]]
    text = f"😴 <b>غير نشط</b>\n\n{users_text}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def pending_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    pending = []
    for msg_id, msg_info in bot_data['messages'].items():
        if not msg_info.get('replied', False):
            pending.append((msg_id, msg_info))
    
    if not pending:
        text = "📭 <b>لا توجد رسائل معلقة</b>"
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]]
    else:
        text = f"📨 <b>الرسائل المعلقة</b>\n\nعدد الرسائل: {len(pending)}\n\n"
        keyboard = []
        for msg_id, msg_info in pending[:5]:
            user_name = msg_info.get('user_name', 'مجهول')
            keyboard.append([InlineKeyboardButton(f"📩 {user_name}", callback_data=f"view_msg_{msg_id}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def view_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    msg_id = query.data.split("_")[2]
    
    if msg_id not in bot_data['messages']:
        await query.answer("❌ الرسالة غير موجودة", show_alert=True)
        return
    
    msg_info = bot_data['messages'][msg_id]
    
    text = f"""
📨 <b>رسالة من مستخدم</b>

👤 الاسم: {msg_info['user_name']}
🆔 ID: <code>{msg_info['user_id']}</code>
👁 Username: @{msg_info.get('username', 'لا يوجد')}
📅 التاريخ: {msg_info['date'][:19]}

━━━━━━━━━━━━━━━
💬 الرسالة:
{msg_info['message']}
    """
    
    keyboard = [
        [InlineKeyboardButton("💬 رد", callback_data=f"reply_{msg_info['user_id']}")],
        [InlineKeyboardButton("🚫 حظر", callback_data=f"ban_{msg_info['user_id']}"),
         InlineKeyboardButton("⭐ VIP", callback_data=f"vip_{msg_info['user_id']}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="pending_msgs")]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📢 إرسال للجميع", callback_data="broadcast_all")],
        [InlineKeyboardButton("⭐ إرسال لـ VIP", callback_data="broadcast_vip")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]
    ]
    
    text = "📢 <b>إذاعة الرسائل</b>\n\nاختر نوع الإذاعة:"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def broadcast_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    context.user_data['broadcast_type'] = 'all'
    
    text = "✍️ <b>إذاعة للجميع</b>\n\nأرسل الرسالة الآن:\n\n(أرسل /cancel للإلغاء)"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    
    return BROADCAST_STATE

async def broadcast_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    context.user_data['broadcast_type'] = 'vip'
    
    text = "✍️ <b>إذاعة لـ VIP</b>\n\nأرسل الرسالة الآن:\n\n(أرسل /cancel للإلغاء)"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    
    return BROADCAST_STATE

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
        
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    
    message = update.message.text or ""
    broadcast_type = context.user_data.get('broadcast_type', 'all')
    
    success = 0
    failed = 0
    
    if broadcast_type == 'all':
        targets = list(bot_data['users'].keys())
    else:
        targets = bot_data['vip']
    
    for user_id in targets:
        try:
            await context.bot.send_message(chat_id=int(user_id), text=message, parse_mode=ParseMode.HTML)
            success += 1
        except:
            failed += 1
    
    await update.message.reply_text(f"✅ تم الإرسال لـ {success} مستخدم\n❌ فشل: {failed}")
    
    context.user_data.clear()
    return ConversationHandler.END

async def admins_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    admins_list = []
    for admin in bot_data['admins']:
        admin_id = admin['user_id']
        user_info = bot_data['users'].get(admin_id, {})
        user_name = user_info.get('name', 'مجهول')
        username = user_info.get('username', 'لا يوجد')
        user_link = format_user_link(admin_id, user_name, username)
        
        access_badge = " 🔑" if admin.get('full_access') else ""
        perms_count = sum(1 for v in admin.get('permissions', {}).values() if v)
        admins_list.append(f"• {user_link}{access_badge}\n  📋 الصلاحيات: {perms_count}/{len(PERMISSION_KEYS)}")
    
    admins_text = "\n\n".join(admins_list) if admins_list else "لا يوجد إداريين"
    
    keyboard = [
        [InlineKeyboardButton("➕ إضافة إداري", callback_data="add_admin_info")],
        [InlineKeyboardButton("➖ حذف إداري", callback_data="remove_admin_info")],
        [InlineKeyboardButton("⚙️ تعديل صلاحيات", callback_data="edit_admin_permissions")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]
    ]
    
    text = f"🔨 <b>الإداريين</b> ({len(bot_data['admins'])})\n\n{admins_text}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    banned_users = []
    for banned_id in bot_data['banned']:
        user_link = format_user_link(banned_id)
        banned_users.append(f"• {user_link}")
    
    banned_text = "\n".join(banned_users) if banned_users else "لا يوجد محظورين"
    
    keyboard = [
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="ban_user_info")],
        [InlineKeyboardButton("✅ إلغاء حظر", callback_data="unban_user_info")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]
    ]
    
    text = f"🚫 <b>المحظورين</b> ({len(bot_data['banned'])})\n\n{banned_text}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def vip_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    vip_users = []
    for vip_id in bot_data['vip']:
        user_link = format_user_link(vip_id)
        vip_users.append(f"⭐ {user_link}")
    
    vip_text = "\n".join(vip_users) if vip_users else "لا يوجد مستخدمين VIP"
    
    keyboard = [
        [InlineKeyboardButton("⭐ إضافة VIP", callback_data="add_vip_info")],
        [InlineKeyboardButton("➖ إزالة VIP", callback_data="remove_vip_info")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]
    ]
    
    text = f"⭐ <b>مستخدمين VIP</b> ({len(bot_data['vip'])})\n\n{vip_text}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    replies_status = "✅ مفعل" if bot_data['replies_enabled'] else "❌ معطل"
    
    keyboard = [
        [InlineKeyboardButton(f"💬 الردود: {replies_status}", callback_data="toggle_replies")],
        [InlineKeyboardButton("🔄 إعادة تعيين", callback_data="reset_confirm")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]
    ]
    
    text = "⚙️ <b>الإعدادات</b>\n\nتخصيص إعدادات البوت"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def maintenance_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    status = "✅ مفعل" if bot_data['maintenance'] else "❌ معطل"
    
    keyboard = [
        [InlineKeyboardButton(f"وضع الصيانة: {status}", callback_data="toggle_maintenance")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]
    ]
    
    text = "🔧 <b>وضع الصيانة</b>\n\nعند التفعيل، لن يتمكن المستخدمون من استخدام البوت"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def welcome_msg_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    import html
    current_msg = html.escape(bot_data['welcome_msg'])
    welcome_status = "✅ مفعلة" if bot_data.get('welcome_enabled', True) else "❌ معطلة"
    
    keyboard = [
        [InlineKeyboardButton(f"الترحيب التلقائي: {welcome_status}", callback_data="toggle_welcome")],
        [InlineKeyboardButton("✏️ تعديل الرسالة", callback_data="edit_welcome")],
        [InlineKeyboardButton("🔄 استعادة الافتراضية", callback_data="reset_welcome")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]
    ]
    
    text = f"📝 <b>رسالة الترحيب</b>\n\n<b>الحالة:</b> {welcome_status}\n<b>الرسالة الحالية:</b>\n\n{current_msg}\n\n<i>استخدم /setwelcome لتعديل الرسالة</i>"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def warnings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    warnings_list = []
    total_warns = 0
    for user_id, count in bot_data['warnings'].items():
        user_link = format_user_link(user_id)
        warnings_list.append(f"⚠️ {user_link}: {count} تحذير")
        total_warns += count
    
    warnings_text = "\n".join(warnings_list) if warnings_list else "لا توجد تحذيرات"
    
    keyboard = [
        [InlineKeyboardButton("⚠️ إضافة تحذير", callback_data="add_warning_info")],
        [InlineKeyboardButton("➖ حذف تحذير", callback_data="remove_warning_info")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]
    ]
    
    text = f"⚠️ <b>التحذيرات</b>\nالمستخدمين: {len(bot_data['warnings'])} | الإجمالي: {total_warns}\n\n{warnings_text}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def force_subscribe_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    force_sub = bot_data.get('force_subscribe', {'enabled': False, 'channels': []})
    status = "✅ مفعل" if force_sub.get('enabled', False) else "❌ معطل"
    channels = force_sub.get('channels', [])
    
    channels_list = []
    for idx, channel in enumerate(channels, 1):
        channels_list.append(f"{idx}. {channel['name']} (<code>{channel['id']}</code>)")
    
    channels_text = "\n".join(channels_list) if channels_list else "لا توجد قنوات"
    
    keyboard = [
        [InlineKeyboardButton(f"الاشتراك الإجباري: {status}", callback_data="toggle_force_subscribe")],
        [InlineKeyboardButton("➕ إضافة قناة", callback_data="add_channel_info")],
        [InlineKeyboardButton("➖ حذف قناة", callback_data="remove_channel_info")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]
    ]
    
    text = f"📺 <b>القنوات الإجبارية</b>\n\n<b>الحالة:</b> {status}\n<b>القنوات:</b> {len(channels)}\n\n{channels_text}\n\n<i>عند التفعيل، يجب على المستخدمين الاشتراك في هذه القنوات لاستخدام البوت</i>"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer("جاري تصدير البيانات...")
    
    await query.message.reply_document(
        document=open(DATA_FILE, 'rb'),
        filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        caption="📤 نسخة احتياطية من بيانات البوت"
    )
    
    await owner_panel(update, context)

async def detailed_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
        
    query = update.callback_query
    await query.answer()
    
    total_warnings = sum(bot_data['warnings'].values())
    pending_count = sum(1 for msg in bot_data['messages'].values() if not msg.get('replied', False))
    
    text = f"""
📈 <b>تقرير مفصل</b>

👥 المستخدمين: {len(bot_data['users'])}
📨 الرسائل الكلية: {stats['total_messages']}
📩 رسائل معلقة: {pending_count}

🔨 الإداريين: {len(bot_data['admins'])}
🚫 المحظورين: {len(bot_data['banned'])}
⭐ VIP: {len(bot_data['vip'])}

⚠️ إجمالي التحذيرات: {total_warnings}

🔧 وضع الصيانة: {'✅ مفعل' if bot_data['maintenance'] else '❌ معطل'}
💬 الردود التلقائية: {'✅ مفعل' if bot_data['replies_enabled'] else '❌ معطل'}

📅 تاريخ التقرير: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="main_panel")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def handle_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
        
    query = update.callback_query
    await query.answer()
    
    user_id = query.data.split("_")[1]
    context.user_data['replying_to'] = user_id
    
    user_name = bot_data['users'].get(user_id, {}).get('name', 'مجهول')
    
    await query.message.reply_text(f"✍️ <b>الرد على: {user_name}</b>\n\nأرسل رسالتك الآن:\n\n(أرسل /cancel للإلغاء)", parse_mode=ParseMode.HTML)
    
    return REPLY_STATE

async def handle_reply_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
        
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    
    user_id = context.user_data.get('replying_to')
    if not user_id:
        return ConversationHandler.END
    
    message = update.message.text or ""
    
    try:
        await context.bot.send_message(
            chat_id=int(user_id),
            text=f"📬 <b>رد من {OWNER_NAME}:</b>\n\n{message}",
            parse_mode=ParseMode.HTML
        )
        await update.message.reply_text("✅ تم إرسال الرد بنجاح!")
        
        for msg_id, msg_info in bot_data['messages'].items():
            if str(msg_info['user_id']) == str(user_id):
                bot_data['messages'][msg_id]['replied'] = True
        save_data(bot_data)
        
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {str(e)}")
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return ConversationHandler.END
        
    await update.message.reply_text("❌ تم الإلغاء")
    context.user_data.clear()
    return ConversationHandler.END

async def start_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("➕ <b>إضافة إداري</b>\n\nأرسل معرف المستخدم (ID أو @username أو رابط):\n\n(أرسل /cancel للإلغاء)", parse_mode=ParseMode.HTML)
    return ADD_ADMIN_STATE

async def handle_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    
    user_identifier = update.message.text.strip()
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return ConversationHandler.END
    
    if any(str(admin['user_id']) == str(user_id) for admin in bot_data['admins']):
        await update.message.reply_text("⚠️ المستخدم إداري بالفعل!")
        context.user_data.clear()
        return ConversationHandler.END
    
    user_info = await fetch_user_info(user_id, context)
    user_name = user_info.get('name', f'User_{user_id[:8]}')
    username = user_info.get('username', 'لا يوجد')
    
    context.user_data['new_admin_id'] = user_id
    context.user_data['new_admin_username'] = username
    
    keyboard = [
        [InlineKeyboardButton("🔑 صلاحيات كاملة", callback_data="admin_perm_full")],
        [InlineKeyboardButton("⚙️ صلاحيات مخصصة", callback_data="admin_perm_custom")],
        [InlineKeyboardButton("📋 صلاحيات افتراضية", callback_data="admin_perm_default")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_perm_cancel")]
    ]
    
    await update.message.reply_text(
        f"✅ تم التعرف على: {user_name} (@{username})\n\n"
        f"🔧 <b>اختر نوع الصلاحيات:</b>\n\n"
        f"🔑 <b>صلاحيات كاملة:</b> جميع الصلاحيات (مثل المالك)\n"
        f"⚙️ <b>صلاحيات مخصصة:</b> اختيار الصلاحيات يدوياً\n"
        f"📋 <b>صلاحيات افتراضية:</b> صلاحيات محدودة (إدارة المستخدمين + VIP + تحذيرات + رد)",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    return ADMIN_PERMISSIONS_STATE

async def handle_admin_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    
    query = update.callback_query
    await query.answer()
    
    user_id = context.user_data.get('new_admin_id')
    username = context.user_data.get('new_admin_username', 'لا يوجد')
    
    if not user_id:
        await query.edit_message_text("❌ حدث خطأ! حاول مرة أخرى.")
        context.user_data.clear()
        return ConversationHandler.END
    
    user_info = bot_data['users'].get(user_id, {})
    user_name = user_info.get('name', 'مجهول')
    
    if query.data == "admin_perm_cancel":
        await query.edit_message_text("❌ تم إلغاء إضافة الإداري")
        context.user_data.clear()
        return ConversationHandler.END
    
    if query.data == "admin_perm_full":
        new_admin = {
            'user_id': user_id,
            'username': username,
            'full_access': True,
            'permissions': {key: True for key in PERMISSION_KEYS.keys()}
        }
        bot_data['admins'].append(new_admin)
        save_data(bot_data)
        await query.edit_message_text(f"✅ تم إضافة {user_name} كإداري بصلاحيات كاملة 🔑")
        context.user_data.clear()
        return ConversationHandler.END
    
    elif query.data == "admin_perm_default":
        new_admin = {
            'user_id': user_id,
            'username': username,
            'full_access': False,
            'permissions': {
                'manage_users': True,
                'manage_vip': True,
                'manage_warnings': True,
                'manage_admins': False,
                'broadcast': False,
                'view_stats': True,
                'auto_replies': False,
                'welcome_msg': False,
                'maintenance': False,
                'reply_messages': True
            }
        }
        bot_data['admins'].append(new_admin)
        save_data(bot_data)
        await query.edit_message_text(f"✅ تم إضافة {user_name} كإداري بصلاحيات افتراضية 📋")
        context.user_data.clear()
        return ConversationHandler.END
    
    elif query.data == "admin_perm_custom":
        context.user_data['custom_permissions'] = {key: False for key in PERMISSION_KEYS.keys()}
        
        keyboard = []
        for perm_key, perm_desc in PERMISSION_KEYS.items():
            status = "✅" if context.user_data['custom_permissions'][perm_key] else "❌"
            keyboard.append([InlineKeyboardButton(f"{status} {perm_desc}", callback_data=f"toggle_perm_{perm_key}")])
        
        keyboard.append([InlineKeyboardButton("💾 حفظ وإنهاء", callback_data="save_custom_perms")])
        keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="admin_perm_cancel")])
        
        await query.edit_message_text(
            f"⚙️ <b>تخصيص الصلاحيات لـ {user_name}</b>\n\n"
            f"انقر على أي صلاحية لتفعيلها/تعطيلها:\n"
            f"✅ = مفعّلة | ❌ = معطّلة",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return ADMIN_PERMISSIONS_STATE

async def handle_permission_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    
    query = update.callback_query
    await query.answer()
    
    user_id = context.user_data.get('new_admin_id') or context.user_data.get('editing_admin_id')
    if not user_id:
        await query.edit_message_text("❌ حدث خطأ! حاول مرة أخرى.")
        context.user_data.clear()
        return ConversationHandler.END
    
    user_info = bot_data['users'].get(user_id, {})
    user_name = user_info.get('name', 'مجهول')
    
    if query.data.startswith("toggle_perm_"):
        perm_key = query.data.replace("toggle_perm_", "")
        
        if 'custom_permissions' not in context.user_data:
            context.user_data['custom_permissions'] = {key: False for key in PERMISSION_KEYS.keys()}
        
        context.user_data['custom_permissions'][perm_key] = not context.user_data['custom_permissions'][perm_key]
        
        keyboard = []
        for pk, perm_desc in PERMISSION_KEYS.items():
            status = "✅" if context.user_data['custom_permissions'][pk] else "❌"
            keyboard.append([InlineKeyboardButton(f"{status} {perm_desc}", callback_data=f"toggle_perm_{pk}")])
        
        keyboard.append([InlineKeyboardButton("💾 حفظ وإنهاء", callback_data="save_custom_perms")])
        keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="admin_perm_cancel")])
        
        await query.edit_message_text(
            f"⚙️ <b>تخصيص الصلاحيات لـ {user_name}</b>\n\n"
            f"انقر على أي صلاحية لتفعيلها/تعطيلها:\n"
            f"✅ = مفعّلة | ❌ = معطّلة",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return ADMIN_PERMISSIONS_STATE
    
    elif query.data == "save_custom_perms":
        if context.user_data.get('editing_admin_id'):
            admin_id = context.user_data['editing_admin_id']
            for admin in bot_data['admins']:
                if str(admin['user_id']) == str(admin_id):
                    admin['permissions'] = context.user_data['custom_permissions']
                    admin['full_access'] = False
                    save_data(bot_data)
                    await query.edit_message_text(f"✅ تم تحديث صلاحيات {user_name} بنجاح!")
                    break
        else:
            username = context.user_data.get('new_admin_username', 'لا يوجد')
            new_admin = {
                'user_id': user_id,
                'username': username,
                'full_access': False,
                'permissions': context.user_data['custom_permissions']
            }
            bot_data['admins'].append(new_admin)
            save_data(bot_data)
            await query.edit_message_text(f"✅ تم إضافة {user_name} كإداري بصلاحيات مخصصة ⚙️")
        
        context.user_data.clear()
        return ConversationHandler.END

async def start_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("➖ <b>حذف إداري</b>\n\nأرسل معرف المستخدم (ID أو @username أو رابط):\n\n(أرسل /cancel للإلغاء)", parse_mode=ParseMode.HTML)
    return REMOVE_ADMIN_STATE

async def handle_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    
    user_identifier = update.message.text.strip()
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return ConversationHandler.END
    
    admin_found = False
    for admin in bot_data['admins']:
        if str(admin['user_id']) == str(user_id):
            bot_data['admins'].remove(admin)
            save_data(bot_data)
            user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
            await update.message.reply_text(f"✅ تم حذف {user_name} ({user_id}) من الإداريين")
            admin_found = True
            break
    
    if not admin_found:
        await update.message.reply_text("⚠️ المستخدم ليس إدارياً!")
    
    context.user_data.clear()
    return ConversationHandler.END

async def start_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🚫 <b>حظر مستخدم</b>\n\nأرسل معرف المستخدم (ID أو @username أو رابط):\n\n(أرسل /cancel للإلغاء)", parse_mode=ParseMode.HTML)
    return BAN_STATE

async def handle_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    
    user_identifier = update.message.text.strip()
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return ConversationHandler.END
    
    if int(user_id) == OWNER_ID:
        await update.message.reply_text("❌ لا يمكن حظر المالك!")
        return ConversationHandler.END
    
    if user_id not in bot_data['banned']:
        user_info = await fetch_user_info(user_id, context)
        bot_data['banned'].append(user_id)
        save_data(bot_data)
        user_name = user_info.get('name', f'User_{user_id[:8]}')
        await update.message.reply_text(f"✅ تم حظر المستخدم {user_name} ({user_id})")
    else:
        await update.message.reply_text("⚠️ المستخدم محظور بالفعل!")
    
    context.user_data.clear()
    return ConversationHandler.END

async def start_unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✅ <b>فك حظر مستخدم</b>\n\nأرسل معرف المستخدم (ID أو @username أو رابط):\n\n(أرسل /cancel للإلغاء)", parse_mode=ParseMode.HTML)
    return UNBAN_STATE

async def handle_unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    
    user_identifier = update.message.text.strip()
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return ConversationHandler.END
    
    if user_id in bot_data['banned']:
        user_info = await fetch_user_info(user_id, context)
        bot_data['banned'].remove(user_id)
        save_data(bot_data)
        user_name = user_info.get('name', f'User_{user_id[:8]}')
        await update.message.reply_text(f"✅ تم إلغاء حظر المستخدم {user_name} ({user_id})")
    else:
        await update.message.reply_text("⚠️ المستخدم غير محظور!")
    
    context.user_data.clear()
    return ConversationHandler.END

async def start_add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⭐ <b>إضافة VIP</b>\n\nأرسل معرف المستخدم (ID أو @username أو رابط):\n\n(أرسل /cancel للإلغاء)", parse_mode=ParseMode.HTML)
    return ADD_VIP_STATE

async def handle_add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    
    user_identifier = update.message.text.strip()
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return ConversationHandler.END
    
    if user_id not in bot_data['vip']:
        user_info = await fetch_user_info(user_id, context)
        bot_data['vip'].append(user_id)
        save_data(bot_data)
        user_name = user_info.get('name', f'User_{user_id[:8]}')
        await update.message.reply_text(f"✅ تم إضافة {user_name} ({user_id}) لـ VIP ⭐")
    else:
        await update.message.reply_text("⚠️ المستخدم VIP بالفعل!")
    
    context.user_data.clear()
    return ConversationHandler.END

async def start_remove_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("➖ <b>حذف VIP</b>\n\nأرسل معرف المستخدم (ID أو @username أو رابط):\n\n(أرسل /cancel للإلغاء)", parse_mode=ParseMode.HTML)
    return REMOVE_VIP_STATE

async def handle_remove_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    
    user_identifier = update.message.text.strip()
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return ConversationHandler.END
    
    if user_id in bot_data['vip']:
        user_info = await fetch_user_info(user_id, context)
        bot_data['vip'].remove(user_id)
        save_data(bot_data)
        user_name = user_info.get('name', f'User_{user_id[:8]}')
        await update.message.reply_text(f"✅ تم إزالة {user_name} ({user_id}) من VIP")
    else:
        await update.message.reply_text("⚠️ المستخدم ليس VIP!")
    
    context.user_data.clear()
    return ConversationHandler.END

async def start_add_warning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⚠️ <b>إضافة تحذير</b>\n\nأرسل معرف المستخدم (ID أو @username أو رابط):\n\n(أرسل /cancel للإلغاء)", parse_mode=ParseMode.HTML)
    return ADD_WARNING_STATE

async def handle_add_warning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    
    user_identifier = update.message.text.strip()
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return ConversationHandler.END
    
    user_info = await fetch_user_info(user_id, context)
    
    if user_id not in bot_data['warnings']:
        bot_data['warnings'][user_id] = 0
    
    bot_data['warnings'][user_id] += 1
    save_data(bot_data)
    
    user_name = user_info.get('name', f'User_{user_id[:8]}')
    warn_count = bot_data['warnings'][user_id]
    await update.message.reply_text(f"⚠️ تم إضافة تحذير للمستخدم {user_name} ({user_id})\nإجمالي التحذيرات: {warn_count}")
    
    try:
        await context.bot.send_message(
            chat_id=int(user_id),
            text=f"⚠️ <b>تحذير!</b>\n\nلقد تلقيت تحذيراً من الإدارة.\nإجمالي تحذيراتك: {warn_count}",
            parse_mode=ParseMode.HTML
        )
    except:
        pass
    
    context.user_data.clear()
    return ConversationHandler.END

async def start_remove_warning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("➖ <b>حذف تحذير</b>\n\nأرسل معرف المستخدم (ID أو @username أو رابط):\n\n(أرسل /cancel للإلغاء)", parse_mode=ParseMode.HTML)
    return REMOVE_WARNING_STATE

async def handle_remove_warning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    
    user_identifier = update.message.text.strip()
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return ConversationHandler.END
    
    if user_id in bot_data['warnings'] and bot_data['warnings'][user_id] > 0:
        bot_data['warnings'][user_id] -= 1
        if bot_data['warnings'][user_id] == 0:
            del bot_data['warnings'][user_id]
        save_data(bot_data)
        user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
        remaining = bot_data['warnings'].get(user_id, 0)
        await update.message.reply_text(f"✅ تم إزالة تحذير من {user_name} ({user_id})\nالتحذيرات المتبقية: {remaining}")
    else:
        await update.message.reply_text("⚠️ المستخدم ليس لديه تحذيرات!")
    
    context.user_data.clear()
    return ConversationHandler.END

async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📺 <b>إضافة قناة إجبارية</b>\n\n"
        "أرسل معرف القناة (@channelname أو ID):\n\n"
        "<i>ملاحظة: يجب أن يكون البوت مسؤولاً في القناة للتحقق من الاشتراك</i>\n\n"
        "(أرسل /cancel للإلغاء)",
        parse_mode=ParseMode.HTML
    )
    return ADD_CHANNEL_STATE

async def handle_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    
    channel_identifier = update.message.text.strip()
    
    try:
        chat = await context.bot.get_chat(channel_identifier)
        
        if chat.type not in ['channel', 'supergroup']:
            await update.message.reply_text("❌ هذا ليس قناة أو مجموعة!")
            return ConversationHandler.END
        
        channel_data = {
            'id': str(chat.id),
            'name': chat.title,
            'username': f"@{chat.username}" if chat.username else None
        }
        
        if 'force_subscribe' not in bot_data:
            bot_data['force_subscribe'] = {'enabled': False, 'channels': []}
        
        for existing in bot_data['force_subscribe']['channels']:
            if existing['id'] == channel_data['id']:
                await update.message.reply_text("⚠️ هذه القناة موجودة مسبقاً!")
                return ConversationHandler.END
        
        bot_data['force_subscribe']['channels'].append(channel_data)
        save_data(bot_data)
        
        channel_name = channel_data['username'] if channel_data['username'] else channel_data['name']
        await update.message.reply_text(
            f"✅ تم إضافة القناة بنجاح!\n\n"
            f"📺 {channel_name}\n"
            f"🆔 <code>{channel_data['id']}</code>\n\n"
            f"<i>تأكد من أن البوت مسؤول في القناة</i>",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}\n\nتأكد من صحة معرف القناة وأن البوت مسؤول فيها.")
    
    context.user_data.clear()
    return ConversationHandler.END

async def start_remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    
    channels = bot_data.get('force_subscribe', {}).get('channels', [])
    if not channels:
        await query.edit_message_text("⚠️ لا توجد قنوات لحذفها!", parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    
    channels_list = []
    for idx, channel in enumerate(channels, 1):
        channel_name = channel.get('username', channel['name'])
        channels_list.append(f"{idx}. {channel_name} (<code>{channel['id']}</code>)")
    
    text = "📺 <b>حذف قناة</b>\n\n" + "\n".join(channels_list) + "\n\n<b>أرسل رقم القناة لحذفها:</b>\n\n(أرسل /cancel للإلغاء)"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    return REMOVE_CHANNEL_STATE

async def handle_remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return ConversationHandler.END
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    
    try:
        channel_num = int(update.message.text.strip())
        channels = bot_data.get('force_subscribe', {}).get('channels', [])
        
        if channel_num < 1 or channel_num > len(channels):
            await update.message.reply_text("❌ رقم القناة غير صحيح!")
            return ConversationHandler.END
        
        removed_channel = channels.pop(channel_num - 1)
        save_data(bot_data)
        
        channel_name = removed_channel.get('username', removed_channel['name'])
        await update.message.reply_text(f"✅ تم حذف القناة: {channel_name}")
        
    except ValueError:
        await update.message.reply_text("❌ يرجى إرسال رقم القناة فقط!")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")
    
    context.user_data.clear()
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    user = update.effective_user
    user_id = user.id
    text = update.message.text or ""
    
    if bot_data['maintenance'] and user_id != OWNER_ID:
        await update.message.reply_text("🔧 البوت في وضع الصيانة حالياً")
        return
    
    if str(user_id) in bot_data['banned']:
        await update.message.reply_text("🚫 أنت محظور من استخدام البوت")
        return
    
    is_subscribed, not_subscribed_channels = await check_user_subscribed(user_id, context)
    if not is_subscribed and not_subscribed_channels:
        await send_force_subscribe_message(update, not_subscribed_channels)
        return
    
    if user_id != OWNER_ID:
        if text == "ℹ️ معلومات" or text == "معلومات" or text == "معلومات ℹ️":
            user_info = bot_data['users'].get(str(user_id), {})
            msg_count = user_info.get('message_count', 0)
            join_date = user_info.get('join_date', 'غير معروف')[:10]
            is_vip = "⭐ نعم" if str(user_id) in bot_data['vip'] else "❌ لا"
            
            info_text = f"""
ℹ️ <b>معلوماتك:</b>

👤 الاسم: {user.full_name}
🆔 ID: <code>{user_id}</code>
📅 انضممت: {join_date}

💬 رسائلك: {msg_count}
⭐ VIP: {is_vip}

📢 القناة: {CHANNEL_LINK}
            """
            await update.message.reply_text(info_text, parse_mode=ParseMode.HTML)
            return
        
        elif text == "📨 إرسال رسالة" or text == "إرسال رسالة":
            await update.message.reply_text("✍️ أرسل رسالتك الآن وسيتم إيصالها للمالك:")
            return
        msg_id = str(datetime.now().timestamp())
        bot_data['messages'][msg_id] = {
            'user_id': user_id,
            'user_name': user.full_name,
            'username': user.username or 'لا يوجد',
            'message': text,
            'date': str(datetime.now()),
            'replied': False
        }
        
        if str(user_id) in bot_data['users']:
            bot_data['users'][str(user_id)]['message_count'] += 1
        save_data(bot_data)
        
        stats['total_messages'] += 1
        stats['messages_today'] += 1
        save_stats(stats)
        
        owner_msg = f"""
📨 <b>رسالة جديدة!</b>

من: {user.full_name}
ID: <code>{user_id}</code>
Username: @{user.username or 'لا يوجد'}

━━━━━━━━━━━━━━━
💬 الرسالة:
{text}
        """
        
        keyboard = [
            [InlineKeyboardButton("💬 رد", callback_data=f"reply_{user_id}")],
            [InlineKeyboardButton("🚫 حظر", callback_data=f"ban_{user_id}"),
             InlineKeyboardButton("⭐ VIP", callback_data=f"vip_{user_id}")]
        ]
        
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=owner_msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            await update.message.reply_text("✅ تم إرسال رسالتك للمالك بنجاح!")
        except Exception as e:
            logger.error(f"خطأ في إرسال الرسالة للمالك: {e}")
            await update.message.reply_text("✅ تم حفظ رسالتك وسيتم إرسالها للمالك!")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query or not update.effective_user:
        return
        
    query = update.callback_query
    user_id = update.effective_user.id
    
    if is_banned(user_id):
        await query.answer("🚫 أنت محظور من استخدام البوت!", show_alert=True)
        return
    
    is_subscribed, not_subscribed_channels = await check_user_subscribed(user_id, context)
    if not is_subscribed and not_subscribed_channels:
        await query.answer("⚠️ يجب الاشتراك في القنوات الإجبارية أولاً!", show_alert=True)
        return
    
    await query.answer()
    
    data = query.data
    
    if user_id != OWNER_ID and str(user_id) not in bot_data['admins']:
        await query.answer("⛔ ليس لديك صلاحية!", show_alert=True)
        return
    
    if data == "main_panel":
        await owner_panel(update, context)
    elif data == "stats":
        await show_stats(update, context)
    elif data == "users_list":
        await users_list(update, context)
    elif data == "full_users_list":
        await full_users_list(update, context)
    elif data == "new_users":
        await new_users(update, context)
    elif data == "active_users":
        await active_users(update, context)
    elif data == "inactive_users":
        await inactive_users(update, context)
    elif data == "broadcast":
        await broadcast_menu(update, context)
    elif data == "pending_msgs":
        await pending_msgs(update, context)
    elif data.startswith("view_msg_"):
        await view_message(update, context)
    elif data == "admins_panel":
        await admins_panel(update, context)
    elif data == "edit_admin_permissions":
        if user_id != OWNER_ID:
            await query.answer("⛔ هذه الميزة للمالك فقط!", show_alert=True)
            return
        
        keyboard = []
        for admin in bot_data['admins']:
            admin_id = admin['user_id']
            user_info = bot_data['users'].get(admin_id, {})
            name = user_info.get('name', 'مجهول')
            access_badge = " 🔑" if admin.get('full_access') else ""
            keyboard.append([InlineKeyboardButton(f"{name}{access_badge}", callback_data=f"edit_perms_{admin_id}")])
        
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admins_panel")])
        
        await query.edit_message_text(
            "⚙️ <b>اختر الإداري لتعديل صلاحياته:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    elif data.startswith("edit_perms_"):
        if user_id != OWNER_ID:
            await query.answer("⛔ هذه الميزة للمالك فقط!", show_alert=True)
            return
        
        admin_id = data.replace("edit_perms_", "")
        admin_record = None
        for admin in bot_data['admins']:
            if str(admin['user_id']) == str(admin_id):
                admin_record = admin
                break
        
        if not admin_record:
            await query.answer("❌ لم يتم العثور على الإداري!", show_alert=True)
            return
        
        context.user_data['editing_admin_id'] = admin_id
        context.user_data['custom_permissions'] = admin_record.get('permissions', {key: False for key in PERMISSION_KEYS.keys()})
        
        user_info = bot_data['users'].get(admin_id, {})
        user_name = user_info.get('name', 'مجهول')
        
        keyboard = []
        for perm_key, perm_desc in PERMISSION_KEYS.items():
            status = "✅" if context.user_data['custom_permissions'].get(perm_key, False) else "❌"
            keyboard.append([InlineKeyboardButton(f"{status} {perm_desc}", callback_data=f"toggle_perm_{perm_key}")])
        
        keyboard.append([InlineKeyboardButton("🔑 صلاحيات كاملة", callback_data="set_full_access")])
        keyboard.append([InlineKeyboardButton("💾 حفظ", callback_data="save_custom_perms")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="edit_admin_permissions")])
        
        await query.edit_message_text(
            f"⚙️ <b>تعديل صلاحيات: {user_name}</b>\n\n"
            f"انقر على أي صلاحية لتفعيلها/تعطيلها:\n"
            f"✅ = مفعّلة | ❌ = معطّلة",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    elif data == "set_full_access":
        if user_id != OWNER_ID:
            await query.answer("⛔ هذه الميزة للمالك فقط!", show_alert=True)
            return
        
        admin_id = context.user_data.get('editing_admin_id')
        if not admin_id:
            await query.answer("❌ حدث خطأ!", show_alert=True)
            return
        
        for admin in bot_data['admins']:
            if str(admin['user_id']) == str(admin_id):
                admin['full_access'] = True
                admin['permissions'] = {key: True for key in PERMISSION_KEYS.keys()}
                save_data(bot_data)
                
                user_info = bot_data['users'].get(admin_id, {})
                user_name = user_info.get('name', 'مجهول')
                
                await query.edit_message_text(f"✅ تم منح {user_name} صلاحيات كاملة 🔑")
                context.user_data.clear()
                break
    elif data == "banned_list":
        await banned_list(update, context)
    elif data == "vip_panel":
        await vip_panel(update, context)
    elif data == "settings":
        await settings_panel(update, context)
    elif data == "maintenance":
        await maintenance_panel(update, context)
    elif data == "welcome_msg":
        await welcome_msg_panel(update, context)
    elif data == "warnings_panel":
        await warnings_panel(update, context)
    elif data == "force_subscribe_panel":
        await force_subscribe_panel(update, context)
    elif data == "toggle_force_subscribe":
        if 'force_subscribe' not in bot_data:
            bot_data['force_subscribe'] = {'enabled': False, 'channels': []}
        bot_data['force_subscribe']['enabled'] = not bot_data['force_subscribe'].get('enabled', False)
        save_data(bot_data)
        await force_subscribe_panel(update, context)
    elif data == "export_data":
        await export_data(update, context)
    elif data == "detailed_report":
        await detailed_report(update, context)
    elif data == "toggle_maintenance":
        bot_data['maintenance'] = not bot_data['maintenance']
        save_data(bot_data)
        await maintenance_panel(update, context)
    elif data == "toggle_welcome":
        bot_data['welcome_enabled'] = not bot_data.get('welcome_enabled', True)
        save_data(bot_data)
        await welcome_msg_panel(update, context)
    elif data == "reset_welcome":
        bot_data['welcome_msg'] = 'مرحباً بك! 👋\nيمكنك الآن إرسال رسالتك للمالك'
        save_data(bot_data)
        await query.answer("✅ تم استعادة رسالة الترحيب الافتراضية!", show_alert=True)
        await welcome_msg_panel(update, context)
    elif data == "toggle_replies":
        bot_data['replies_enabled'] = not bot_data['replies_enabled']
        save_data(bot_data)
        await settings_panel(update, context)
    elif data == "reset_confirm":
        keyboard = [
            [InlineKeyboardButton("✅ نعم، امسح كل شيء", callback_data="reset_yes")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="settings")]
        ]
        text = "⚠️ <b>تحذير!</b>\n\nهل أنت متأكد من إعادة تعيين جميع البيانات؟\nسيتم حذف كل شيء!"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    elif data == "reset_yes":
        bot_data['users'] = {}
        bot_data['admins'] = []
        bot_data['banned'] = []
        bot_data['vip'] = []
        bot_data['messages'] = {}
        bot_data['warnings'] = {}
        save_data(bot_data)
        stats['total_messages'] = 0
        stats['total_users'] = 0
        stats['messages_today'] = 0
        save_stats(stats)
        await query.answer("✅ تم إعادة تعيين البيانات!", show_alert=True)
        await owner_panel(update, context)
    elif data == "edit_welcome":
        await query.answer("استخدم: /setwelcome <الرسالة>", show_alert=True)
    elif data.startswith("ban_"):
        user_id = data.split("_")[1]
        if user_id not in bot_data['banned']:
            bot_data['banned'].append(user_id)
            save_data(bot_data)
        await query.answer("✅ تم حظر المستخدم!", show_alert=True)
    elif data.startswith("vip_"):
        user_id = data.split("_")[1]
        if user_id not in bot_data['vip']:
            bot_data['vip'].append(user_id)
            save_data(bot_data)
        await query.answer("✅ تم إضافة المستخدم لـ VIP!", show_alert=True)

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if update.effective_user.id != OWNER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("📢 الاستخدام: /broadcast <الرسالة>")
        return
    
    message = ' '.join(context.args)
    success = 0
    failed = 0
    
    for user_id in bot_data['users'].keys():
        try:
            await context.bot.send_message(chat_id=int(user_id), text=message)
            success += 1
        except:
            failed += 1
    
    await update.message.reply_text(f"✅ تم الإرسال لـ {success} مستخدم\n❌ فشل: {failed}")

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ليس لديك صلاحية!")
        return
    
    if not context.args:
        await update.message.reply_text("🚫 الاستخدام: /ban <user_id أو @username أو رابط>")
        return
    
    user_identifier = context.args[0]
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return
    
    if int(user_id) == OWNER_ID:
        await update.message.reply_text("❌ لا يمكن حظر المالك!")
        return
    
    if user_id not in bot_data['banned']:
        bot_data['banned'].append(user_id)
        save_data(bot_data)
        user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
        await update.message.reply_text(f"✅ تم حظر المستخدم {user_name} ({user_id})")
    else:
        await update.message.reply_text("⚠️ المستخدم محظور بالفعل!")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ليس لديك صلاحية!")
        return
    
    if not context.args:
        await update.message.reply_text("✅ الاستخدام: /unban <user_id أو @username أو رابط>")
        return
    
    user_identifier = context.args[0]
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return
    
    if user_id in bot_data['banned']:
        bot_data['banned'].remove(user_id)
        save_data(bot_data)
        user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
        await update.message.reply_text(f"✅ تم إلغاء حظر المستخدم {user_name} ({user_id})")
    else:
        await update.message.reply_text("⚠️ المستخدم غير محظور!")

async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط!")
        return
    
    if not context.args:
        await update.message.reply_text("🔨 الاستخدام: /addadmin <user_id أو @username أو رابط>")
        return
    
    user_identifier = context.args[0]
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return
    
    if user_id not in bot_data['admins']:
        bot_data['admins'].append(user_id)
        save_data(bot_data)
        user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
        await update.message.reply_text(f"✅ تم إضافة {user_name} ({user_id}) كإداري")
    else:
        await update.message.reply_text("⚠️ المستخدم إداري بالفعل!")

async def removeadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ هذا الأمر للمالك فقط!")
        return
    
    if not context.args:
        await update.message.reply_text("➖ الاستخدام: /removeadmin <user_id أو @username أو رابط>")
        return
    
    user_identifier = context.args[0]
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return
    
    if user_id in bot_data['admins']:
        bot_data['admins'].remove(user_id)
        save_data(bot_data)
        user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
        await update.message.reply_text(f"✅ تم حذف {user_name} ({user_id}) من الإداريين")
    else:
        await update.message.reply_text("⚠️ المستخدم ليس إدارياً!")

async def addvip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ليس لديك صلاحية!")
        return
    
    if not context.args:
        await update.message.reply_text("⭐ الاستخدام: /addvip <user_id أو @username أو رابط>")
        return
    
    user_identifier = context.args[0]
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return
    
    if user_id not in bot_data['vip']:
        bot_data['vip'].append(user_id)
        save_data(bot_data)
        user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
        await update.message.reply_text(f"✅ تم إضافة {user_name} ({user_id}) لـ VIP ⭐")
    else:
        await update.message.reply_text("⚠️ المستخدم VIP بالفعل!")

async def removevip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ليس لديك صلاحية!")
        return
    
    if not context.args:
        await update.message.reply_text("➖ الاستخدام: /removevip <user_id أو @username أو رابط>")
        return
    
    user_identifier = context.args[0]
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return
    
    if user_id in bot_data['vip']:
        bot_data['vip'].remove(user_id)
        save_data(bot_data)
        user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
        await update.message.reply_text(f"✅ تم إزالة {user_name} ({user_id}) من VIP")
    else:
        await update.message.reply_text("⚠️ المستخدم ليس VIP!")

async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ليس لديك صلاحية!")
        return
    
    if not context.args:
        await update.message.reply_text("⚠️ الاستخدام: /warn <user_id أو @username أو رابط>")
        return
    
    user_identifier = context.args[0]
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return
    
    if user_id not in bot_data['warnings']:
        bot_data['warnings'][user_id] = 0
    
    bot_data['warnings'][user_id] += 1
    save_data(bot_data)
    
    user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
    warn_count = bot_data['warnings'][user_id]
    await update.message.reply_text(f"⚠️ تم إضافة تحذير للمستخدم {user_name} ({user_id})\nإجمالي التحذيرات: {warn_count}")
    
    try:
        await context.bot.send_message(
            chat_id=int(user_id),
            text=f"⚠️ <b>تحذير!</b>\n\nلقد تلقيت تحذيراً من الإدارة.\nإجمالي تحذيراتك: {warn_count}",
            parse_mode=ParseMode.HTML
        )
    except:
        pass

async def unwarn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ليس لديك صلاحية!")
        return
    
    if not context.args:
        await update.message.reply_text("✅ الاستخدام: /unwarn <user_id أو @username أو رابط>")
        return
    
    user_identifier = context.args[0]
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return
    
    if user_id in bot_data['warnings'] and bot_data['warnings'][user_id] > 0:
        bot_data['warnings'][user_id] -= 1
        if bot_data['warnings'][user_id] == 0:
            del bot_data['warnings'][user_id]
        save_data(bot_data)
        user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
        remaining = bot_data['warnings'].get(user_id, 0)
        await update.message.reply_text(f"✅ تم إزالة تحذير من {user_name} ({user_id})\nالتحذيرات المتبقية: {remaining}")
    else:
        await update.message.reply_text("⚠️ المستخدم ليس لديه تحذيرات!")

async def resetwarns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ليس لديك صلاحية!")
        return
    
    if not context.args:
        await update.message.reply_text("🔄 الاستخدام: /resetwarns <user_id أو @username أو رابط>")
        return
    
    user_identifier = context.args[0]
    user_id = await resolve_user_identifier(user_identifier, context)
    
    if not user_id:
        await update.message.reply_text("❌ لم أتمكن من إيجاد المستخدم!")
        return
    
    if user_id in bot_data['warnings']:
        del bot_data['warnings'][user_id]
        save_data(bot_data)
        user_name = bot_data['users'].get(user_id, {}).get('name', user_id)
        await update.message.reply_text(f"✅ تم إعادة تعيين تحذيرات {user_name} ({user_id})")
    else:
        await update.message.reply_text("⚠️ المستخدم ليس لديه تحذيرات!")

async def setwelcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if update.effective_user.id != OWNER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("📝 الاستخدام: /setwelcome <الرسالة>")
        return
    
    message = ' '.join(context.args)
    bot_data['welcome_msg'] = message
    save_data(bot_data)
    
    await update.message.reply_text("✅ تم تحديث رسالة الترحيب!")

async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if update.effective_user.id != OWNER_ID:
        return
    
    await update.message.reply_document(
        document=open(DATA_FILE, 'rb'),
        filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        caption="📤 نسخة احتياطية من بيانات البوت"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
        
    if update.effective_user.id != OWNER_ID:
        return
    
    help_text = """
📚 <b>قائمة الأوامر المتاحة:</b>

1️⃣ <b>إدارة عامة:</b>
/start - لوحة التحكم
/help - قائمة الأوامر

2️⃣ <b>إدارة المستخدمين:</b>
/ban <معرف> - حظر مستخدم
/unban <معرف> - إلغاء حظر
/broadcast <رسالة> - إذاعة

3️⃣ <b>إدارة الإداريين:</b> (للمالك فقط)
/addadmin <معرف> - إضافة إداري
/removeadmin <معرف> - حذف إداري

4️⃣ <b>إدارة VIP:</b>
/addvip <معرف> - إضافة VIP
/removevip <معرف> - إزالة VIP

5️⃣ <b>إدارة التحذيرات:</b>
/warn <معرف> - إضافة تحذير
/unwarn <معرف> - إزالة تحذير
/resetwarns <معرف> - مسح كل التحذيرات

6️⃣ <b>إدارة البيانات:</b> (للمالك فقط)
/backup - نسخ احتياطي
/setwelcome <رسالة> - تغيير الترحيب

<b>ملاحظة:</b> <معرف> يمكن أن يكون:
• ID مثل: 123456789
• Username مثل: @username
• رابط مثل: https://t.me/username
    """
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    reply_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_reply_start, pattern=r'^reply_\d+$')],
        states={
            REPLY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_message)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    broadcast_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(broadcast_all, pattern='^broadcast_all$'),
            CallbackQueryHandler(broadcast_vip, pattern='^broadcast_vip$')
        ],
        states={
            BROADCAST_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    add_admin_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_admin, pattern='^add_admin_info$')],
        states={
            ADD_ADMIN_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_admin)],
            ADMIN_PERMISSIONS_STATE: [
                CallbackQueryHandler(handle_admin_permissions, pattern='^admin_perm_(full|default|custom|cancel)$'),
                CallbackQueryHandler(handle_permission_toggle, pattern='^(toggle_perm_|save_custom_perms)')
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    remove_admin_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_remove_admin, pattern='^remove_admin_info$')],
        states={
            REMOVE_ADMIN_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_admin)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    ban_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_ban_user, pattern='^ban_user_info$')],
        states={
            BAN_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ban_user)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    unban_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_unban_user, pattern='^unban_user_info$')],
        states={
            UNBAN_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unban_user)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    add_vip_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_vip, pattern='^add_vip_info$')],
        states={
            ADD_VIP_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_vip)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    remove_vip_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_remove_vip, pattern='^remove_vip_info$')],
        states={
            REMOVE_VIP_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_vip)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    add_warning_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_warning, pattern='^add_warning_info$')],
        states={
            ADD_WARNING_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_warning)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    remove_warning_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_remove_warning, pattern='^remove_warning_info$')],
        states={
            REMOVE_WARNING_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_warning)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    add_channel_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_channel, pattern='^add_channel_info$')],
        states={
            ADD_CHANNEL_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_channel)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    remove_channel_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_remove_channel, pattern='^remove_channel_info$')],
        states={
            REMOVE_CHANNEL_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_channel)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("broadcast", broadcast_cmd))
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("unban", unban_cmd))
    application.add_handler(CommandHandler("addadmin", addadmin_cmd))
    application.add_handler(CommandHandler("removeadmin", removeadmin_cmd))
    application.add_handler(CommandHandler("addvip", addvip_cmd))
    application.add_handler(CommandHandler("removevip", removevip_cmd))
    application.add_handler(CommandHandler("warn", warn_cmd))
    application.add_handler(CommandHandler("unwarn", unwarn_cmd))
    application.add_handler(CommandHandler("resetwarns", resetwarns_cmd))
    application.add_handler(CommandHandler("setwelcome", setwelcome_cmd))
    application.add_handler(CommandHandler("backup", backup_cmd))
    
    application.add_handler(reply_handler)
    application.add_handler(broadcast_handler)
    application.add_handler(add_admin_handler)
    application.add_handler(remove_admin_handler)
    application.add_handler(ban_handler)
    application.add_handler(unban_handler)
    application.add_handler(add_vip_handler)
    application.add_handler(remove_vip_handler)
    application.add_handler(add_warning_handler)
    application.add_handler(remove_warning_handler)
    application.add_handler(add_channel_handler)
    application.add_handler(remove_channel_handler)
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 البوت يعمل الآن...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
