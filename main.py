import os
import asyncio
import logging
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError, FloodWaitError, ChannelPrivateError, ChatAdminRequiredError
from dotenv import load_dotenv
# تم حذف keep_alive لحل المشاكل
import sqlite3
import threading
import time

# Load environment variables
load_dotenv()

# Configure comprehensive logging 
logging.basicConfig(
    format='%(asctime)s [%(levelname)8s] %(name)s: %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('telegram_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# إنشاء logger مخصص للبوت
bot_logger = logging.getLogger('TelegramBot')
bot_logger.setLevel(logging.DEBUG)

# Database setup
def init_database():
    conn = sqlite3.connect("bot.db", check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            phone_number TEXT,
            session_string TEXT,
            is_verified INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vip_users (
            user_id INTEGER PRIMARY KEY,
            end_date TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            ban_expires TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            permissions TEXT DEFAULT 'basic'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            setting_name TEXT PRIMARY KEY,
            setting_value TEXT
        )
    ''')
    
    # تحديث جدول القنوات لدعم أكثر من قناة لكل مستخدم
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id TEXT,
            channel_name TEXT,
            source_channels TEXT,
            forward_mode TEXT DEFAULT 'with_source',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # إضافة عمود forward_mode للجداول الموجودة
    try:
        cursor.execute('ALTER TABLE user_channels ADD COLUMN forward_mode TEXT DEFAULT "with_source"')
    except sqlite3.OperationalError:
        pass  # العمود موجود بالفعل
    
    # جدول لتتبع حالة التحويل
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS forwarding_status (
            user_id INTEGER PRIMARY KEY,
            is_active INTEGER DEFAULT 0,
            last_activity TEXT,
            error_count INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('INSERT OR IGNORE INTO admins (user_id, permissions) VALUES (7124431342, "super_admin")')
    cursor.execute('INSERT OR IGNORE INTO bot_settings (setting_name, setting_value) VALUES ("bot_status", "active")')
    
    conn.commit()
    conn.close()

# Database helper functions with thread safety
def get_db_connection():
    return sqlite3.connect("bot.db", check_same_thread=False)

def is_admin(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return bool(result)

def is_super_admin(user_id):
    return user_id == 7124431342

def is_user_banned(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ban_expires FROM banned_users WHERE user_id = ? AND is_active = 1", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return False
    
    if result[0]:
        ban_expires = datetime.fromisoformat(result[0])
        if datetime.now() > ban_expires:
            cursor.execute("UPDATE banned_users SET is_active = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            return False
    
    conn.close()
    return True

def is_vip_user(user_id):
    if is_admin(user_id):
        return True
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT end_date FROM vip_users WHERE user_id = ? AND is_active = 1", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return False
    
    end_date = datetime.fromisoformat(result[0])
    if datetime.now() > end_date:
        cursor.execute("UPDATE vip_users SET is_active = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return False
    
    conn.close()
    return True

def is_user_registered(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_verified FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return bool(result and result[0])

def get_bot_status():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT setting_value FROM bot_settings WHERE setting_name = 'bot_status'")
    status_result = cursor.fetchone()
    cursor.execute("SELECT setting_value FROM bot_settings WHERE setting_name = 'bot_message'")
    message_result = cursor.fetchone()
    conn.close()
    
    status = status_result[0] if status_result else "active"
    message = message_result[0] if message_result else None
    return status, message

def ban_user(user_id, days=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    ban_expires = None
    if days:
        ban_expires = (datetime.now() + timedelta(days=days)).isoformat()
    
    cursor.execute('''
        INSERT OR REPLACE INTO banned_users (user_id, ban_expires, is_active)
        VALUES (?, ?, 1)
    ''', (user_id, ban_expires))
    
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE banned_users SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def add_vip_user(user_id, days):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    end_date = (datetime.now() + timedelta(days=days)).isoformat()
    cursor.execute('''
        INSERT OR REPLACE INTO vip_users (user_id, end_date, is_active)
        VALUES (?, ?, 1)
    ''', (user_id, end_date))
    
    conn.commit()
    conn.close()

def remove_vip_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE vip_users SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def add_admin(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def remove_admin(user_id):
    if user_id == 7124431342:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True

def set_bot_status(status, message=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO bot_settings (setting_name, setting_value) VALUES ('bot_status', ?)", (status,))
    if message:
        cursor.execute("INSERT OR REPLACE INTO bot_settings (setting_name, setting_value) VALUES ('bot_message', ?)", (message,))
    conn.commit()
    conn.close()

def get_banned_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT b.user_id, b.ban_expires, u.first_name, u.username
        FROM banned_users b
        LEFT JOIN users u ON b.user_id = u.user_id
        WHERE b.is_active = 1
    ''')
    results = cursor.fetchall()
    conn.close()
    return results

def get_vip_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT v.user_id, v.end_date, u.first_name, u.username
        FROM vip_users v
        LEFT JOIN users u ON v.user_id = u.user_id
        WHERE v.is_active = 1
    ''')
    results = cursor.fetchall()
    conn.close()
    return results

def get_admins():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.user_id, a.permissions, u.first_name, u.username
        FROM admins a
        LEFT JOIN users u ON a.user_id = u.user_id
    ''')
    results = cursor.fetchall()
    conn.close()
    return results

def unban_all_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE banned_users SET is_active = 0")
    conn.commit()
    conn.close()

def remove_all_admins():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE user_id != 7124431342")
    conn.commit()
    conn.close()

# تحديث دوال إدارة القنوات لدعم أكثر من قناة
def add_user_channel(user_id, channel_id, channel_name="", source_channels="", forward_mode="with_source"):
    """إضافة قناة جديدة للمستخدم"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO user_channels (user_id, channel_id, channel_name, source_channels, forward_mode, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
    ''', (user_id, channel_id, channel_name, source_channels, forward_mode))
    conn.commit()
    conn.close()

def update_channel_sources(user_id, channel_id, source_channels):
    """تحديث مصادر قناة معينة"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE user_channels 
        SET source_channels = ?
        WHERE user_id = ? AND channel_id = ? AND is_active = 1
    ''', (source_channels, user_id, channel_id))
    conn.commit()
    conn.close()

def update_channel_forward_mode(user_id, channel_id, forward_mode):
    """تحديث نوع التحويل لقناة"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE user_channels 
        SET forward_mode = ?
        WHERE user_id = ? AND channel_id = ? AND is_active = 1
    ''', (forward_mode, user_id, channel_id))
    conn.commit()
    conn.close()

def get_user_channels(user_id):
    """الحصول على جميع قنوات المستخدم"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, channel_id, channel_name, source_channels, forward_mode, created_at 
        FROM user_channels 
        WHERE user_id = ? AND is_active = 1 
        ORDER BY created_at DESC
    ''', (user_id,))
    results = cursor.fetchall()
    conn.close()
    return results

def delete_user_channel(user_id, channel_id):
    """حذف قناة من قنوات المستخدم"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE user_channels 
        SET is_active = 0 
        WHERE user_id = ? AND channel_id = ?
    ''', (user_id, channel_id))
    conn.commit()
    conn.close()

def get_all_active_forwards():
    """الحصول على جميع إعدادات التحويل النشطة"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT uc.user_id, uc.channel_id, uc.source_channels, u.session_string, uc.channel_name, uc.forward_mode
        FROM user_channels uc
        JOIN users u ON uc.user_id = u.user_id
        WHERE uc.is_active = 1 AND u.is_verified = 1 AND uc.source_channels != ''
    ''')
    results = cursor.fetchall()
    conn.close()
    return results

def add_user_to_db(user_id, username, first_name, phone_number, session_string):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, first_name, phone_number, session_string, is_verified)
        VALUES (?, ?, ?, ?, ?, 1)
    ''', (user_id, username or '', first_name or '', phone_number or '', session_string or ''))
    conn.commit()
    conn.close()

def update_forwarding_status(user_id, is_active, error_count=0):
    """تحديث حالة التحويل للمستخدم"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO forwarding_status 
        (user_id, is_active, last_activity, error_count)
        VALUES (?, ?, ?, ?)
    ''', (user_id, is_active, datetime.now().isoformat(), error_count))
    conn.commit()
    conn.close()

def get_forwarding_status(user_id):
    """الحصول على حالة التحويل للمستخدم"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT is_active, last_activity, error_count 
        FROM forwarding_status 
        WHERE user_id = ?
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

# Initialize database
init_database()

class MessageForwarder:
    """كلاس محدث لتحويل الرسائل مع دعم أفضل"""
    def __init__(self):
        self.clients = {}
        self.forward_mappings = {}
        self.last_forwarded_messages = {}
        self._initializing = False
        self._monitoring_active = False
        self._restart_lock = False
        self.message_handlers = {}  # تخزين معرفات المستمعات
        
    async def initialize_user_clients(self):
        """تهيئة جلسات المستخدمين مع معالجة أفضل للأخطاء"""
        if self._initializing:
            print("🔄 التهيئة قيد التشغيل بالفعل...")
            return
        
        self._initializing = True
        
        try:
            # إغلاق الجلسات السابقة
            await self.cleanup_clients()
            
            forwards = get_all_active_forwards()
            print(f"🔄 تحميل {len(forwards)} إعداد تحويل نشط...")
            
            for user_id, target_channel, source_channels, session_string, channel_name, forward_mode in forwards:
                if session_string and session_string.strip():
                    await self._initialize_single_user(user_id, target_channel, source_channels, session_string, channel_name, forward_mode)
                        
        except Exception as e:
            print(f"❌ خطأ في تهيئة جلسات المستخدمين: {e}")
        finally:
            self._initializing = False
    
    async def _initialize_single_user(self, user_id, target_channel, source_channels, session_string, channel_name, forward_mode="with_source"):
        """تهيئة جلسة مستخدم واحد"""
        try:
            api_id_env = os.getenv('API_ID')
            api_hash = os.getenv('API_HASH')
            
            if not api_id_env or not api_hash:
                print(f"❌ مفاتيح API مفقودة للمستخدم {user_id}")
                return
                
            api_id = int(api_id_env)
            
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            await client.start()
            
            # التحقق من صحة الجلسة
            me = await client.get_me()
            if not me:
                print(f"❌ جلسة غير صالحة للمستخدم {user_id}")
                update_forwarding_status(user_id, False, 1)
                return
            
            # التحقق من صلاحيات القنوات
            sources = [s.strip() for s in source_channels.split(',') if s.strip()]
            verified_sources = await self.verify_channel_access(client, sources, user_id)
            
            if not verified_sources:
                print(f"⚠️ لا توجد قنوات مصدر صالحة للمستخدم {user_id}")
                await client.disconnect()
                update_forwarding_status(user_id, False, 1)
                return
            
            # التحقق من القناة المستهدفة
            target_valid = await self.verify_target_channel(client, target_channel, user_id)
            if not target_valid:
                print(f"❌ القناة المستهدفة غير صالحة للمستخدم {user_id}")
                await client.disconnect()
                update_forwarding_status(user_id, False, 1)
                return
            
            self.clients[user_id] = client
            
            # تخزين معلومات التحويل
            mapping_key = f"{user_id}_{target_channel}"
            self.forward_mappings[mapping_key] = {
                'user_id': user_id,
                'target': target_channel,
                'target_name': channel_name,
                'sources': verified_sources,
                'client': client,
                'forward_mode': forward_mode
            }
            
            # تسجيل مستمعات الرسائل
            await self._setup_message_listeners(client, user_id, target_channel, verified_sources)
            
            print(f"✅ تم تحميل جلسة المستخدم {user_id} مع {len(verified_sources)} قنوات مصدر")
            update_forwarding_status(user_id, True, 0)
            
        except Exception as e:
            print(f"❌ خطأ في تحميل جلسة المستخدم {user_id}: {e}")
            update_forwarding_status(user_id, False, 1)
    
    async def _setup_message_listeners(self, client, user_id, target_channel, sources):
        """إعداد مستمعات الرسائل للقنوات المصدر مع منع التكرار"""
        handler_key = f"{user_id}_{target_channel}"
        
        # إزالة المعالجات السابقة إن وجدت
        if handler_key in self.message_handlers:
            for handler in self.message_handlers[handler_key]:
                try:
                    client.remove_event_handler(handler)
                except:
                    pass
        
        self.message_handlers[handler_key] = []
        
        for source in sources:
            try:
                # إنشاء معالج فريد لكل مصدر
                async def create_handler(source_channel, target_ch, user_id_val):
                    async def handle_new_message(event):
                        # تحقق من عدم تكرار الرسالة
                        message_id = f"{event.chat_id}_{event.message.id}"
                        if message_id not in self.last_forwarded_messages:
                            self.last_forwarded_messages[message_id] = True
                            await self.forward_message(event, target_ch, user_id_val, source_channel)
                            # تنظيف الذاكرة بعد 5 دقائق لتجنب التراكم
                            # تنظيف الذاكرة بعد فترة (بدون انتظار)
                            asyncio.create_task(self._cleanup_message_cache(message_id))
                    return handle_new_message
                
                handler = await create_handler(source, target_channel, user_id)
                client.add_event_handler(handler, events.NewMessage(chats=source))
                self.message_handlers[handler_key].append(handler)
                
                print(f"🎯 بدء مراقبة {source} للمستخدم {user_id}")
                
            except Exception as e:
                print(f"❌ خطأ في مراقبة {source} للمستخدم {user_id}: {e}")
    
    async def cleanup_clients(self):
        """إغلاق جميع الجلسات السابقة وإزالة المستمعات"""
        # إزالة جميع معالجات الرسائل أولاً
        for user_id, client in self.clients.items():
            try:
                # إزالة جميع معالجات الأحداث لهذا العميل
                client.remove_event_handlers()
                await client.disconnect()
                print(f"🔌 تم إغلاق جلسة المستخدم {user_id}")
            except Exception as e:
                print(f"❌ خطأ في إغلاق جلسة المستخدم {user_id}: {e}")
        
        self.clients.clear()
        self.forward_mappings.clear()
        self.message_handlers.clear()
    
    async def verify_channel_access(self, client, sources, user_id):
        """التحقق من صلاحية الوصول للقنوات المصدر مع تجاهل حد المعدل المؤقت"""
        verified_sources = []
        
        for source in sources:
            try:
                entity = await client.get_entity(source)
                
                # محاولة قراءة آخر رسالة للتأكد من صحة الوصول
                messages = await client.get_messages(entity, limit=1)
                
                verified_sources.append(source)
                print(f"✅ تحقق من صلاحية الوصول للقناة {source} للمستخدم {user_id}")
                
            except FloodWaitError as e:
                # تجاهل حد المعدل وإضافة المصدر كصالح مؤقتاً
                print(f"⚠️ حد معدل لـ {source} - سيتم المحاولة لاحقاً")
                verified_sources.append(source)  # إضافة رغم الخطأ المؤقت
                continue
            except Exception as e:
                print(f"❌ خطأ في التحقق من القناة {source} للمستخدم {user_id}: {e}")
                # إذا كان خطأ في حل الاسم، أضفه أيضاً كمؤقت
                if "ResolveUsernameRequest" in str(e) or "wait" in str(e).lower():
                    print(f"⚠️ سيتم إضافة {source} مؤقتاً رغم الخطأ")
                    verified_sources.append(source)
                continue
        
        return verified_sources
    
    async def verify_target_channel(self, client, target_channel, user_id):
        """التحقق من صلاحية القناة المستهدفة مع تجاهل حد المعدل المؤقت"""
        try:
            entity = await client.get_entity(target_channel)
            
            # التحقق من صلاحيات الإرسال
            permissions = await client.get_permissions(entity, 'me')
            if permissions and permissions.is_banned:
                print(f"❌ المستخدم {user_id} محظور من القناة {target_channel}")
                return False
            
            print(f"✅ تحقق من صلاحية القناة المستهدفة {target_channel} للمستخدم {user_id}")
            return True
            
        except FloodWaitError as e:
            print(f"⚠️ حد معدل للقناة المستهدفة {target_channel} - سيتم قبولها مؤقتاً")
            return True  # قبول مؤقت رغم حد المعدل
        except Exception as e:
            print(f"❌ خطأ في التحقق من القناة المستهدفة {target_channel} للمستخدم {user_id}: {e}")
            # إذا كان خطأ في حل الاسم، اقبلها مؤقتاً
            if "ResolveUsernameRequest" in str(e) or "wait" in str(e).lower():
                print(f"⚠️ سيتم قبول القناة المستهدفة {target_channel} مؤقتاً رغم الخطأ")
                return True
            return False
    
    async def _cleanup_message_cache(self, message_id):
        """تنظيف رسالة من الذاكرة بعد فترة"""
        await asyncio.sleep(300)  # 5 دقائق
        self.last_forwarded_messages.pop(message_id, None)
        
    async def forward_message(self, event, target_channel, user_id, source_channel):
        """تحويل الرسالة إلى القناة المستهدفة مع معالجة محسنة للأخطاء ومنع التكرار"""
        # التحقق من عدم تكرار الرسالة
        message_key = f"{event.chat_id}_{event.message.id}_{user_id}_{target_channel}"
        if message_key in self.last_forwarded_messages:
            return  # الرسالة تم تحويلها بالفعل
        
        max_retries = 2  # تقليل عدد المحاولات لتجنب التكرار
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                client = self.clients.get(user_id)
                if not client:
                    print(f"❌ جلسة المستخدم {user_id} غير موجودة")
                    return
                
                # التحقق من صلاحيات المستخدم (تبسيط الفحص)
                if not is_user_registered(user_id) or is_user_banned(user_id):
                    return
                
                # الحصول على نوع التحويل
                forward_mode = "with_source"  # القيمة الافتراضية
                
                # البحث عن إعدادات التحويل للمستخدم
                for mapping_key, mapping_data in self.forward_mappings.items():
                    if mapping_data['user_id'] == user_id and mapping_data['target'] == target_channel:
                        forward_mode = mapping_data.get('forward_mode', 'with_source')
                        break
                
                # تسجيل الرسالة لمنع التكرار
                self.last_forwarded_messages[message_key] = True
                
                # تحويل الرسالة بناءً على نوع التحويل
                if forward_mode == "without_source":
                    # إرسال الرسالة بدون ذكر المصدر
                    if event.message.media:
                        await client.send_file(
                            target_channel,
                            event.message.media,
                            caption=event.message.text or ""
                        )
                    else:
                        await client.send_message(
                            target_channel,
                            event.message.text or ""
                        )
                    print(f"📤 تم إرسال رسالة {event.message.id} من {source_channel} إلى {target_channel} (بدون ذكر المصدر)")
                else:
                    # تحويل الرسالة مع ذكر المصدر
                    await client.forward_messages(target_channel, event.message)
                    print(f"📤 تم تحويل رسالة {event.message.id} من {source_channel} إلى {target_channel} (مع ذكر المصدر)")
                
                # تنظيف الذاكرة بعد 10 دقائق لتجنب التراكم
                async def cleanup_message_memory():
                    await asyncio.sleep(600)  # 10 دقائق
                    self.last_forwarded_messages.pop(message_key, None)
                
                asyncio.create_task(cleanup_message_memory())
                
                # تحديث حالة التحويل
                update_forwarding_status(user_id, True, 0)
                break
                
            except FloodWaitError as e:
                retry_count += 1
                wait_seconds = e.seconds + 5
                print(f"⏳ انتظار {wait_seconds} ثانية بسبب FloodWait للمستخدم {user_id}")
                if retry_count < max_retries:
                    await asyncio.sleep(wait_seconds)
                else:
                    print(f"❌ فشل تحويل الرسالة بعد {max_retries} محاولات للمستخدم {user_id}")
                    update_forwarding_status(user_id, False, retry_count)
                    
            except (ChannelPrivateError, ChatAdminRequiredError) as e:
                print(f"❌ مشكلة في الصلاحيات للمستخدم {user_id}: {e}")
                update_forwarding_status(user_id, False, 1)
                break
                
            except Exception as e:
                retry_count += 1
                print(f"❌ خطأ في تحويل الرسالة للمستخدم {user_id} - محاولة {retry_count}: {e}")
                if retry_count < max_retries:
                    await asyncio.sleep(2)
                else:
                    print(f"❌ فشل تحويل الرسالة نهائياً للمستخدم {user_id}")
                    update_forwarding_status(user_id, False, retry_count)
    
    async def verify_user_permissions(self, user_id):
        """التحقق من صلاحيات المستخدم للتحويل"""
        # التحقق من أن المستخدم مسجل أو VIP أو admin
        if not is_user_registered(user_id) and not is_vip_user(user_id) and not is_admin(user_id):
            return False
        
        # التحقق من أن المستخدم غير محظور
        if is_user_banned(user_id):
            return False
        
        # التحقق من حالة البوت
        bot_status, _ = get_bot_status()
        if bot_status != "active" and not is_admin(user_id):
            return False
        
        return True
    
    async def restart_forwarding(self):
        """إعادة تشغيل نظام التحويل مع منع التداخل"""
        if self._restart_lock:
            print("🔄 إعادة التشغيل قيد التنفيذ بالفعل...")
            return
        
        self._restart_lock = True
        try:
            print("🔄 إعادة تشغيل نظام التحويل...")
            await self.cleanup_clients()
            await self.initialize_user_clients()
            print("✅ تم إعادة تشغيل نظام التحويل بنجاح")
        finally:
            self._restart_lock = False

class TelegramBot:
    def __init__(self):
        api_id_str = os.getenv('API_ID')
        self.api_hash = os.getenv('API_HASH')
        self.bot_token = os.getenv('BOT_TOKEN')
        
        if not api_id_str or not self.api_hash or not self.bot_token:
            raise ValueError("Missing required environment variables")
            
        try:
            self.api_id = int(api_id_str) if api_id_str else 0
        except (ValueError, TypeError):
            raise ValueError("API_ID must be a valid integer")
        
        if not self.api_hash or not self.api_id:
            raise ValueError("Missing API credentials")
        self.bot = TelegramClient('bot_session', self.api_id, self.api_hash or '')
        
        # Store pending operations
        self.pending_registrations = {}
        self.pending_codes = {}
        self.pending_2fa = {}
        self.pending_inputs = {}
        self.pending_channel_operations = {}
        
        # إضافة نظام تحويل الرسائل المحدث
        try:
            self.message_forwarder = MessageForwarder()
        except Exception as e:
            bot_logger.error(f"❌ خطأ في إنشاء MessageForwarder: {e}")
            self.message_forwarder = None

    async def start_bot(self):
        try:
            bot_logger.info("🚀 بدء تشغيل البوت...")
            
            if not self.bot_token:
                bot_logger.error("❌ BOT_TOKEN غير موجود!")
                raise ValueError("BOT_TOKEN is required")
            
            bot_logger.info("🔑 تم تحميل التوكن بنجاح")
            
            # تشغيل البوت مع تسجيل مفصل
            await self.bot.start(bot_token=self.bot_token)
            
            # التحقق من معلومات البوت
            me = await self.bot.get_me()
            bot_username = getattr(me, 'username', 'unknown')
            bot_first_name = getattr(me, 'first_name', 'غير محدد')
            bot_id = getattr(me, 'id', 0)
            
            bot_logger.info(f"✅ البوت متصل بنجاح: @{bot_username}")
            bot_logger.info(f"📋 اسم البوت: {bot_first_name}")
            bot_logger.info(f"🆔 معرف البوت: {bot_id}")
            
            # تسجيل معالجات الأحداث مع تسجيل مفصل
            bot_logger.info("📝 تسجيل معالجات الأحداث...")
            
            # تسجيل معالجات الأوامر أولاً (أولوية عالية) - أنماط بسيطة
            command_handlers = [
                (self.handle_start, events.NewMessage(pattern='/start'), "start"),
                (self.handle_help, events.NewMessage(pattern='/help'), "help"),
                (self.handle_settings, events.NewMessage(pattern='/settings'), "settings"),
                (self.handle_admin, events.NewMessage(pattern='/admin'), "admin"),
                (self.handle_login, events.NewMessage(pattern='/login'), "login")
            ]
            
            # معالج callbacks  
            callback_handlers = [
                (self.handle_callback, events.CallbackQuery(), "callback")
            ]
            
            # معالج الرسائل العام (أولوية منخفضة - آخر شيء)
            general_handlers = [
                (self.handle_message, events.NewMessage(), "message")
            ]
            
            # دمج جميع المعالجات بالترتيب الصحيح
            handlers = command_handlers + callback_handlers + general_handlers
            
            for handler, event_type, name in handlers:
                try:
                    self.bot.add_event_handler(handler, event_type)
                    bot_logger.debug(f"✅ تم تسجيل معالج {name}")
                except Exception as e:
                    bot_logger.error(f"❌ فشل في تسجيل معالج {name}: {e}")
            
            bot_logger.info("🔄 تشغيل نظام تحويل الرسائل...")
            
            # تشغيل نظام تحويل الرسائل مع معالجة الأخطاء
            try:
                await self.message_forwarder.initialize_user_clients()
                bot_logger.info("✅ تم تشغيل نظام تحويل الرسائل بنجاح")
            except Exception as e:
                bot_logger.error(f"⚠️ خطأ في تشغيل نظام التحويل: {e}")
            
            bot_logger.info("🤖 تم تشغيل البوت بنجاح!")
            bot_logger.info(f"🔗 رابط البوت: https://t.me/{bot_username}")
            print("🤖 تم تشغيل البوت بنجاح!")
            print(f"🔗 رابط البوت: https://t.me/{bot_username}")
            bot_logger.info("🎯 البوت جاهز لاستقبال الأوامر!")
            
            await self.bot.run_until_disconnected()
            
        except Exception as e:
            bot_logger.error(f"❌ خطأ حرج في تشغيل البوت: {e}")
            bot_logger.critical(f"❌ خطأ حرج: {e}")
            print(f"❌ خطأ حرج: {e}")
            raise

    async def handle_start(self, event):
        user_id = event.sender_id
        message_text = event.message.text
        
        try:
            bot_logger.info(f"🎯 معالج /start تم استدعاؤه! المستخدم: {user_id}, الرسالة: '{message_text}'")
            
            # التأكد من أن هذه رسالة start حقيقية
            if not message_text or not message_text.startswith('/start'):
                bot_logger.warning(f"⚠️ معالج /start استُدعي برسالة خاطئة: '{message_text}'")
                return
                
            bot_logger.info(f"✅ تأكيد: هذه رسالة /start صحيحة من المستخدم {user_id}")
            
            # الحصول على معلومات المستخدم
            user = await event.get_sender()
            username = user.username or "بدون اسم مستخدم"
            first_name = user.first_name or "بدون اسم"
            
            bot_logger.info(f"👤 معلومات المستخدم: {first_name} (@{username})")
            
            # التحقق من حالة البوت
            bot_status, status_message = get_bot_status()
            bot_logger.debug(f"🔍 حالة البوت: {bot_status}")
            
            if bot_status != "active" and not is_admin(user_id):
                bot_logger.warning(f"🚫 البوت متوقف - رفض الوصول للمستخدم {user_id}")
                if status_message:
                    await event.respond(f"🚫 البوت متوقف حالياً\n\n{status_message}")
                else:
                    await event.respond("🚫 البوت متوقف حالياً. يرجى المحاولة لاحقاً")
                return
            
            # التحقق من الحظر
            if is_user_banned(user_id):
                bot_logger.warning(f"🚫 المستخدم المحظور {user_id} حاول الوصول")
                await event.respond("🚫 تم حظرك من استخدام البوت")
                return
            
            bot_logger.info(f"✅ المستخدم {user_id} يستطيع الوصول للبوت")
            
            welcome_text = f"مرحباً {user.first_name}! 👋\n\n"
            welcome_text += "🤖 بوت تحويل الرسائل المطور\n"
            welcome_text += "📤 يمكنك تحويل الرسائل من قنوات متعددة إلى قنواتك\n\n"
            
            keyboard = []
            
            if is_user_registered(user_id):
                bot_logger.info(f"📋 المستخدم {user_id} مسجل في النظام")
                welcome_text += "✅ أنت مسجل في النظام\n"
                keyboard = [
                    [Button.inline("⚙️ الإعدادات", b"user_settings"), Button.inline("📋 قنواتي", b"my_channels")],
                    [Button.inline("🔄 إعادة تشغيل التحويل", b"restart_forwarding")]
                ]
            else:
                bot_logger.info(f"📱 المستخدم {user_id} غير مسجل - يحتاج تسجيل")
                welcome_text += "📱 يرجى تسجيل رقم هاتفك أولاً\n"
                keyboard = [
                    [Button.inline("📱 تسجيل رقم الهاتف", b"register_phone")]
                ]
            
            keyboard.append([Button.inline("📖 المساعدة", b"help")])
            
            # إضافة لوحة الأدمن إذا كان المستخدم أدمن
            if is_admin(user_id):
                bot_logger.info(f"🛡️ المستخدم {user_id} أدمن - إضافة لوحة الأدمن")
                keyboard.append([Button.inline("🛡️ لوحة الأدمن", b"admin_menu")])
            
            await self.safe_edit_or_respond(event, welcome_text, buttons=keyboard)
            bot_logger.info(f"✅ تم إرسال رسالة الترحيب للمستخدم {user_id}")
            
        except Exception as e:
            bot_logger.error(f"❌ خطأ في معالج /start للمستخدم {user_id}: {e}")
            try:
                await event.respond("❌ حدث خطأ في تشغيل الأمر. يرجى المحاولة لاحقاً")
            except:
                bot_logger.error("❌ فشل في إرسال رسالة الخطأ")

    async def safe_edit_or_respond(self, event, message, buttons=None, parse_mode='html'):
        """دالة آمنة لتحرير أو إرسال الرسائل"""
        try:
            bot_logger.debug(f"📤 محاولة إرسال رسالة بطول {len(message)} حرف")
            
            # التحقق من نوع الحدث
            if hasattr(event, 'query') and event.query:
                # هذا callback query - يجب استخدام edit
                bot_logger.debug("🔄 استخدام edit للـ callback query")
                try:
                    await event.edit(message, buttons=buttons, parse_mode=parse_mode)
                    bot_logger.debug("✅ تم تعديل الرسالة بنجاح")
                    return
                except Exception as edit_error:
                    bot_logger.warning(f"⚠️ فشل في تعديل الرسالة: {edit_error}")
                    # إذا فشل التعديل، أرسل رسالة جديدة
                    await event.respond(message, buttons=buttons, parse_mode=parse_mode)
                    bot_logger.debug("✅ تم إرسال رسالة جديدة بدلاً من التعديل")
                    return
            else:
                # رسالة عادية
                bot_logger.debug("📨 إرسال رسالة عادية")
                await event.respond(message, buttons=buttons, parse_mode=parse_mode)
                bot_logger.debug("✅ تم إرسال الرسالة بنجاح")
                
        except Exception as e:
            bot_logger.error(f"❌ خطأ في إرسال الرسالة: {e}")
            try:
                await event.respond(message, buttons=buttons, parse_mode=parse_mode)
                bot_logger.info("✅ تم إرسال الرسالة في المحاولة الثانية")
            except Exception as retry_error:
                bot_logger.error(f"❌ فشل في المحاولة الثانية: {retry_error}")
                await event.respond("❌ حدث خطأ في إرسال الرسالة")

    async def handle_callback(self, event):
        data = event.data.decode('utf-8')
        user_id = event.sender_id
        
        try:
            bot_logger.info(f"🔘 استلام callback: {data} من المستخدم {user_id}")
            
            # التحقق من الحظر
            if is_user_banned(user_id):
                bot_logger.warning(f"🚫 محاولة callback من مستخدم محظور {user_id}")
                await event.answer("🚫 تم حظرك من استخدام البوت", alert=True)
                return
        
            # معالجة أنواع الـ callbacks المختلفة مع تسجيل مفصل
            bot_logger.debug(f"🔍 معالجة callback: {data}")
            
            if data == "start":
                bot_logger.info(f"➡️ استدعاء handle_start_callback للمستخدم {user_id}")
                await self.handle_start_callback(event)
            elif data == "help":
                bot_logger.info(f"❓ عرض المساعدة للمستخدم {user_id}")
                await self.show_help(event)
            elif data == "register_phone":
                bot_logger.info(f"📱 بدء تسجيل الهاتف للمستخدم {user_id}")
                await self.start_registration(event)
            elif data == "user_settings":
                bot_logger.info(f"⚙️ عرض إعدادات المستخدم {user_id}")
                await self.show_user_settings(event)
            elif data == "my_channels":
                bot_logger.info(f"📋 عرض قنوات المستخدم {user_id}")
                await self.show_my_channels(event)
            elif data == "restart_forwarding":
                bot_logger.info(f"🔄 إعادة تشغيل التحويل للمستخدم {user_id}")
                await self.restart_message_forwarding(event)
            elif data == "admin_menu":
                if is_admin(user_id):
                    bot_logger.info(f"🛡️ عرض قائمة الأدمن للمستخدم {user_id}")
                    await self.show_admin_menu(event)
                else:
                    bot_logger.warning(f"⛔ محاولة وصول غير مصرح للأدمن من المستخدم {user_id}")
                    await event.answer("⛔ ليس لديك صلاحية الوصول!", alert=True)
            # معالجة أزرار إدارة القنوات الجديدة
            elif data == "add_channel":
                await self.start_add_channel(event)
            elif data == "add_sources":
                await self.start_add_sources(event)
            elif data.startswith("select_channel_"):
                channel_id = data.replace("select_channel_", "")
                await self.show_channel_details(event, channel_id)
            elif data.startswith("edit_sources_"):
                channel_id = data.replace("edit_sources_", "")
                await self.start_edit_sources(event, channel_id)
            elif data.startswith("forward_mode_"):
                channel_id = data.replace("forward_mode_", "")
                await self.toggle_forward_mode(event, channel_id)
            elif data.startswith("delete_channel_"):
                channel_id = data.replace("delete_channel_", "")
                await self.confirm_delete_channel(event, channel_id)
            elif data.startswith("confirm_delete_"):
                channel_id = data.replace("confirm_delete_", "")
                await self.delete_channel(event, channel_id)
            elif data.startswith("add_source_"):
                channel_id = data.replace("add_source_", "")
                await self.start_add_single_source(event, channel_id)
            elif data.startswith("remove_source_"):
                channel_id = data.replace("remove_source_", "")
                await self.start_remove_single_source(event, channel_id)
            elif data.startswith("confirm_remove_source_"):
                parts = data.replace("confirm_remove_source_", "").split("_", 1)
                if len(parts) == 2:
                    channel_id, source_index = parts
                    await self.remove_source_by_index(event, channel_id, int(source_index))
            # معالجة أزرار الأدمن
            elif data.startswith("admin_"):
                if is_admin(user_id):
                    await self.handle_admin_callbacks(event, data)
                else:
                    await event.answer("⛔ ليس لديك صلاحية الوصول!", alert=True)
            # معالجة أزرار إدارة المحظورين والـ VIP
            elif data.startswith(("ban_", "vip_")):
                if is_admin(user_id):
                    if data.startswith("ban_"):
                        await self.handle_ban_callbacks(event, data)
                    elif data.startswith("vip_"):
                        await self.handle_vip_callbacks(event, data)
                else:
                    await event.answer("⛔ ليس لديك صلاحية الوصول!", alert=True)
            
            await event.answer()
            
        except Exception as e:
            print(f"خطأ في معالجة callback {data}: {e}")
            await event.answer("❌ حدث خطأ، يرجى المحاولة مرة أخرى", alert=True)

    # معالجة الرسائل النصية
    async def handle_message(self, event):
        user_id = event.sender_id
        message_text = event.message.text if event.message.text else "[رسالة بدون نص]"
        
        try:
            bot_logger.info(f"📨 رسالة جديدة من المستخدم {user_id}: {message_text[:50]}...")
            
            # تجاهل الرسائل من القنوات والمجموعات
            if event.is_channel or event.is_group:
                bot_logger.debug(f"🔇 تجاهل رسالة من قناة/مجموعة: {user_id}")
                return
            
            # تجاهل الأوامر
            if event.message.text and event.message.text.startswith('/'):
                bot_logger.debug(f"⚡ تجاهل أمر: {event.message.text} من {user_id}")
                return
                
            message = event.message.text
            
            if not message:
                bot_logger.debug(f"📝 رسالة فارغة من المستخدم {user_id}")
                return
            
            bot_logger.info(f"🔍 معالجة رسالة من المستخدم {user_id}: {message}")
            
            # معالجة العمليات المعلقة
            if user_id in self.pending_registrations:
                bot_logger.info(f"📱 معالجة إدخال رقم هاتف من المستخدم {user_id}")
                await self.handle_phone_input(event, message)
            elif user_id in self.pending_codes:
                bot_logger.info(f"🔢 معالجة كود التحقق من المستخدم {user_id}")
                await self.handle_code_input(event, message)
            elif user_id in self.pending_2fa:
                bot_logger.info(f"🔐 معالجة 2FA من المستخدم {user_id}")
                await self.handle_2fa_input(event, message)
            elif user_id in self.pending_inputs:
                bot_logger.info(f"🛡️ معالجة إدخال أدمن من المستخدم {user_id}")
                await self.handle_admin_input(event, message)
            elif user_id in self.pending_channel_operations:
                bot_logger.info(f"📋 معالجة عملية قناة من المستخدم {user_id}")
                await self.handle_channel_input(event, message)
            else:
                bot_logger.info(f"🤷 رسالة غير متوقعة من المستخدم {user_id}: {message}")
                
        except Exception as e:
            bot_logger.error(f"❌ خطأ في معالج الرسائل للمستخدم {user_id}: {e}")
            try:
                await event.respond("❌ حدث خطأ في معالجة الرسالة. يرجى المحاولة لاحقاً")
            except:
                bot_logger.error("❌ فشل في إرسال رسالة الخطأ للمستخدم")

    # بدء تسجيل المستخدم
    async def start_registration(self, event):
        user_id = event.sender_id
        
        if is_user_registered(user_id):
            await event.respond("✅ أنت مسجل بالفعل في النظام!")
            return
        
        await self.safe_edit_or_respond(event, 
            "📱 أرسل رقم هاتفك مع رمز البلد\n\n"
            "مثال: +96170400568\n"
            "أو: +201234567890\n\n"
            "💡 تأكد من كتابة الرقم صحيحاً"
        )
        
        self.pending_registrations[user_id] = {}

    async def handle_phone_input(self, event, phone):
        user_id = event.sender_id
        
        # التحقق من صحة رقم الهاتف
        is_valid, error_msg = self.validate_phone_number(phone)
        if not is_valid:
            await event.respond(f"❌ {error_msg}\n\nيرجى إرسال رقم صحيح:")
            return
        
        try:
            # إنشاء جلسة تليجرام جديدة
            temp_client = TelegramClient(StringSession(), self.api_id, self.api_hash or '')
            await temp_client.connect()
            
            # إرسال كود التحقق
            result = await temp_client.send_code_request(phone)
            
            self.pending_codes[user_id] = {
                'phone': phone,
                'phone_code_hash': result.phone_code_hash,
                'client': temp_client
            }
            
            # حذف من قائمة الانتظار للتسجيل
            if user_id in self.pending_registrations:
                del self.pending_registrations[user_id]
            
            await event.respond(
                f"📨 تم إرسال كود التحقق إلى {phone}\n\n"
                "📥 أرسل الكود المكون من 5 أرقام\n"
                "⏰ انتبه: الكود صالح لمدة محدودة"
            )
            
        except PhoneNumberInvalidError:
            await event.respond("❌ رقم الهاتف غير صحيح\nيرجى التأكد من الرقم وإعادة المحاولة")
        except FloodWaitError as e:
            time_str = self.format_time_arabic(e.seconds)
            await event.respond(f"⏳ تم المحاولة كثيراً\n\n🕐 يجب الانتظار: {time_str}")
        except Exception as e:
            await event.respond(f"❌ خطأ في إرسال الكود: {str(e)}")
            if user_id in self.pending_registrations:
                del self.pending_registrations[user_id]

    def validate_phone_number(self, phone):
        """تحقق من صحة رقم الهاتف"""
        if not phone:
            return False, "لم يتم إدخال رقم هاتف"
        
        # إزالة المسافات والرموز غير المرغوبة
        clean_phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        # التحقق من وجود رمز البلد
        if not clean_phone.startswith('+'):
            return False, "يجب أن يبدأ الرقم برمز البلد (مثل +96170400568)"
        
        # التحقق من الطول
        if len(clean_phone) < 10 or len(clean_phone) > 15:
            return False, "طول الرقم غير صحيح (يجب أن يكون بين 10-15 رقماً مع رمز البلد)"
        
        # التحقق من أن باقي الأرقام رقمية
        if not clean_phone[1:].isdigit():
            return False, "يجب أن يحتوي الرقم على أرقام فقط بعد رمز البلد"
        
        return True, ""

    def format_time_arabic(self, seconds):
        """تنسيق الوقت بالعربية"""
        if seconds < 60:
            return f"{seconds} ثانية"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} دقيقة"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours} ساعة و {minutes} دقيقة"

    async def handle_code_input(self, event, code):
        user_id = event.sender_id
        
        if user_id not in self.pending_codes:
            await event.respond("❌ لم يتم طلب كود تحقق. ابدأ من جديد.")
            return
        
        pending_data = self.pending_codes[user_id]
        client = pending_data['client']
        phone = pending_data['phone']
        phone_code_hash = pending_data['phone_code_hash']
        
        try:
            # محاولة تسجيل الدخول بالكود
            signed_in = await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            
            # الحصول على جلسة الـ string
            session_string = client.session.save()
            
            # حفظ المستخدم في قاعدة البيانات
            user_info = await client.get_me()
            add_user_to_db(
                user_id=user_id,
                username=user_info.username,
                first_name=user_info.first_name,
                phone_number=phone,
                session_string=session_string
            )
            
            await client.disconnect()
            
            # تنظيف البيانات المعلقة
            del self.pending_codes[user_id]
            
            await event.respond(
                "✅ تم تسجيلك بنجاح!\n\n"
                "🎉 يمكنك الآن استخدام جميع ميزات البوت\n"
                "⚙️ اضغط على الإعدادات لبدء إعداد قنواتك"
            )
            
            # إعادة عرض القائمة الرئيسية
            await asyncio.sleep(1)
            await self.handle_start(event)
            
        except SessionPasswordNeededError:
            # المستخدم يحتاج كلمة مرور التحقق بخطوتين
            self.pending_2fa[user_id] = pending_data
            del self.pending_codes[user_id]
            
            await event.respond(
                "🔐 حسابك محمي بالتحقق بخطوتين\n\n"
                "🔑 أرسل كلمة مرور التحقق بخطوتين"
            )
            
        except PhoneCodeInvalidError:
            await event.respond(
                "❌ الكود غير صحيح!\n\n"
                "💡 تأكد من:\n"
                "• كتابة الكود كاملاً (5 أرقام)\n"
                "• عدم انتهاء صلاحية الكود\n"
                "• عدم وجود مسافات\n\n"
                "🔄 أرسل الكود مرة أخرى"
            )
            
        except FloodWaitError as e:
            time_str = self.format_time_arabic(e.seconds)
            await event.respond(f"⏳ تم المحاولة كثيراً لإدخال الكود\n\n"
                              f"🕐 يجب الانتظار: {time_str}")
            
        except Exception as e:
            error_msg = str(e).lower()
            
            if "expired" in error_msg or "timeout" in error_msg:
                await event.respond("⏰ انتهت صلاحية الكود!\n\nيرجى بدء عملية التسجيل من جديد")
                await client.disconnect()
                del self.pending_codes[user_id]
            elif "invalid" in error_msg:
                await event.respond("❌ الكود غير صحيح. يرجى المحاولة مرة أخرى")
            else:
                await event.respond(f"❌ خطأ في التحقق من الكود: {str(e)}")

    async def handle_2fa_input(self, event, password):
        user_id = event.sender_id
        
        if user_id not in self.pending_2fa:
            await event.respond("❌ لم يتم طلب كلمة مرور التحقق بخطوتين")
            return
        
        pending_data = self.pending_2fa[user_id]
        client = pending_data['client']
        phone = pending_data['phone']
        
        try:
            # محاولة تسجيل الدخول بكلمة المرور
            signed_in = await client.sign_in(password=password)
            
            # الحصول على جلسة الـ string
            session_string = client.session.save()
            
            # حفظ المستخدم في قاعدة البيانات
            user_info = await client.get_me()
            add_user_to_db(
                user_id=user_id,
                username=user_info.username,
                first_name=user_info.first_name,
                phone_number=phone,
                session_string=session_string
            )
            
            await client.disconnect()
            
            # تنظيف البيانات المعلقة
            del self.pending_2fa[user_id]
            
            await event.respond(
                "✅ تم تسجيلك بنجاح!\n\n"
                "🎉 يمكنك الآن استخدام جميع ميزات البوت\n"
                "⚙️ اضغط على الإعدادات لبدء إعداد قنواتك"
            )
            
            # إعادة عرض القائمة الرئيسية
            await asyncio.sleep(1)
            await self.handle_start(event)
            
        except FloodWaitError as e:
            time_str = self.format_time_arabic(e.seconds)
            await event.respond(f"⏳ تم المحاولة كثيراً لإدخال كلمة المرور\n\n"
                              f"🕐 يجب الانتظار: {time_str}\n\n"
                              f"💡 لحماية حسابك من الاختراق")
            
        except Exception as e:
            error_msg = str(e).lower()
            
            if "password" in error_msg and "invalid" in error_msg:
                await event.respond("❌ كلمة مرور التحقق بخطوتين غير صحيحة!\n\n"
                                  "💡 تأكد من:\n"
                                  "• كتابة كلمة المرور الصحيحة\n"
                                  "• عدم وجود مسافات إضافية\n"
                                  "• أنها نفس كلمة المرور المحفوظة في حسابك\n\n"
                                  "🔄 يمكنك المحاولة مرة أخرى")
            else:
                await event.respond(f"❌ خطأ في التحقق من كلمة المرور: {str(e)}\n\n"
                                  "يرجى التأكد من صحة كلمة المرور وإعادة المحاولة")

    async def show_help(self, event):
        help_text = """
🤖 مساعدة البوت المطور

📱 لتسجيل رقم هاتفك:
- اضغط على "تسجيل رقم الهاتف"
- أدخل رقمك مع رمز البلد
- أدخل كود التحقق المرسل إليك

📺 لإضافة قناة جديدة:
- اضغط على "إضافة قناة"
- أرسل ID القناة أو اسم المستخدم
- ستتم إضافة القناة لقائمة قنواتك

📤 لإضافة مصادر لقناة:
- اضغط على "أرسل قنوات المصدر"
- اختر القناة المراد إعداد مصادر لها
- أرسل قنوات المصدر مفصولة بفاصلة

⚙️ للإعدادات:
- استخدم زر الإعدادات
- يمكنك إدارة قنواتك ومصادرها
- إعادة تشغيل نظام التحويل

✨ الميزات الجديدة:
- دعم قنوات متعددة
- إدارة منفصلة لمصادر كل قناة
- نظام تحويل محسن ومستقر
        """
        
        keyboard = [[Button.inline("🔙 العودة", b"start")]]
        await self.safe_edit_or_respond(event, help_text, buttons=keyboard)

    async def handle_start_callback(self, event):
        await self.handle_start(event)

    async def show_user_settings(self, event):
        """عرض إعدادات المستخدم مع الأزرار الجديدة"""
        user_id = event.sender_id
        channels = get_user_channels(user_id)
        
        settings_text = "⚙️ إعدادات المستخدم\n\n"
        settings_text += f"📊 عدد القنوات المضافة: {len(channels)}\n"
        
        if channels:
            active_channels = [ch for ch in channels if ch[3]]  # التي لديها مصادر
            settings_text += f"🔄 القنوات النشطة: {len(active_channels)}\n"
        
        keyboard = [
            [Button.inline("📺 إضافة قناة", b"add_channel")],
            [Button.inline("📤 أرسل قنوات المصدر", b"add_sources")],
            [Button.inline("📋 إدارة القنوات", b"my_channels")],
            [Button.inline("🔄 إعادة تشغيل التحويل", b"restart_forwarding")],
            [Button.inline("🔙 القائمة الرئيسية", b"start")]
        ]
        
        await self.safe_edit_or_respond(event, settings_text, buttons=keyboard)

    async def start_add_channel(self, event):
        """بدء إضافة قناة جديدة"""
        user_id = event.sender_id
        
        self.pending_channel_operations[user_id] = {
            'action': 'add_channel'
        }
        
        await self.safe_edit_or_respond(event,
            "📺 إضافة قناة جديدة\n\n"
            "أرسل معرف القناة أو اسم المستخدم:\n\n"
            "أمثلة:\n"
            "• @mychannel\n"
            "• -1001234567890\n"
            "• https://t.me/mychannel\n\n"
            "💡 تأكد أنك مدير في القناة أو لديك صلاحية الإرسال"
        )

    async def start_add_sources(self, event):
        """بدء إضافة مصادر لقناة"""
        user_id = event.sender_id
        channels = get_user_channels(user_id)
        
        if not channels:
            await self.safe_edit_or_respond(event,
                "❌ لا توجد قنوات مضافة\n\n"
                "يجب إضافة قناة أولاً باستخدام زر 'إضافة قناة'",
                buttons=[[Button.inline("🔙 العودة", b"user_settings")]]
            )
            return
        
        # عرض قائمة القنوات للاختيار
        text = "📤 اختر القناة لإضافة مصادر لها:\n\n"
        keyboard = []
        
        for i, (db_id, channel_id, channel_name, current_sources, forward_mode, created_at) in enumerate(channels):
            display_name = channel_name if channel_name else channel_id
            sources_count = len([s for s in current_sources.split(',') if s.strip()]) if current_sources else 0
            
            text += f"{i+1}. {display_name}\n"
            text += f"   📊 المصادر الحالية: {sources_count}\n\n"
            
            keyboard.append([Button.inline(f"📺 {display_name}", f"select_channel_{channel_id}")])
        
        keyboard.append([Button.inline("🔙 العودة", b"user_settings")])
        
        await self.safe_edit_or_respond(event, text, buttons=keyboard)

    async def show_channel_details(self, event, channel_id):
        """عرض تفاصيل قناة معينة"""
        user_id = event.sender_id
        channels = get_user_channels(user_id)
        
        # البحث عن القناة
        channel_data = None
        for ch in channels:
            if ch[1] == channel_id:  # channel_id is at index 1
                channel_data = ch
                break
        
        if not channel_data:
            await event.answer("❌ القناة غير موجودة", alert=True)
            return
        
        db_id, channel_id, channel_name, sources, forward_mode, created_at = channel_data
        display_name = channel_name if channel_name else channel_id
        
        text = f"📺 تفاصيل القناة: {display_name}\n\n"
        text += f"🆔 المعرف: {channel_id}\n"
        text += f"📅 تم الإضافة: {created_at[:10] if created_at else 'غير محدد'}\n"
        
        # عرض نوع التحويل
        mode_text = "مع ذكر المصدر" if forward_mode == "with_source" else "بدون ذكر المصدر"
        text += f"📋 نوع التحويل: {mode_text}\n\n"
        
        if sources and sources.strip():
            sources_list = [s.strip() for s in sources.split(',') if s.strip()]
            text += f"📤 المصادر ({len(sources_list)}):\n"
            for i, source in enumerate(sources_list, 1):
                text += f"{i}. {source}\n"
        else:
            text += "❌ لا توجد مصادر مضافة\n"
        
        # تحديد حالة التحويل
        forwarding_status = get_forwarding_status(user_id)
        if forwarding_status:
            is_active, last_activity, error_count = forwarding_status
            status_text = "🟢 نشط" if is_active else "🔴 متوقف"
            text += f"\n🔄 حالة التحويل: {status_text}\n"
            if error_count > 0:
                text += f"⚠️ عدد الأخطاء: {error_count}\n"
        
        keyboard = [
            [Button.inline("✏️ تعديل المصادر", f"edit_sources_{channel_id}")],
            [Button.inline("➕ إضافة مصدر", f"add_source_{channel_id}"), Button.inline("➖ حذف مصدر", f"remove_source_{channel_id}")],
            [Button.inline("📋 نوع التحويل", f"forward_mode_{channel_id}")],
            [Button.inline("🗑️ حذف القناة", f"delete_channel_{channel_id}")],
            [Button.inline("🔙 العودة", b"add_sources")]
        ]
        
        await self.safe_edit_or_respond(event, text, buttons=keyboard)

    async def start_edit_sources(self, event, channel_id):
        """بدء تعديل مصادر قناة"""
        user_id = event.sender_id
        
        self.pending_channel_operations[user_id] = {
            'action': 'edit_sources',
            'channel_id': channel_id
        }
        
        await self.safe_edit_or_respond(event,
            "📤 تحديث مصادر القناة\n\n"
            "أرسل قنوات المصدر الجديدة (مفصولة بفاصلة):\n\n"
            "أمثلة:\n"
            "• @source1, @source2, @source3\n"
            "• -1001111111111, -1002222222222\n"
            "• @news_channel, https://t.me/updates\n\n"
            "💡 سيتم استبدال المصادر الحالية بالجديدة"
        )

    async def start_add_single_source(self, event, channel_id):
        """بدء إضافة مصدر واحد لقناة"""
        user_id = event.sender_id
        
        self.pending_channel_operations[user_id] = {
            'action': 'add_single_source',
            'channel_id': channel_id
        }
        
        await self.safe_edit_or_respond(event,
            "➕ إضافة مصدر جديد\n\n"
            "أرسل معرف قناة المصدر الجديدة:\n\n"
            "أمثلة:\n"
            "• @news_channel\n"
            "• -1001111111111\n"
            "• https://t.me/updates\n\n"
            "💡 سيتم إضافة هذا المصدر للمصادر الحالية"
        )
    
    async def start_remove_single_source(self, event, channel_id):
        """بدء حذف مصدر واحد من قناة"""
        user_id = event.sender_id
        channels = get_user_channels(user_id)
        
        # البحث عن القناة
        channel_data = None
        for ch in channels:
            if ch[1] == channel_id:
                channel_data = ch
                break
        
        if not channel_data or not channel_data[3]:  # لا توجد مصادر
            await self.safe_edit_or_respond(event,
                "❌ لا توجد مصادر لحذفها من هذه القناة\n\n"
                "يجب إضافة مصادر أولاً",
                buttons=[[Button.inline("🔙 العودة", f"select_channel_{channel_id}")]]
            )
            return
        
        sources_list = [s.strip() for s in channel_data[3].split(',') if s.strip()]
        
        if not sources_list:
            await self.safe_edit_or_respond(event,
                "❌ لا توجد مصادر لحذفها من هذه القناة\n\n"
                "يجب إضافة مصادر أولاً",
                buttons=[[Button.inline("🔙 العودة", f"select_channel_{channel_id}")]]
            )
            return
        
        text = "➖ اختر المصدر المراد حذفه:\n\n"
        keyboard = []
        
        for i, source in enumerate(sources_list, 1):
            text += f"{i}. {source}\n"
            keyboard.append([Button.inline(f"🗑️ {source}", f"confirm_remove_source_{channel_id}_{i-1}")])
        
        keyboard.append([Button.inline("🔙 العودة", f"select_channel_{channel_id}")])
        
        await self.safe_edit_or_respond(event, text, buttons=keyboard)

    async def remove_source_by_index(self, event, channel_id, source_index):
        """حذف مصدر محدد بالفهرس"""
        user_id = event.sender_id
        channels = get_user_channels(user_id)
        
        # البحث عن القناة
        channel_data = None
        for ch in channels:
            if ch[1] == channel_id:
                channel_data = ch
                break
        
        if not channel_data:
            await event.answer("❌ القناة غير موجودة", alert=True)
            return
        
        sources_list = [s.strip() for s in channel_data[3].split(',') if s.strip()]
        
        if source_index >= len(sources_list):
            await event.answer("❌ المصدر غير موجود", alert=True)
            return
        
        removed_source = sources_list[source_index]
        sources_list.pop(source_index)
        
        # تحديث المصادر
        new_sources = ", ".join(sources_list)
        update_channel_sources(user_id, channel_id, new_sources)
        
        await event.answer(f"✅ تم حذف المصدر: {removed_source}", alert=True)
        
        # إعادة تشغيل نظام التحويل
        try:
            await self.message_forwarder.restart_forwarding()
        except Exception as e:
            print(f"خطأ في إعادة تشغيل النظام: {e}")
        
        # العودة لتفاصيل القناة
        await self.show_channel_details(event, channel_id)

    def fix_channel_id_format(self, channel_ids_text):
        """إصلاح تنسيق معرفات القنوات من الشكل العادي إلى الشكل الكامل"""
        if not channel_ids_text:
            return channel_ids_text
        
        import re
        
        # تقسيم المعرفات
        channel_ids = [id.strip() for id in channel_ids_text.split(',') if id.strip()]
        fixed_ids = []
        
        for channel_id in channel_ids:
            # تنظيف المعرف من الروابط
            if 't.me/' in channel_id:
                channel_id = channel_id.split('/')[-1].replace('@', '')
                if not channel_id.startswith('@'):
                    channel_id = '@' + channel_id
            
            # إذا كان المعرف رقماً عادياً بدون -100 في البداية
            if re.match(r'^\d{10,}$', channel_id):
                # إضافة -100 في البداية
                fixed_id = f"-100{channel_id}"
                fixed_ids.append(fixed_id)
            # إذا كان رقماً يبدأ بـ 1 (بدون ناقص)
            elif re.match(r'^1\d{12,}$', channel_id):
                fixed_id = f"-{channel_id}"
                fixed_ids.append(fixed_id)
            else:
                # المعرف صحيح بالفعل أو يحتوي على @
                fixed_ids.append(channel_id)
        
        return ", ".join(fixed_ids)

    async def confirm_delete_channel(self, event, channel_id):
        """تأكيد حذف القناة"""
        text = "⚠️ هل أنت متأكد من حذف هذه القناة؟\n\n"
        text += f"🗑️ سيتم حذف: {channel_id}\n"
        text += "📤 وجميع مصادرها المرتبطة\n\n"
        text += "❗ لا يمكن التراجع عن هذا الإجراء"
        
        keyboard = [
            [Button.inline("✅ نعم، احذف", f"confirm_delete_{channel_id}")],
            [Button.inline("❌ إلغاء", f"select_channel_{channel_id}")]
        ]
        
        await self.safe_edit_or_respond(event, text, buttons=keyboard)

    async def toggle_forward_mode(self, event, channel_id):
        """تبديل نوع التحويل للقناة"""
        user_id = event.sender_id
        channels = get_user_channels(user_id)
        
        # البحث عن القناة
        channel_data = None
        for ch in channels:
            if ch[1] == channel_id:
                channel_data = ch
                break
        
        if not channel_data:
            await event.answer("❌ القناة غير موجودة", alert=True)
            return
        
        # تبديل نوع التحويل
        current_mode = channel_data[4]  # forward_mode at index 4
        new_mode = "without_source" if current_mode == "with_source" else "with_source"
        
        try:
            update_channel_forward_mode(user_id, channel_id, new_mode)
            
            mode_text = "بدون ذكر المصدر" if new_mode == "without_source" else "مع ذكر المصدر"
            await event.answer(f"✅ تم تغيير نوع التحويل إلى: {mode_text}", alert=True)
            
            # إعادة تشغيل نظام التحويل
            try:
                await self.message_forwarder.restart_forwarding()
            except Exception as e:
                print(f"خطأ في إعادة تشغيل النظام: {e}")
            
            # إعادة عرض تفاصيل القناة
            await self.show_channel_details(event, channel_id)
            
        except Exception as e:
            await event.answer(f"❌ خطأ في تغيير نوع التحويل: {str(e)}", alert=True)

    async def delete_channel(self, event, channel_id):
        """حذف القناة نهائياً"""
        user_id = event.sender_id
        
        try:
            delete_user_channel(user_id, channel_id)
            
            await event.answer("✅ تم حذف القناة بنجاح", alert=True)
            
            # إعادة تشغيل نظام التحويل
            try:
                await self.message_forwarder.restart_forwarding()
                await event.respond("🔄 تم تحديث نظام التحويل")
            except Exception as e:
                await event.respond(f"⚠️ تم حذف القناة، لكن حدث خطأ في تحديث النظام: {str(e)}")
            
            # العودة لقائمة القنوات
            await self.show_my_channels(event)
            
        except Exception as e:
            await event.answer(f"❌ خطأ في حذف القناة: {str(e)}", alert=True)

    async def handle_channel_input(self, event, message):
        """معالجة إدخالات إدارة القنوات"""
        user_id = event.sender_id
        
        if user_id not in self.pending_channel_operations:
            return
        
        operation = self.pending_channel_operations[user_id]
        action = operation['action']
        
        try:
            if action == 'add_channel':
                # إضافة قناة جديدة
                channel_id = message.strip()
                
                # استخراج معرف القناة من الرابط إذا لزم الأمر
                if 't.me/' in channel_id:
                    channel_id = '@' + channel_id.split('/')[-1]
                
                # إصلاح تنسيق معرف القناة
                if not channel_id.startswith('@'):
                    channel_id = self.fix_channel_id_format(channel_id)
                
                # التحقق من صحة المعرف
                if not (channel_id.startswith('@') or channel_id.startswith('-100')):
                    await event.respond("❌ تنسيق معرف القناة غير صحيح\n\nيرجى استخدام:\n• @channel_name\n• -1001234567890\n• أو رقم القناة العادي (سيتم إصلاح التنسيق تلقائياً)")
                    return
                
                # إضافة القناة
                add_user_channel(user_id, channel_id, channel_id, "")
                
                await event.respond(f"✅ تم إضافة القناة بنجاح!\n\n📺 القناة: {channel_id}\n\n💡 يمكنك الآن إضافة مصادر لها")
                
                # العودة للإعدادات
                await asyncio.sleep(1)
                await self.show_user_settings(event)
                
            elif action == 'edit_sources':
                # تحديث مصادر القناة
                channel_id = operation['channel_id']
                sources = message.strip()
                
                # إصلاح تنسيق معرفات القنوات
                sources = self.fix_channel_id_format(sources)
                
                # تحديث المصادر
                update_channel_sources(user_id, channel_id, sources)
                
                await event.respond(f"✅ تم تحديث مصادر القناة بنجاح!\n\n📺 القناة: {channel_id}\n📤 المصادر: {sources}")
                
                # إعادة تشغيل نظام التحويل
                try:
                    await self.message_forwarder.restart_forwarding()
                    
                    # حساب الإحصائيات
                    active_sessions = len(self.message_forwarder.clients)
                    total_sources = sum(len(mapping['sources']) for mapping in self.message_forwarder.forward_mappings.values())
                    
                    await event.respond(
                        f"🔄 تم تحديث نظام التحويل!\n"
                        f"📊 الجلسات النشطة: {active_sessions}\n"
                        f"📤 إجمالي القنوات المراقبة: {total_sources}"
                    )
                    
                except Exception as e:
                    await event.respond(f"⚠️ تم تحديث المصادر، لكن حدث خطأ في نظام التحويل: {str(e)}")
                
                # العودة لتفاصيل القناة
                await asyncio.sleep(2)
                await self.show_channel_details(event, channel_id)
                
            elif action == 'add_single_source':
                # إضافة مصدر واحد
                channel_id = operation['channel_id']
                new_source = message.strip()
                
                # إصلاح تنسيق معرف المصدر
                new_source = self.fix_channel_id_format(new_source) if not new_source.startswith('@') else new_source
                
                # الحصول على المصادر الحالية
                channels = get_user_channels(user_id)
                current_sources = ""
                for ch in channels:
                    if ch[1] == channel_id:
                        current_sources = ch[3] or ""
                        break
                
                # إضافة المصدر الجديد
                if current_sources:
                    new_sources = f"{current_sources}, {new_source}"
                else:
                    new_sources = new_source
                
                update_channel_sources(user_id, channel_id, new_sources)
                await event.respond(f"✅ تم إضافة المصدر بنجاح!\n\n📺 القناة: {channel_id}\n📤 المصدر الجديد: {new_source}")
                
                # إعادة تشغيل نظام التحويل
                try:
                    await self.message_forwarder.restart_forwarding()
                    await event.respond("🔄 تم تحديث نظام التحويل")
                except Exception as e:
                    await event.respond(f"⚠️ تم إضافة المصدر، لكن حدث خطأ في تحديث النظام: {str(e)}")
                
                # العودة لتفاصيل القناة
                await asyncio.sleep(1)
                await self.show_channel_details(event, channel_id)
                
        except Exception as e:
            await event.respond(f"❌ خطأ: {str(e)}")
        
        # تنظيف العملية المعلقة
        if user_id in self.pending_channel_operations:
            del self.pending_channel_operations[user_id]

    async def show_my_channels(self, event):
        """عرض قنوات المستخدم مع إدارة محسنة"""
        user_id = event.sender_id
        channels = get_user_channels(user_id)
        
        if not channels:
            message = "📋 لا توجد قنوات مضافة\n\n"
            message += "💡 استخدم 'إضافة قناة' لإضافة قناة جديدة"
            
            keyboard = [
                [Button.inline("📺 إضافة قناة", b"add_channel")],
                [Button.inline("🔙 العودة", b"user_settings")]
            ]
        else:
            message = f"📋 قنواتك ({len(channels)}):\n\n"
            
            keyboard = []
            for i, (_, channel_id, channel_name, sources, forward_mode, created_at) in enumerate(channels, 1):
                display_name = channel_name if channel_name else channel_id
                sources_count = len([s for s in sources.split(',') if s.strip()]) if sources else 0
                
                status_icon = "🟢" if sources_count > 0 else "⚪"
                message += f"{status_icon} {i}. {display_name}\n"
                message += f"   📊 المصادر: {sources_count}\n"
                message += f"   📅 {created_at[:10] if created_at else 'غير محدد'}\n\n"
                
                keyboard.append([Button.inline(f"📺 {display_name}", f"select_channel_{channel_id}")])
            
            # حالة التحويل العامة
            forwarding_status = get_forwarding_status(user_id)
            if forwarding_status:
                is_active, last_activity, error_count = forwarding_status
                status_text = "🟢 نشط" if is_active else "🔴 متوقف"
                message += f"🔄 حالة التحويل: {status_text}\n"
                if last_activity:
                    message += f"🕐 آخر نشاط: {last_activity[:16].replace('T', ' ')}\n"
            
            keyboard.extend([
                [Button.inline("📺 إضافة قناة", b"add_channel"), Button.inline("📤 إضافة مصادر", b"add_sources")],
                [Button.inline("🔄 إعادة تشغيل التحويل", b"restart_forwarding")],
                [Button.inline("🔙 العودة", b"user_settings")]
            ])
        
        await self.safe_edit_or_respond(event, message, buttons=keyboard)

    async def restart_message_forwarding(self, event):
        """إعادة تشغيل نظام تحويل الرسائل"""
        try:
            await event.answer("🔄 جارٍ إعادة تشغيل نظام التحويل...", alert=True)
            
            # إعادة تشغيل النظام
            await self.message_forwarder.restart_forwarding()
            
            # حساب الإحصائيات
            active_sessions = len(self.message_forwarder.clients)
            total_mappings = len(self.message_forwarder.forward_mappings)
            total_sources = sum(len(mapping['sources']) for mapping in self.message_forwarder.forward_mappings.values())
            
            result_text = "✅ تم إعادة تشغيل نظام التحويل بنجاح!\n\n"
            result_text += f"📊 الإحصائيات:\n"
            result_text += f"👥 الجلسات النشطة: {active_sessions}\n"
            result_text += f"📺 القنوات المضافة: {total_mappings}\n"
            result_text += f"📤 قنوات المصدر المراقبة: {total_sources}\n\n"
            
            if active_sessions > 0:
                result_text += "🟢 النظام يعمل بشكل طبيعي"
            else:
                result_text += "⚠️ لا توجد جلسات نشطة - تحقق من إعدادات القنوات"
            
            await event.respond(result_text)
            
        except Exception as e:
            await event.respond(f"❌ خطأ في إعادة تشغيل النظام: {str(e)}")
            print(f"خطأ تفصيلي في restart_message_forwarding: {e}")

    # معالجة أوامر الأدمن (نسخ من الكود الأصلي مع التحسينات)
    async def handle_admin(self, event):
        user_id = event.sender_id
        
        if not is_admin(user_id):
            await event.respond("⛔ ليس لديك صلاحية الوصول لهذا الأمر")
            return
        
        await self.show_admin_menu(event)

    async def handle_settings(self, event):
        user_id = event.sender_id
        
        if not is_user_registered(user_id):
            await event.respond("❌ يجب تسجيل رقم هاتفك أولاً\nاستخدم /start للبدء")
            return
        
        await self.show_user_settings(event)

    async def handle_help(self, event):
        await self.show_help(event)

    async def handle_login(self, event):
        """تسجيل دخول جديد في حال حذف الجلسة"""
        user_id = event.sender_id
        
        # حذف الجلسة الحالية من قاعدة البيانات
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET session_string = '', is_verified = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        await event.respond(
            "🔄 تم مسح جلستك السابقة بنجاح!\n\n"
            "📱 الآن يمكنك إعادة تسجيل رقم هاتفك\n"
            "اضغط على الزر أدناه للبدء:",
            buttons=[[Button.inline("📱 تسجيل رقم الهاتف", b"register_phone")]]
        )

    async def show_admin_menu(self, event):
        keyboard = [
            [Button.inline("👥 إدارة المستخدمين", b"admin_users"), Button.inline("🚫 إدارة المحظورين", b"admin_bans")],
            [Button.inline("👑 إدارة VIP", b"admin_vip"), Button.inline("🛡️ إدارة الأدمن", b"admin_admins")],
            [Button.inline("🤖 إعدادات البوت", b"admin_bot_settings")],
            [Button.inline("🔄 إحصائيات التحويل", b"admin_forwarding_stats")],
            [Button.inline("🔙 القائمة الرئيسية", b"start")]
        ]
        
        await self.safe_edit_or_respond(event, "🛡️ لوحة التحكم الإدارية\nاختر العملية المطلوبة:", buttons=keyboard)

    # باقي دوال الأدمن (نسخ من الكود الأصلي)
    async def handle_admin_callbacks(self, event, data):
        print(f"Admin callback: {data}")
        
        if data == "admin_users":
            await self.show_user_management(event)
        elif data == "admin_bans":
            await self.show_ban_management(event)
        elif data == "admin_vip":
            await self.show_vip_management(event)
        elif data == "admin_admins":
            await self.show_admin_management(event)
        elif data == "admin_bot_settings":
            await self.show_bot_settings(event)
        elif data == "admin_forwarding_stats":
            await self.show_forwarding_stats(event)
        elif data == "admin_toggle_bot":
            await self.handle_toggle_bot(event)
        elif data == "admin_bot_message":
            self.pending_inputs[event.sender_id] = {'action': 'bot_message'}
            await self.safe_edit_or_respond(event, "📝 أرسل رسالة التوقف الجديدة:")
        elif data == "admin_add":
            self.pending_inputs[event.sender_id] = {'action': 'add_admin'}
            await self.safe_edit_or_respond(event, "➕ أرسل ID المستخدم المراد إضافته كأدمن:")
        elif data == "admin_remove":
            self.pending_inputs[event.sender_id] = {'action': 'remove_admin'}
            await self.safe_edit_or_respond(event, "➖ أرسل ID الأدمن المراد حذفه:")
        elif data == "admin_list":
            await self.show_admins_list(event)
        elif data == "admin_remove_all":
            remove_all_admins()
            await event.answer("✅ تم حذف جميع الأدمن عدا المدير الأعلى!", alert=True)

    async def show_forwarding_stats(self, event):
        """عرض إحصائيات التحويل للأدمن"""
        try:
            # إحصائيات نظام التحويل
            active_sessions = len(self.message_forwarder.clients)
            total_mappings = len(self.message_forwarder.forward_mappings)
            total_sources = sum(len(mapping['sources']) for mapping in self.message_forwarder.forward_mappings.values())
            
            # إحصائيات قاعدة البيانات
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM user_channels WHERE is_active = 1")
            total_channels = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM user_channels WHERE is_active = 1 AND source_channels != ''")
            active_channels = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM user_channels WHERE is_active = 1")
            users_with_channels = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM forwarding_status WHERE is_active = 1")
            active_forwarding_users = cursor.fetchone()[0]
            
            conn.close()
            
            stats_text = "📊 إحصائيات نظام التحويل\n\n"
            stats_text += f"🤖 النظام:\n"
            stats_text += f"• الجلسات النشطة: {active_sessions}\n"
            stats_text += f"• مسارات التحويل: {total_mappings}\n"
            stats_text += f"• قنوات المصدر المراقبة: {total_sources}\n\n"
            
            stats_text += f"📺 القنوات:\n"
            stats_text += f"• إجمالي القنوات: {total_channels}\n"
            stats_text += f"• القنوات النشطة: {active_channels}\n"
            stats_text += f"• المستخدمون: {users_with_channels}\n\n"
            
            stats_text += f"🔄 التحويل:\n"
            stats_text += f"• المستخدمون النشطون: {active_forwarding_users}\n"
            
            if active_sessions > 0:
                stats_text += f"\n🟢 النظام يعمل بشكل طبيعي"
            else:
                stats_text += f"\n🔴 النظام متوقف أو لا توجد جلسات نشطة"
            
            keyboard = [
                [Button.inline("🔄 إعادة تشغيل النظام", b"admin_restart_forwarding")],
                [Button.inline("🔙 العودة", b"admin_menu")]
            ]
            
            await self.safe_edit_or_respond(event, stats_text, buttons=keyboard)
            
        except Exception as e:
            await event.respond(f"❌ خطأ في جلب الإحصائيات: {str(e)}")

    # دوال الأدمن الأخرى (نسخ مبسط من الكود الأصلي)
    async def show_user_management(self, event):
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_verified = 1")
        registered_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM vip_users WHERE is_active = 1")
        vip_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM banned_users WHERE is_active = 1")
        banned_users = cursor.fetchone()[0]
        
        conn.close()
        
        stats_text = "📊 إحصائيات المستخدمين\n\n"
        stats_text += f"👥 إجمالي المستخدمين: {total_users}\n"
        stats_text += f"✅ المسجلين: {registered_users}\n"
        stats_text += f"👑 VIP: {vip_users}\n"
        stats_text += f"🚫 المحظورين: {banned_users}\n"
        
        keyboard = [[Button.inline("🔙 العودة", b"admin_menu")]]
        await self.safe_edit_or_respond(event, stats_text, buttons=keyboard)

    async def show_ban_management(self, event):
        keyboard = [
            [Button.inline("🚫 حظر مستخدم بالID", b"ban_user_id"), Button.inline("✅ فك حظر بالID", b"unban_user_id")],
            [Button.inline("📋 قائمة المحظورين", b"ban_list"), Button.inline("🆓 فك حظر الجميع", b"unban_all")],
            [Button.inline("🔙 العودة", b"admin_menu")]
        ]
        
        await self.safe_edit_or_respond(event, "🚫 إدارة المحظورين\nاختر العملية المطلوبة:", buttons=keyboard)

    async def show_vip_management(self, event):
        keyboard = [
            [Button.inline("👑 إضافة VIP", b"vip_add"), Button.inline("❌ حذف VIP", b"vip_remove")],
            [Button.inline("📋 قائمة VIP", b"vip_list")],
            [Button.inline("🔙 العودة", b"admin_menu")]
        ]
        
        await self.safe_edit_or_respond(event, "👑 إدارة العضوية المميزة\nاختر العملية المطلوبة:", buttons=keyboard)

    async def show_admin_management(self, event):
        if not is_super_admin(event.sender_id):
            await event.answer("⛔ هذه الميزة للمدير الأعلى فقط!", alert=True)
            return
        
        keyboard = [
            [Button.inline("➕ إضافة أدمن", b"admin_add"), Button.inline("➖ حذف أدمن", b"admin_remove")],
            [Button.inline("📋 قائمة الأدمن", b"admin_list"), Button.inline("🗑️ حذف جميع الأدمن", b"admin_remove_all")],
            [Button.inline("🔙 العودة", b"admin_menu")]
        ]
        
        await self.safe_edit_or_respond(event, "🛡️ إدارة المديرين\nاختر العملية المطلوبة:", buttons=keyboard)

    async def show_bot_settings(self, event):
        bot_status, status_message = get_bot_status()
        status_text = "🟢 نشط" if bot_status == "active" else "🔴 متوقف"
        
        keyboard = [
            [Button.inline("🔄 تغيير حالة البوت", b"admin_toggle_bot")],
            [Button.inline("📝 تعديل رسالة التوقف", b"admin_bot_message")],
            [Button.inline("🔙 العودة", b"admin_menu")]
        ]
        
        message_text = f"🤖 إعدادات البوت\n\nالحالة الحالية: {status_text}"
        if status_message:
            message_text += f"\n\nرسالة التوقف:\n{status_message}"
        
        await self.safe_edit_or_respond(event, message_text, buttons=keyboard)

    async def handle_ban_callbacks(self, event, data):
        if data == "ban_user_id":
            self.pending_inputs[event.sender_id] = {'action': 'ban_user'}
            await self.safe_edit_or_respond(event, "🚫 أرسل ID المستخدم المراد حظره:")
        elif data == "unban_user_id":
            self.pending_inputs[event.sender_id] = {'action': 'unban_user'}
            await self.safe_edit_or_respond(event, "✅ أرسل ID المستخدم المراد فك حظره:")
        elif data == "ban_list":
            await self.show_banned_users_list(event)
        elif data == "unban_all":
            unban_all_users()
            await event.answer("✅ تم فك حظر جميع المستخدمين!", alert=True)

    async def show_banned_users_list(self, event):
        banned_users = get_banned_users()
        
        if not banned_users:
            message = "✅ لا يوجد مستخدمون محظورون حالياً"
        else:
            message = "🚫 قائمة المحظورين:\n\n"
            for user in banned_users:
                user_id, ban_expires, first_name, username = user
                user_link = f"tg://openmessage?user_id={user_id}"
                name = first_name or "Unknown"
                if username:
                    name += f" (@{username})"
                
                message += f"👤 [{name}]({user_link})\n"
                if ban_expires:
                    message += f"⏰ ينتهي: {ban_expires[:10]}\n"
                else:
                    message += "⏰ دائم\n"
                message += "\n"
        
        keyboard = [[Button.inline("🔙 العودة", b"admin_bans")]]
        await self.safe_edit_or_respond(event, message, buttons=keyboard, parse_mode='md')

    async def handle_vip_callbacks(self, event, data):
        if data == "vip_add":
            self.pending_inputs[event.sender_id] = {'action': 'add_vip'}
            await self.safe_edit_or_respond(event, "👑 أرسل ID المستخدم وعدد الأيام:\nمثال: 123456789 30")
        elif data == "vip_remove":
            self.pending_inputs[event.sender_id] = {'action': 'remove_vip'}
            await self.safe_edit_or_respond(event, "❌ أرسل ID المستخدم المراد حذفه من VIP:")
        elif data == "vip_list":
            await self.show_vip_users_list(event)

    async def show_vip_users_list(self, event):
        vip_users = get_vip_users()
        
        if not vip_users:
            message = "📋 لا يوجد مستخدمون VIP حالياً"
        else:
            message = "👑 قائمة العضوية المميزة:\n\n"
            for user in vip_users:
                user_id, end_date, first_name, username = user
                user_link = f"tg://openmessage?user_id={user_id}"
                name = first_name or "Unknown"
                if username:
                    name += f" (@{username})"
                
                end_dt = datetime.fromisoformat(end_date)
                days_remaining = (end_dt - datetime.now()).days
                
                message += f"👤 [{name}]({user_link})\n"
                message += f"⏰ ينتهي: {end_date[:10]}\n"
                message += f"📊 الأيام المتبقية: {max(0, days_remaining)} يوم\n\n"
        
        keyboard = [[Button.inline("🔙 العودة", b"admin_vip")]]
        await self.safe_edit_or_respond(event, message, buttons=keyboard, parse_mode='md')

    async def handle_admin_input(self, event, message):
        user_id = event.sender_id
        
        if user_id not in self.pending_inputs:
            return
        
        action = self.pending_inputs[user_id]['action']
        
        try:
            if action == 'ban_user':
                target_user_id = int(message)
                ban_user(target_user_id, days=1)
                await event.respond(f"✅ تم حظر المستخدم {target_user_id} لمدة يوم واحد")
                
            elif action == 'unban_user':
                target_user_id = int(message)
                unban_user(target_user_id)
                await event.respond(f"✅ تم فك حظر المستخدم {target_user_id}")
                
            elif action == 'add_vip':
                parts = message.split()
                if len(parts) != 2:
                    await event.respond("❌ الرجاء إدخال: USER_ID DAYS\nمثال: 123456789 30")
                else:
                    target_user_id = int(parts[0])
                    days = int(parts[1])
                    add_vip_user(target_user_id, days)
                    await event.respond(f"✅ تم إضافة المستخدم {target_user_id} إلى VIP لمدة {days} يوم")
                    
            elif action == 'remove_vip':
                target_user_id = int(message)
                remove_vip_user(target_user_id)
                await event.respond(f"✅ تم حذف المستخدم {target_user_id} من VIP")
                
            elif action == 'add_admin':
                target_user_id = int(message)
                add_admin(target_user_id)
                await event.respond(f"✅ تم إضافة المستخدم {target_user_id} كأدمن")
                
            elif action == 'remove_admin':
                target_user_id = int(message)
                if remove_admin(target_user_id):
                    await event.respond(f"✅ تم حذف المستخدم {target_user_id} من الأدمن")
                else:
                    await event.respond("❌ لا يمكن حذف المدير الأعلى")
                    
            elif action == 'bot_message':
                set_bot_status("inactive", message)
                await event.respond(f"✅ تم تحديث رسالة توقف البوت:\n{message}")
                
        except ValueError:
            await event.respond("❌ الرجاء إدخال قيم صحيحة")
        except Exception as e:
            await event.respond(f"❌ خطأ: {str(e)}")
        
        if user_id in self.pending_inputs:
            del self.pending_inputs[user_id]

    async def handle_toggle_bot(self, event):
        bot_status, _ = get_bot_status()
        new_status = "inactive" if bot_status == "active" else "active"
        set_bot_status(new_status)
        
        status_text = "🟢 نشط" if new_status == "active" else "🔴 متوقف"
        await event.answer(f"✅ تم تغيير حالة البوت إلى: {status_text}", alert=True)
        
        await self.show_bot_settings(event)

    async def show_admins_list(self, event):
        admins = get_admins()
        
        if not admins:
            message = "📋 لا يوجد أدمن حالياً"
        else:
            message = "🛡️ قائمة المديرين:\n\n"
            for admin in admins:
                user_id, permissions, first_name, username = admin
                user_link = f"tg://openmessage?user_id={user_id}"
                name = first_name or "Unknown"
                if username:
                    name += f" (@{username})"
                
                if user_id == 7124431342:
                    message += f"👑 [{name}]({user_link})\nالصلاحية: مدير أعلى\n\n"
                else:
                    message += f"🛡️ [{name}]({user_link})\nالصلاحية: {permissions}\n\n"
        
        keyboard = [[Button.inline("🔙 العودة", b"admin_admins")]]
        await self.safe_edit_or_respond(event, message, buttons=keyboard, parse_mode='md')

async def main():
    try:
        bot_logger.info("🚀 تشغيل التطبيق الرئيسي...")
        bot_logger.info(f"🔧 Python version: {asyncio.get_event_loop()}")
        
        bot = TelegramBot()
        bot_logger.info("✅ تم إنشاء كائن البوت بنجاح")
        
        await bot.start_bot()
        
    except KeyboardInterrupt:
        bot_logger.info("🛑 تم إيقاف البوت بواسطة المستخدم")
    except Exception as e:
        bot_logger.critical(f"💥 خطأ حرج في التطبيق الرئيسي: {e}")
        print(f"❌ خطأ حرج: {e}")
        raise

if __name__ == "__main__":
    print("🤖 بدء تشغيل بوت التليغرام...")
    print("📝 تفعيل نظام تسجيل شامل للأخطاء...")
    bot_logger.info("🎬 بداية تشغيل البوت")
    asyncio.run(main())
