#!/usr/bin/env python3
# news_forwarder_bot_v4.py
# Requires:
# pip install python-telegram-bot==13.15 feedparser apscheduler python-dotenv requests

import os
import json
import sqlite3
import logging
import traceback
import base64
import requests
from datetime import datetime, timedelta
from hashlib import sha256
from functools import wraps

import feedparser
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot, Update, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, ChatMemberHandler, MessageHandler, Filters

from dotenv import load_dotenv
load_dotenv()

# ---------------------------
# Config (ضع القيم في .env)
# ---------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
OWNER_ID = int(os.getenv("OWNER_ID", "7124431342"))
DB_PATH = os.getenv("DB_PATH", "news_forwarder_bot_v4.db")
LOG_FILE = os.getenv("LOG_FILE", "news_forwarder_bot_v4.log")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))

# Default sources (editable)
DEFAULT_SOURCES = [
    {"url": "https://www.aljazeera.net/xml/rss/all.xml", "name": "Al Jazeera"},
    {"url": "https://www.wafa.ps/rss.aspx", "name": "WAFA"},
    {"url": "https://www.maannews.net/rss/ar/all.xml", "name": "Maan"},
    {"url": "https://arabic.rt.com/rss/", "name": "RT Arabic"},
    {"url": "https://www.france24.com/ar/rss", "name": "France24 Arabic"}
]

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

def push_log(level, message):
    if level == "INFO":
        logger.info(message)
    else:
        logger.error(message)
    try:
        cur = db.cursor()
        cur.execute("INSERT INTO events (ts, level, message) VALUES (?, ?, ?)",
                    (datetime.utcnow().isoformat(), level, message[:2000]))
        db.commit()
    except Exception as e:
        logger.error("Failed to write event to DB: %s", e)

# ---------------------------
# DB init
# ---------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    # channels
    c.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        chat_id TEXT PRIMARY KEY,
        title TEXT,
        added_by INTEGER,
        added_at TEXT,
        blocked INTEGER DEFAULT 0
    )""")
    # admins
    c.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        permissions TEXT,
        added_at TEXT
    )""")
    # sources
    c.execute("""
    CREATE TABLE IF NOT EXISTS sources (
        url TEXT PRIMARY KEY,
        name TEXT,
        enabled INTEGER DEFAULT 1,
        added_at TEXT
    )""")
    # sent links
    c.execute("""
    CREATE TABLE IF NOT EXISTS sent_links (
        link_hash TEXT PRIMARY KEY,
        url TEXT,
        posted_at TEXT
    )""")
    # bans (perm or temp)
    c.execute("""
    CREATE TABLE IF NOT EXISTS bans (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        reason TEXT,
        expires_at TEXT,
        banned_at TEXT
    )""")
    # events logs
    c.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        level TEXT,
        message TEXT
    )""")
    # settings
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.commit()
    return conn

db = init_db()

# ---------------------------
# Settings helpers
# ---------------------------
def set_setting(k, v):
    cur = db.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, json.dumps(v)))
    db.commit()

def get_setting(k, default=None):
    cur = db.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (k,))
    r = cur.fetchone()
    if not r:
        return default
    return json.loads(r[0])

# default settings
if get_setting("global_enabled") is None:
    set_setting("global_enabled", True)
if get_setting("auto_add_channels") is None:
    set_setting("auto_add_channels", True)
if get_setting("download_media") is None:
    set_setting("download_media", True)
if get_setting("notify_owner") is None:
    set_setting("notify_owner", True)
if get_setting("maintenance_mode") is None:
    set_setting("maintenance_mode", {"on": False, "reason": "", "until": None})

# ---------------------------
# Utility functions
# ---------------------------
def hash_link(link):
    return sha256(link.encode()).hexdigest()

def link_was_sent(link):
    h = hash_link(link)
    cur = db.cursor()
    cur.execute("SELECT 1 FROM sent_links WHERE link_hash = ?", (h,))
    return cur.fetchone() is not None

def add_sent_link(link):
    h = hash_link(link)
    cur = db.cursor()
    cur.execute("INSERT OR IGNORE INTO sent_links (link_hash, url, posted_at) VALUES (?, ?, ?)",
                (h, link, datetime.utcnow().isoformat()))
    db.commit()

def count_sent_links():
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM sent_links")
    return cur.fetchone()[0]

# ---------------------------
# DB actions for channels/sources/admins/bans
# ---------------------------
def add_channel_db(chat_id, title, added_by):
    cur = db.cursor()
    cur.execute("INSERT OR REPLACE INTO channels (chat_id, title, added_by, added_at) VALUES (?, ?, ?, ?)",
                (str(chat_id), title or "", added_by, datetime.utcnow().isoformat()))
    db.commit()
    push_log("INFO", f"Channel added: {chat_id} by {added_by}")

def remove_channel_db(chat_id):
    cur = db.cursor()
    cur.execute("DELETE FROM channels WHERE chat_id = ?", (str(chat_id),))
    db.commit()
    push_log("INFO", f"Channel removed: {chat_id}")

def list_channels_db():
    cur = db.cursor()
    cur.execute("SELECT chat_id, title, blocked, added_by, added_at FROM channels")
    return cur.fetchall()

def add_source(url, name=None):
    cur = db.cursor()
    cur.execute("INSERT OR REPLACE INTO sources (url, name, enabled, added_at) VALUES (?, ?, ?, ?)",
                (url, name or url, 1, datetime.utcnow().isoformat()))
    db.commit()
    push_log("INFO", f"Source added: {url}")

def remove_source(url):
    cur = db.cursor()
    cur.execute("DELETE FROM sources WHERE url = ?", (url,))
    db.commit()
    push_log("INFO", f"Source removed: {url}")

def get_enabled_sources():
    cur = db.cursor()
    cur.execute("SELECT url, name FROM sources WHERE enabled = 1")
    return cur.fetchall()

def set_source_enabled(url, enabled):
    cur = db.cursor()
    cur.execute("UPDATE sources SET enabled = ? WHERE url = ?", (1 if enabled else 0, url))
    db.commit()
    push_log("INFO", f"Source {'enabled' if enabled else 'disabled'}: {url}")

def add_admin_db(user_id, username, perms=None):
    if perms is None:
        perms = ["*"]
    cur = db.cursor()
    cur.execute("INSERT OR REPLACE INTO admins (user_id, username, permissions, added_at) VALUES (?, ?, ?, ?)",
                (user_id, username or "", json.dumps(perms), datetime.utcnow().isoformat()))
    db.commit()
    push_log("INFO", f"Admin added: {user_id} ({username}) perms={perms}")

def remove_admin_db(user_id):
    cur = db.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    db.commit()
    push_log("INFO", f"Admin removed: {user_id}")

def list_admins_db():
    cur = db.cursor()
    cur.execute("SELECT user_id, username, permissions, added_at FROM admins")
    return cur.fetchall()

def ban_user_db(user_id, username="", reason="", expires_at=None):
    cur = db.cursor()
    cur.execute("INSERT OR REPLACE INTO bans (user_id, username, reason, expires_at, banned_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, username or "", reason or "", expires_at, datetime.utcnow().isoformat()))
    db.commit()
    push_log("INFO", f"User banned: {user_id} username={username} reason={reason} expires_at={expires_at}")

def unban_user_db(user_id):
    cur = db.cursor()
    cur.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
    db.commit()
    push_log("INFO", f"User unbanned: {user_id}")

def is_banned(user_id):
    cur = db.cursor()
    cur.execute("SELECT expires_at FROM bans WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    if not r:
        return False
    expires = r[0]
    if expires is None:
        return True
    try:
        expires_dt = datetime.fromisoformat(expires)
        if datetime.utcnow() >= expires_dt:
            # expired -> remove
            unban_user_db(user_id)
            return False
        return True
    except Exception:
        return True

# ---------------------------
# Ensure owner exists as admin
# ---------------------------
add_admin_db(OWNER_ID, "owner", ["*"])

# ensure default sources exist
for s in DEFAULT_SOURCES:
    add_source(s["url"], s["name"])

# ---------------------------
# Bot init
# ---------------------------
bot = Bot(token=BOT_TOKEN)
updater = Updater(token=BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

def owner_notify(text):
    if get_setting("notify_owner", True):
        try:
            bot.send_message(chat_id=OWNER_ID, text=text, parse_mode=ParseMode.HTML)
        except Exception as e:
            push_log("ERROR", f"Owner notify failed: {e}")

# ---------------------------
# Permission system (advanced)
# ---------------------------
PERMISSIONS_LIST = {
    "add_channel": "إضافة قناة/جروب",
    "remove_channel": "حذف قناة/جروب",
    "list_channels": "عرض القنوات",
    "add_source": "إضافة مصدر RSS/API",
    "remove_source": "حذف مصدر",
    "toggle_source": "تفعيل/تعطيل مصدر",
    "toggle_all_sources": "تعطيل/تفعيل كل المصادر دفعة واحدة",
    "post_manual": "نشر يدوي (send_manual)",
    "block_channel": "حظر قناة من النشر",
    "unblock_channel": "فك حظر قناة",
    "add_admin": "إضافة أدمن",
    "remove_admin": "حذف أدمن",
    "list_admins": "عرض الأدمنز",
    "grant_perm": "منح صلاحية لأدمن",
    "revoke_perm": "سحب صلاحية من أدمن",
    "ban_user": "حظر مستخدم",
    "unban_user": "رفع حظر مستخدم",
    "view_logs": "عرض السجلات (Logs)",
    "clean_links": "تنظيف sent_links",
    "toggle_global": "تشغيل/إيقاف البوت العام",
    "toggle_maintenance": "تشغيل/إيقاف وضع الصيانة",
    "export_logs": "تصدير السجلات",
    "manage_settings": "تعديل الإعدادات العامة",
    "manage_media": "تفعيل/تعطيل تنزيل الوسائط",
    "manage_notifications": "تفعيل/تعطيل إشعارات المالك"
}

PRESET_ROLES = {
    "owner": list(PERMISSIONS_LIST.keys()),
    "manager": ["add_channel","remove_channel","add_source","remove_source","toggle_source","post_manual","list_channels","list_admins","view_logs","export_logs"],
    "moderator": ["block_channel","unblock_channel","ban_user","unban_user","post_manual"],
    "editor": ["add_source","toggle_source","post_manual","manage_media"],
    "viewer": ["list_channels","list_admins","view_logs"]
}

def get_admin_permissions(user_id):
    cur = db.cursor()
    cur.execute("SELECT permissions FROM admins WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    if not r:
        return []
    try:
        perms = json.loads(r[0])
        if perms == ["*"]:
            return list(PERMISSIONS_LIST.keys())
        return perms
    except Exception:
        return []

def set_admin_permissions(user_id, perms_list):
    cur = db.cursor()
    cur.execute("UPDATE admins SET permissions = ? WHERE user_id = ?", (json.dumps(perms_list), user_id))
    db.commit()
    push_log("INFO", f"Permissions set for admin {user_id}: {perms_list}")
    owner_notify(f"صلاحيات المُستخدم {user_id} تعدَّلت: {perms_list}")

def add_permission_to_admin(user_id, perm):
    perms = get_admin_permissions(user_id)
    if perm not in PERMISSIONS_LIST:
        return False, "Permission unknown"
    if "*" in perms:
        return True, "Already has all perms"
    if perm in perms:
        return True, "Already has permission"
    perms.append(perm)
    set_admin_permissions(user_id, perms)
    return True, "Permission granted"

def remove_permission_from_admin(user_id, perm):
    perms = get_admin_permissions(user_id)
    if "*" in perms:
        perms = list(PERMISSIONS_LIST.keys())
    if perm not in perms:
        return False, "Admin does not have this permission"
    perms.remove(perm)
    set_admin_permissions(user_id, perms)
    return True, "Permission revoked"

def set_preset_for_admin(user_id, preset_name):
    if preset_name not in PRESET_ROLES:
        return False, "Preset not found"
    perms = PRESET_ROLES[preset_name]
    set_admin_permissions(user_id, perms)
    return True, f"Preset {preset_name} applied"

def require_permission(permission):
    def decorator(func):
        @wraps(func)
        def wrapper(update: Update, context: CallbackContext, *a, **kw):
            user = update.effective_user
            # owner bypass
            if user and user.id == OWNER_ID:
                return func(update, context, *a, **kw)
            # check admin record
            cur = db.cursor()
            cur.execute("SELECT permissions FROM admins WHERE user_id = ?", (user.id,))
            r = cur.fetchone()
            if not r:
                try:
                    if update.effective_message:
                        update.effective_message.reply_text("ما عندك صلاحية لتنفيذ هذا الإجراء.")
                except:
                    pass
                return
            try:
                perms = json.loads(r[0])
            except:
                perms = []
            if "*" in perms or permission in perms:
                return func(update, context, *a, **kw)
            try:
                if update.effective_message:
                    update.effective_message.reply_text("محجوز: ما عندك صلاحية كافية لتنفيذ هذا الإجراء.")
            except:
                pass
            push_log("INFO", f"Unauthorized attempt by {user.id} to run {permission}")
            return
        return wrapper
    return decorator

# ---------------------------
# Inline admin panel (main)
# ---------------------------
def encode_id(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode()

def decode_id(s: str) -> str:
    return base64.urlsafe_b64decode(s.encode()).decode()

def build_main_panel():
    kb = [
        [InlineKeyboardButton("المصادر (Sources)", callback_data="panel:sources")],
        [InlineKeyboardButton("القنوات (Channels)", callback_data="panel:channels")],
        [InlineKeyboardButton("الأدمن (Admins)", callback_data="panel:admins")],
        [InlineKeyboardButton("إعدادات البوت (Bot Settings)", callback_data="panel:settings")],
        [InlineKeyboardButton("أدوات الصيانة (Maintenance Tools)", callback_data="panel:maintenance")],
        [InlineKeyboardButton("السجلات (Logs)", callback_data="panel:logs")],
        [InlineKeyboardButton("إغلاق", callback_data="panel:close")]
    ]
    return InlineKeyboardMarkup(kb)

def build_admins_panel_buttons():
    rows = list_admins_db()
    kb = []
    for uid, username, perms, added_at in rows:
        label = f"{uid} | @{username}" if username else str(uid)
        kb.append([InlineKeyboardButton(label, callback_data="adm_view:" + str(uid))])
    kb.append([InlineKeyboardButton("إضافة أدمن", callback_data="adm_add")])
    kb.append([InlineKeyboardButton("عودة", callback_data="panel:main")])
    return InlineKeyboardMarkup(kb)

# ---------------------------
# Handlers: admin panel & callbacks
# ---------------------------
def restricted(func):
    def wrapper(update: Update, context: CallbackContext):
        user = update.effective_user
        if is_banned(user.id):
            update.message.reply_text("ممنوع من استخدام البوت (محظور).")
            return
        if user.id == OWNER_ID:
            return func(update, context)
        cur = db.cursor()
        cur.execute("SELECT permissions FROM admins WHERE user_id = ?", (user.id,))
        r = cur.fetchone()
        if not r:
            update.message.reply_text("ما عندك صلاحية لذلك.")
            return
        return func(update, context)
    return wrapper

@restricted
def cmd_adminpanel(update: Update, context: CallbackContext):
    update.message.reply_text("لوحة التحكم - اختر قسم:", reply_markup=build_main_panel())

def admin_panel_callback_adm_view(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    if not data.startswith("adm_view:"):
        return False
    uid = int(data.split(":",1)[1])
    cur = db.cursor()
    cur.execute("SELECT user_id, username, permissions, added_at FROM admins WHERE user_id = ?", (uid,))
    r = cur.fetchone()
    if not r:
        query.answer("الأدمن غير موجود")
        return True
    try:
        perms = json.loads(r[2])
    except:
        perms = []
    kb = []
    for perm_key, perm_desc in PERMISSIONS_LIST.items():
        state = "✅" if (perm_key in perms or perms==["*"]) else "❌"
        kb.append([InlineKeyboardButton(f"{state} {perm_desc}", callback_data=f"adm_perm_toggle:{uid}:{perm_key}")])
    preset_row = []
    for p in PRESET_ROLES.keys():
        preset_row.append(InlineKeyboardButton(p, callback_data=f"adm_preset:{uid}:{p}"))
    kb.append(preset_row)
    kb.append([InlineKeyboardButton("سحب كل الصلاحيات (revoke all)", callback_data=f"adm_revoke_all:{uid}")])
    kb.append([InlineKeyboardButton("عودة", callback_data="panel:admins")])
    query.edit_message_text(f"صلاحيات الأدمن {uid}:", reply_markup=InlineKeyboardMarkup(kb))
    query.answer()
    return True

def admin_permissions_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data or ""
    try:
        if data.startswith("adm_perm_toggle:"):
            _, uid_str, perm_key = data.split(":",2)
            uid = int(uid_str)
            perms = get_admin_permissions(uid)
            if perm_key in perms:
                ok, msg = remove_permission_from_admin(uid, perm_key)
            else:
                ok, msg = add_permission_to_admin(uid, perm_key)
            query.answer(msg)
            admin_panel_callback_adm_view(update, context)
            return
        if data.startswith("adm_preset:"):
            _, uid_str, preset = data.split(":",2)
            uid = int(uid_str)
            ok, msg = set_preset_for_admin(uid, preset)
            query.answer(msg)
            admin_panel_callback_adm_view(update, context)
            return
        if data.startswith("adm_revoke_all:"):
            uid = int(data.split(":",1)[1])
            set_admin_permissions(uid, [])
            query.answer("تمت سحب كل الصلاحيات")
            admin_panel_callback_adm_view(update, context)
            return
    except Exception as e:
        push_log("ERROR", f"admin_permissions_callback error: {traceback.format_exc()}")
        query.answer("خطأ داخلي في تعديل الصلاحيات")

def panel_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data or ""
    user = query.from_user
    try:
        if data == "panel:close":
            query.edit_message_text("تم الإغلاق.")
            query.answer()
            return

        if data == "panel:main":
            query.edit_message_text("لوحة التحكم - اختر قسم:", reply_markup=build_main_panel())
            query.answer()
            return

        if data == "panel:sources":
            cur = db.cursor()
            cur.execute("SELECT url, name, enabled FROM sources")
            rows = cur.fetchall()
            kb = []
            for url, name, enabled in rows:
                label = f"{'✅' if enabled else '❌'} {name}"
                cb = "src_toggle:" + encode_id(url)
                kb.append([InlineKeyboardButton(label, callback_data=cb)])
            kb.append([InlineKeyboardButton("إضافة مصدر جديد", callback_data="src_add")])
            kb.append([InlineKeyboardButton("تعطيل/تفعيل الكل", callback_data="src_toggle_all")])
            kb.append([InlineKeyboardButton("عودة", callback_data="panel:main")])
            query.edit_message_text("المصادر:", reply_markup=InlineKeyboardMarkup(kb))
            query.answer()
            return

        if data.startswith("src_toggle:"):
            url = decode_id(data.split(":",1)[1])
            cur = db.cursor()
            cur.execute("SELECT enabled FROM sources WHERE url = ?", (url,))
            r = cur.fetchone()
            if r:
                set_source_enabled(url, not bool(r[0]))
                query.answer("تم التبديل")
            else:
                query.answer("المصدر غير موجود")
            panel_callback(update, context)
            return

        if data == "src_toggle_all":
            cur = db.cursor()
            cur.execute("SELECT url, enabled FROM sources")
            rows = cur.fetchall()
            any_enabled = any(r[1]==1 for r in rows)
            for r in rows:
                set_source_enabled(r[0], not any_enabled)
            query.answer("تم تبديل حالة كل المصادر")
            panel_callback(update, context)
            return

        if data == "src_add":
            query.answer()
            query.edit_message_text("أرسل الرابط واسم المصدر مفصول بمسافة (مثال):\nhttps://site/rss.xml اسم الموقع")
            context.user_data['awaiting_add_source'] = True
            return

        if data == "panel:channels":
            rows = list_channels_db()
            kb = []
            for chat_id, title, blocked, added_by, added_at in rows:
                label = f"{chat_id} | {'🔒' if blocked else '🔓'} {title or ''}"
                enc = encode_id(str(chat_id))
                kb.append([InlineKeyboardButton(label, callback_data="noop")])
                kb.append([
                    InlineKeyboardButton("حظر/إلغاء", callback_data=("ch_block:" + enc if not blocked else "ch_unblock:" + enc)),
                    InlineKeyboardButton("حذف", callback_data="ch_remove:" + enc)
                ])
            kb.append([InlineKeyboardButton("إضافة قناة/جروب يدوي", callback_data="ch_add")])
            kb.append([InlineKeyboardButton("حظر كل القنوات مؤقتاً", callback_data="ch_block_all")])
            kb.append([InlineKeyboardButton("عودة", callback_data="panel:main")])
            query.edit_message_text("قنوات مضافة:", reply_markup=InlineKeyboardMarkup(kb))
            query.answer()
            return

        if data.startswith("ch_block:") or data.startswith("ch_unblock:"):
            enc = data.split(":",1)[1]
            chat_id = decode_id(enc)
            cur = db.cursor()
            if data.startswith("ch_block:"):
                cur.execute("UPDATE channels SET blocked = 1 WHERE chat_id = ?", (chat_id,))
                push_log("INFO", f"Channel blocked via panel: {chat_id}")
            else:
                cur.execute("UPDATE channels SET blocked = 0 WHERE chat_id = ?", (chat_id,))
                push_log("INFO", f"Channel unblocked via panel: {chat_id}")
            db.commit()
            panel_callback(update, context)
            query.answer("تم")
            return

        if data.startswith("ch_remove:"):
            chat_id = decode_id(data.split(":",1)[1])
            remove_channel_db(chat_id)
            query.answer("تم الحذف")
            panel_callback(update, context)
            return

        if data == "ch_add":
            query.answer()
            query.edit_message_text("أرسل معرف القناة أو اسم المستخدم (مثال: -1001234567890 أو @channelusername):")
            context.user_data['awaiting_add_channel'] = True
            return

        if data == "ch_block_all":
            cur = db.cursor()
            cur.execute("UPDATE channels SET blocked = 1")
            db.commit()
            push_log("INFO", "All channels blocked via panel")
            query.answer("تم حظر جميع القنوات مؤقتاً")
            panel_callback(update, context)
            return

        if data == "panel:admins":
            kb_markup = build_admins_panel_buttons()
            query.edit_message_text("الأدمنز:", reply_markup=kb_markup)
            query.answer()
            return

        if data == "adm_add":
            query.answer()
            query.edit_message_text("أرسل user_id واسم المستخدم (اختياري) مفصول بمسافة:\nمثال: 123456789 username")
            context.user_data['awaiting_add_admin'] = True
            return

        if data.startswith("adm_remove:"):
            uid = int(data.split(":",1)[1])
            remove_admin_db(uid)
            query.answer("تمت إزالة الأدمن")
            panel_callback(update, context)
            return

        if data == "panel:settings":
            st = {
                "global_enabled": get_setting("global_enabled", True),
                "download_media": get_setting("download_media", True),
                "auto_add_channels": get_setting("auto_add_channels", True),
                "notify_owner": get_setting("notify_owner", True)
            }
            kb = []
            for k, v in st.items():
                label = ("✅" if v else "❌") + " " + k
                kb.append([InlineKeyboardButton(label, callback_data="set_setting:" + k)])
            kb.append([InlineKeyboardButton("تعطيل البوت (stop all posting)", callback_data="set_setting:global_enabled_force_off")])
            kb.append([InlineKeyboardButton("عودة", callback_data="panel:main")])
            query.edit_message_text("إعدادات:", reply_markup=InlineKeyboardMarkup(kb))
            query.answer()
            return

        if data.startswith("set_setting:"):
            arg = data.split(":",1)[1]
            if arg == "global_enabled_force_off":
                set_setting("global_enabled", False)
                query.answer("تم إيقاف البوت (global_disabled)")
                panel_callback(update, context)
                return
            cur_val = get_setting(arg, True)
            set_setting(arg, not cur_val)
            query.answer("تم التبديل")
            panel_callback(update, context)
            return

        if data == "panel:maintenance":
            mm = get_setting("maintenance_mode", {"on": False, "reason": "", "until": None})
            kb = [
                [InlineKeyboardButton(f"{'✅' if mm['on'] else '❌'} Maintenance mode", callback_data="mg_toggle")],
                [InlineKeyboardButton("ضبط وضع الصيانة (مع سبب ومدة)", callback_data="mg_set")],
                [InlineKeyboardButton("حظر مؤقت (Temp ban)", callback_data="ban_menu")],
                [InlineKeyboardButton("رفع حظر (Unban)", callback_data="unban_menu")],
                [InlineKeyboardButton("تنظيف sent_links (Clean old links)", callback_data="clean_links")],
                [InlineKeyboardButton("تصدير السجلات (Export Logs)", callback_data="export_logs")],
                [InlineKeyboardButton("عودة", callback_data="panel:main")]
            ]
            query.edit_message_text("أدوات الصيانة:", reply_markup=InlineKeyboardMarkup(kb))
            query.answer()
            return

        if data == "mg_toggle":
            mm = get_setting("maintenance_mode", {"on": False, "reason": "", "until": None})
            mm['on'] = not mm.get('on', False)
            if not mm['on']:
                mm['reason'] = ""
                mm['until'] = None
            set_setting("maintenance_mode", mm)
            query.answer("تم التبديل")
            panel_callback(update, context)
            return

        if data == "mg_set":
            query.answer()
            query.edit_message_text("أرسل سبب الصيانة ثم مدة بالساعة (مثال):\n`سبب الصيانة | 2`  <- يعني 2 ساعة", parse_mode=ParseMode.MARKDOWN)
            context.user_data['awaiting_set_maintenance'] = True
            return

        if data == "ban_menu":
            kb = [
                [InlineKeyboardButton("حظر بواسطة user_id", callback_data="ban_by_id")],
                [InlineKeyboardButton("حظر بواسطة @username", callback_data="ban_by_username")],
                [InlineKeyboardButton("عودة", callback_data="panel:maintenance")]
            ]
            query.edit_message_text("اختر نوع الحظر:", reply_markup=InlineKeyboardMarkup(kb))
            query.answer()
            return

        if data == "ban_by_id":
            query.answer()
            query.edit_message_text("أرسل: user_id مدة_بالدقائق سبب_اختياري\nمثال: `123456789 60 تسبب بإزعاج`", parse_mode=ParseMode.MARKDOWN)
            context.user_data['awaiting_ban_by_id'] = True
            return

        if data == "ban_by_username":
            query.answer()
            query.edit_message_text("أرسل: @username مدة_بالدقائق سبب_اختياري\nمثال: `@someuser 1440 سبام`", parse_mode=ParseMode.MARKDOWN)
            context.user_data['awaiting_ban_by_username'] = True
            return

        if data == "unban_menu":
            query.answer()
            query.edit_message_text("أرسل user_id لرفع الحظر أو اضغط 'قائمة المحظورين' لإظهارهم.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("قائمة المحظورين", callback_data="show_bans")],
                [InlineKeyboardButton("عودة", callback_data="panel:maintenance")]
            ]))
            context.user_data['awaiting_unban'] = True
            return

        if data == "show_bans":
            cur = db.cursor()
            cur.execute("SELECT user_id, username, reason, expires_at, banned_at FROM bans")
            rows = cur.fetchall()
            if not rows:
                query.edit_message_text("لا يوجد محظورين.")
                query.answer()
                return
            text = "<b>قائمة المحظورين:</b>\n"
            for r in rows:
                text += f"- {r[0]} @{r[1]} | reason: {r[2]} | until: {r[3]} | banned_at: {r[4]}\n"
            query.edit_message_text(text, parse_mode=ParseMode.HTML)
            query.answer()
            return

        if data == "clean_links":
            query.answer()
            query.edit_message_text("أرسل عدد الأيام: سيتم حذف روابط أقدم من هذا (مثال: 30)")
            context.user_data['awaiting_clean_links'] = True
            return

        if data == "export_logs":
            cur = db.cursor()
            cur.execute("SELECT ts, level, message FROM events ORDER BY id DESC LIMIT 200")
            rows = cur.fetchall()
            if not rows:
                query.answer("لا سجلات")
                return
            msg = "آخر السجلات:\n"
            for r in rows[::-1]:
                msg += f"{r[0]} | {r[1]} | {r[2][:400]}\n"
            if len(msg) < 4000:
                bot.send_message(chat_id=user.id, text=msg)
            else:
                fname = f"logs_export_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.txt"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(msg)
                bot.send_document(chat_id=user.id, document=open(fname, "rb"))
                try:
                    os.remove(fname)
                except:
                    pass
            query.answer("تم إرسال السجلات لك بالخاص")
            return

        query.answer()
    except Exception as e:
        push_log("ERROR", f"panel_callback error: {traceback.format_exc()}")
        query.answer("حدث خطأ داخلي.")

# Register callbacks specific to admin perms before the generic panel handler
dispatcher.add_handler(CallbackQueryHandler(admin_permissions_callback, pattern=r'^(adm_perm_toggle:|adm_preset:|adm_revoke_all:)'))
dispatcher.add_handler(CallbackQueryHandler(admin_panel_callback_adm_view, pattern=r'^adm_view:'))
dispatcher.add_handler(CallbackQueryHandler(panel_callback))

# ---------------------------
# Message handlers for awaited flows
# ---------------------------
def text_message_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if is_banned(user.id):
        update.message.reply_text("ممنوع من استخدام البوت (محظور).")
        return

    if context.user_data.get('awaiting_add_source'):
        text = update.message.text.strip()
        parts = text.split(maxsplit=1)
        url = parts[0]
        name = parts[1] if len(parts) > 1 else url
        add_source(url, name)
        update.message.reply_text(f"تمت إضافة المصدر: {name}\n{url}")
        context.user_data['awaiting_add_source'] = False
        return

    if context.user_data.get('awaiting_add_channel'):
        text = update.message.text.strip()
        try:
            chat = bot.get_chat(text)
            add_channel_db(chat.id, chat.title or chat.username or "", user.id)
            update.message.reply_text(f"تمت إضافة القناة/جروب: {chat.id} - {chat.title or chat.username}")
            owner_notify(f"Channel added by {user.id} ({user.username}) -> {chat.id}")
        except Exception as e:
            update.message.reply_text(f"خطأ بجلب القناة: {e}")
        context.user_data['awaiting_add_channel'] = False
        return

    if context.user_data.get('awaiting_add_admin'):
        text = update.message.text.strip()
        parts = text.split(maxsplit=1)
        try:
            uid = int(parts[0])
            uname = parts[1] if len(parts) > 1 else ""
            add_admin_db(uid, uname, ["*"])
            update.message.reply_text(f"تمت إضافة أدمن: {uid}")
        except Exception as e:
            update.message.reply_text(f"خطأ: تأكد من user_id صحيح. {e}")
        context.user_data['awaiting_add_admin'] = False
        return

    if context.user_data.get('awaiting_set_maintenance'):
        text = update.message.text.strip()
        if '|' in text:
            reason, hours = [p.strip() for p in text.split('|',1)]
            try:
                hrs = float(hours)
                until = (datetime.utcnow() + timedelta(hours=hrs)).isoformat()
                mm = {"on": True, "reason": reason, "until": until}
                set_setting("maintenance_mode", mm)
                update.message.reply_text(f"تم تفعيل وضع الصيانة حتى {until} UTC مع السبب: {reason}")
                owner_notify(f"Maintenance ON by {user.id}: {reason} until {until}")
            except Exception as e:
                update.message.reply_text("خطأ بالمدة. استخدم ساعات رقمية مثل: 2 أو 0.5")
        else:
            update.message.reply_text("اكتب: سبب الصيانة | عدد_الساعات  (مثال: تحديثات | 2)")
        context.user_data['awaiting_set_maintenance'] = False
        return

    if context.user_data.get('awaiting_ban_by_id'):
        text = update.message.text.strip()
        parts = text.split(maxsplit=2)
        try:
            uid = int(parts[0])
            mins = int(parts[1]) if len(parts) > 1 else 0
            reason = parts[2] if len(parts) > 2 else ""
            expires = None
            if mins > 0:
                expires = (datetime.utcnow() + timedelta(minutes=mins)).isoformat()
            ban_user_db(uid, "", reason, expires)
            update.message.reply_text(f"تم حظر {uid} مدة {mins} دقيقة سبب: {reason}")
            owner_notify(f"User {uid} banned by {user.id} minutes={mins} reason={reason}")
        except Exception as e:
            update.message.reply_text(f"خطأ بصيغة الحظر: {e}")
        context.user_data['awaiting_ban_by_id'] = False
        return

    if context.user_data.get('awaiting_ban_by_username'):
        text = update.message.text.strip()
        parts = text.split(maxsplit=2)
        try:
            uname = parts[0].lstrip("@")
            mins = int(parts[1]) if len(parts) > 1 else 0
            reason = parts[2] if len(parts) > 2 else ""
            try:
                user_obj = bot.get_chat("@" + uname)
                uid = user_obj.id
            except Exception:
                uid = None
            expires = None
            if mins > 0:
                expires = (datetime.utcnow() + timedelta(minutes=mins)).isoformat()
            if uid:
                ban_user_db(uid, uname, reason, expires)
                update.message.reply_text(f"تم حظر @{uname} ({uid}) مدة {mins} دقيقة سبب: {reason}")
                owner_notify(f"User @{uname} ({uid}) banned by {user.id} minutes={mins} reason={reason}")
            else:
                ban_user_db(0, uname, reason, expires)
                update.message.reply_text(f"تمت إضافة @{uname} للقائمة (لم نتحصل على ID). سينظر النظام عندما يحاول المستخدم التفاعل.")
                owner_notify(f"User @{uname} (no id resolved) banned record by {user.id} minutes={mins} reason={reason}")
        except Exception as e:
            update.message.reply_text(f"خطأ: {e}")
        context.user_data['awaiting_ban_by_username'] = False
        return

    if context.user_data.get('awaiting_clean_links'):
        text = update.message.text.strip()
        try:
            days = int(text)
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            cur = db.cursor()
            cur.execute("DELETE FROM sent_links WHERE posted_at < ?", (cutoff,))
            deleted = cur.rowcount
            db.commit()
            update.message.reply_text(f"تم حذف روابط أقدم من {days} يوم. المحذوف: {deleted}")
            push_log("INFO", f"Cleaned sent_links older than {days} days. deleted={deleted}")
        except Exception as e:
            update.message.reply_text(f"خطأ: {e}")
        context.user_data['awaiting_clean_links'] = False
        return

    update.message.reply_text("استعمل /adminpanel للوصول للوحة التحكم.")

dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, text_message_handler))

# --------------------------------
# my_chat_member to auto-add channel, detect admin promotion
# --------------------------------
def my_chat_member(update: Update, context: CallbackContext):
    try:
        chat = update.my_chat_member.chat
        new_status = update.my_chat_member.new_chat_member
        by_user = update.my_chat_member.from_user
        push_log("INFO", f"my_chat_member update: {chat.id} status={new_status.status} by {by_user.id}")
        if get_setting("auto_add_channels", True):
            add_channel_db(chat.id, chat.title or chat.username or "", by_user.id)
            if get_setting("notify_owner", True):
                owner_notify(f"تمت إضافة البوت لقناة/جروب: {chat.id} ({chat.title or chat.username}) by {by_user.id}")
    except Exception as e:
        push_log("ERROR", f"my_chat_member error: {traceback.format_exc()}")

dispatcher.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

# ---------------------------
# Fetch & forward logic
# ---------------------------
def fetch_and_forward_once():
    try:
        mm = get_setting("maintenance_mode", {"on": False, "reason": "", "until": None})
        if mm.get("on"):
            until = mm.get("until")
            if until:
                try:
                    until_dt = datetime.fromisoformat(until)
                    if datetime.utcnow() >= until_dt:
                        mm = {"on": False, "reason": "", "until": None}
                        set_setting("maintenance_mode", mm)
                        push_log("INFO", "Maintenance expired -> turned off automatically")
                        owner_notify("Maintenance mode auto-disabled (expired).")
                    else:
                        push_log("INFO", "Maintenance active -> skipping fetch")
                        return
                except Exception:
                    push_log("INFO", "Maintenance active (no valid until) -> skipping fetch")
                    return
            else:
                push_log("INFO", "Maintenance active (no until) -> skipping fetch")
                return

        if not get_setting("global_enabled", True):
            push_log("INFO", "Global disabled - skipping fetch")
            return

        sources = get_enabled_sources()
        channels = [row[0] for row in list_channels_db() if row[2] == 0]  # not blocked
        if not channels:
            push_log("INFO", "No target channels configured - skipping fetch")
            return

        for url, name in sources:
            try:
                feed = feedparser.parse(url)
                entries = feed.entries or []
                for entry in entries[::-1]:
                    link = getattr(entry, "link", None) or getattr(entry, "id", None)
                    if not link:
                        continue
                    if link_was_sent(link):
                        continue
                    title = getattr(entry, "title", "بدون عنوان")
                    summary = getattr(entry, "summary", "") or ""
                    message = f"📰 <b>{title}</b>\n\n{summary[:800]}\n\n🔗 {link}\n\n🗂️ <i>المصدر: {name}</i>"
                    medias = []
                    if hasattr(entry, "media_content"):
                        for m in entry.media_content:
                            medias.append(m.get("url"))
                    if hasattr(entry, "links"):
                        for l in entry.links:
                            if l.get("rel") == "enclosure" and l.get("href"):
                                medias.append(l.get("href"))

                    for chat_id in channels:
                        try:
                            if medias and get_setting("download_media", True):
                                sent_any = False
                                for murl in medias[:2]:
                                    try:
                                        r = requests.get(murl, stream=True, timeout=15)
                                        r.raise_for_status()
                                        ctype = r.headers.get("Content-Type", "")
                                        if "image" in ctype:
                                            bot.send_photo(chat_id=chat_id, photo=r.content, caption=message, parse_mode=ParseMode.HTML)
                                        else:
                                            bot.send_document(chat_id=chat_id, document=r.content, filename=murl.split("/")[-1], caption=message, parse_mode=ParseMode.HTML)
                                        sent_any = True
                                    except Exception as e:
                                        push_log("ERROR", f"Media send failed {murl} -> {chat_id}: {e}")
                                if not sent_any:
                                    bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
                            else:
                                bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
                            push_log("INFO", f"Posted new item from {name} to {chat_id}: {title}")
                        except Exception as e:
                            push_log("ERROR", f"Failed to post to {chat_id}: {e}")
                    add_sent_link(link)
            except Exception as e:
                push_log("ERROR", f"Failed to process source {url}: {e}")
    except Exception as e:
        push_log("ERROR", f"fetch outer error: {traceback.format_exc()}")
        if get_setting("notify_owner", True):
            owner_notify(f"<b>fetch error</b>\n<pre>{traceback.format_exc()[:1000]}</pre>")

# ---------------------------
# Periodic job: expire temp bans, housekeeping
# ---------------------------
def expire_checks():
    try:
        cur = db.cursor()
        cur.execute("SELECT user_id, expires_at FROM bans WHERE expires_at IS NOT NULL")
        rows = cur.fetchall()
        for uid, expires in rows:
            try:
                if expires and datetime.fromisoformat(expires) <= datetime.utcnow():
                    unban_user_db(uid)
                    owner_notify(f"تم رفع الحظر المؤقت عن: {uid} (انتهى الوقت)")
            except Exception as e:
                push_log("ERROR", f"Expire check error for {uid}: {e}")
    except Exception as e:
        push_log("ERROR", f"expire_checks outer error: {traceback.format_exc()}")

# ---------------------------
# Admin commands for permissions (grant/revoke/set_perms)
# ---------------------------
@require_permission("grant_perm")
def cmd_grant(update: Update, context: CallbackContext):
    if len(context.args) < 2:
        update.message.reply_text("استخدام: /grant <user_id> <perm1,perm2,...>")
        return
    try:
        uid = int(context.args[0])
        perms = ",".join(context.args[1:]).split(",")
        for p in perms:
            p = p.strip()
            if p:
                add_permission_to_admin(uid, p)
        update.message.reply_text("تم منح الصلاحيات.")
    except Exception as e:
        update.message.reply_text(f"خطأ: {e}")

@require_permission("revoke_perm")
def cmd_revoke(update: Update, context: CallbackContext):
    if len(context.args) < 2:
        update.message.reply_text("استخدام: /revoke <user_id> <perm1,perm2,...>")
        return
    try:
        uid = int(context.args[0])
        perms = ",".join(context.args[1:]).split(",")
        for p in perms:
            p = p.strip()
            if p:
                remove_permission_from_admin(uid, p)
        update.message.reply_text("تم سحب الصلاحيات.")
    except Exception as e:
        update.message.reply_text(f"خطأ: {e}")

@require_permission("add_admin")
def cmd_set_perms(update: Update, context: CallbackContext):
    if len(context.args) < 2:
        update.message.reply_text("استخدام: /set_perms <user_id> <perm1,perm2,...> (اكتب * للصلاحيات الكاملة)")
        return
    try:
        uid = int(context.args[0])
        raw = " ".join(context.args[1:])
        perms = [p.strip() for p in raw.split(",") if p.strip()]
        if "*" in perms:
            perms = ["*"]
        set_admin_permissions(uid, perms)
        update.message.reply_text(f"تم تعيين صلاحيات للمستخدم {uid}: {perms}")
    except Exception as e:
        update.message.reply_text(f"خطأ: {e}")

dispatcher.add_handler(CommandHandler("grant", cmd_grant))
dispatcher.add_handler(CommandHandler("revoke", cmd_revoke))
dispatcher.add_handler(CommandHandler("set_perms", cmd_set_perms))

# ---------------------------
# Register basic commands & start
# ---------------------------
dispatcher.add_handler(CommandHandler("adminpanel", cmd_adminpanel))
dispatcher.add_handler(CommandHandler("start", lambda u,c: u.message.reply_text("مرحبا! استخدم /adminpanel لإدارة.")))
dispatcher.add_handler(CommandHandler("status", lambda u,c: u.message.reply_text(
    f"Channels: {len(list_channels_db())} | Enabled sources: {len(get_enabled_sources())} | Sent links: {count_sent_links()}")))
dispatcher.add_handler(CommandHandler("help", lambda u,c: u.message.reply_text("Use /adminpanel")))

# scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_and_forward_once, 'interval', seconds=CHECK_INTERVAL_SECONDS, next_run_time=datetime.utcnow())
scheduler.add_job(expire_checks, 'interval', seconds=60, next_run_time=datetime.utcnow())
scheduler.start()

push_log("INFO", "Bot v4 started")
owner_notify("🚀 <b>News Forwarder Bot v4 started</b>")

# ---------------------------
# Start polling
# ---------------------------
if __name__ == "__main__":
    try:
        updater.start_polling()
        updater.idle()
    except KeyboardInterrupt:
        push_log("INFO", "Stopped by KeyboardInterrupt")
    except Exception as e:
        push_log("ERROR", f"Bot crashed: {traceback.format_exc()}")
        owner_notify(f"<b>Bot crashed</b>\n<pre>{traceback.format_exc()[:1500]}</pre>")
