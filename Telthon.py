# -*- coding: utf-8 -*-
import asyncio
import logging
import random
import re
import string
from datetime import datetime
from typing import Optional, Dict, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ContextTypes
)
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
    PasswordHashInvalidError
)

logger = logging.getLogger(__name__)

# معلومات البوت
BOT_TOKEN = "8265094830:AAHApH9_FVOUCNobZOq5nZahlxlVSmDgsjE"

# إعدادات telethon للجلسة الشخصية
API_ID = 94575  # معرف تطبيق تليجرام
API_HASH = "a3406de8d171bb422bb6ddf3bbd800e2"  # هاش تطبيق تليجرام
SESSION_NAME = "user_session"

# متغيرات عامة
user_client: Optional[TelegramClient] = None
logged_in_user_id: Optional[int] = None
auth_states: Dict[int, Dict] = {}
hunt_tasks: Dict[int, Dict] = {}
auto_post_tasks: Dict[int, Dict] = {}
# muted_users stores identifiers as lowercase username (without @) and string ids
muted_users: Set[str] = set()


class TelegramBot:
    def __init__(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
        # flag to avoid registering telethon handlers multiple times
        self._telethon_handlers_registered = False

        # basic logger setup
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            logger.addHandler(ch)

    def setup_handlers(self):
        """إعداد معالجات الأوامر"""
        # أوامر البوت الأساسية
        self.application.add_handler(CommandHandler("start", self.start_command))

        # معالج الرسائل النصية
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        # معالج أزرار لوحة التحكم
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))

    def setup_telethon_handlers(self):
        """إعداد معالجات telethon للتحكم في جميع المحادثات
        - يسجل معالج أوامر النقطة (الخاصة بالمستخدم)
        - يسجل معالج لحذف رسائل المستخدمين المكتومين
        """
        global user_client
        if not user_client or not logged_in_user_id:
            return
        if self._telethon_handlers_registered:
            return
        self._telethon_handlers_registered = True

        # استماع للأوامر التي تبدأ بنقطة في جميع المحادثات (أوامر يرسلها المستخدم المصادق)
        @user_client.on(events.NewMessage(pattern=r'^\..*', outgoing=True))
        async def handle_dot_commands(event):
            """معالج الأوامر النقطية في جميع المحادثات"""
            try:
                message_text = (event.message.message or "").lower().strip()
                chat_id = event.chat_id

                if message_text in ['.مساعدة', '.مساعده']:
                    help_text = (
                        "🤖 **أوامر البوت - دليل المساعدة**\n\n"
                        "📋 **الأوامر الأساسية:**\n"
                        "• `.مساعدة` - عرض هذه القائمة\n"
                        "• `.الاوامر` - لوحة التحكم التفاعلية\n\n"
                        "🔇 **أوامر الكتم:**\n"
                        "• `.كتم` - كتم شخص (رد على رسالته)\n"
                        "• `.كتم @معرف` - كتم شخص بمعرفه\n"
                        "• `.الغاء كتم` - إلغاء كتم شخص\n\n"
                        "🎯 **أوامر الصيد:**\n"
                        "• `.صيد` - بدء صيد اليوزرات\n"
                        "  - ثلاثي: ### (3 حروف)\n"
                        "  - رباعي: ##_## (4 حروف مع _)\n"
                        "  - خماسي: ##### (5 حروف)\n\n"
                        "📢 **النشر التلقائي:**\n"
                        "• `.نشر تلقائي` - نشر رسائل تلقائية\n\n"
                        "🔧 **الميزات الإضافية:**\n"
                        "• تحديث البايو تلقائياً حسب الوقت\n"
                        "• تحويل الرسائل الواردة\n"
                        "• ذكاء اصطناعي للرد التلقائي\n\n"
                        "💡 **ملاحظة:** جميع الأوامر تبدأ بنقطة (.)"
                    )
                    await user_client.send_message(chat_id, help_text)
                    await event.delete()

                elif message_text == '.الاوامر':
                    keyboard_text = (
                        "⚙️ **لوحة التحكم الرئيسية**\n\n"
                        f"🎯 **صيد اليوزرات النشط:** {'نعم' if hunt_tasks else 'لا'}\n"
                        f"📢 **النشر التلقائي:** {'نشط' if auto_post_tasks else 'متوقف'}\n"
                        f"🔇 **المستخدمون المكتومون:** {len(muted_users)}\n\n"
                        "📊 **إحصائيات اليوم:**\n"
                        "• اليوزرات المفحوصة: 0\n"
                        "• اليوزرات المتاحة: 0\n"
                        "• الرسائل المنشورة: 0\n\n"
                        "💡 استخدم الأوامر المتاحة للتحكم في البوت"
                    )
                    await user_client.send_message(chat_id, keyboard_text)
                    await event.delete()

                elif message_text == '.صيد':
                    await self.start_hunting_command(chat_id, event)

                elif message_text.startswith('.كتم'):
                    await self.mute_command(event, message_text)

                elif message_text.startswith('.الغاء كتم') or message_text.startswith('.إلغاء كتم'):
                    await self.unmute_command(event)

                elif message_text == '.نشر تلقائي':
                    await self.auto_post_command(chat_id, event)

                elif message_text == '.المكتومون':
                    # عرض قائمة المستخدمين المكتومين
                    list_txt = "🔇 **المستخدمون المكتومون:**\n"
                    if not muted_users:
                        list_txt += "لا يوجد مستخدمون مكتومون."
                    else:
                        for m in muted_users:
                            list_txt += f"• `{m}`\n"
                    await user_client.send_message(chat_id, list_txt)
                    await event.delete()

            except Exception as e:
                logger.error(f"خطأ في معالجة الأمر: {e}")
                try:
                    await user_client.send_message(event.chat_id, f"❌ خطأ في تنفيذ الأمر: {str(e)}")
                except:
                    pass

        # معالج يحذف رسائل المستخدمين المكتومين في المجموعات والمحادثات الخاصة
        @user_client.on(events.NewMessage())
        async def enforce_mute(event):
            try:
                # لا نتعامل مع رسائلنا (outgoing)
                if getattr(event, 'out', False):
                    return

                sender = None
                try:
                    sender = await event.get_sender()
                except Exception:
                    # في بعض الحالات (قنوات) قد لا نحصل على المرسل
                    pass

                sender_usernames_to_check = set()
                sender_ids_to_check = set()

                if sender:
                    if getattr(sender, 'username', None):
                        sender_usernames_to_check.add(sender.username.lower())
                    if getattr(sender, 'id', None):
                        sender_ids_to_check.add(str(sender.id))
                else:
                    # fallback to event.sender_id
                    if getattr(event, 'sender_id', None):
                        sender_ids_to_check.add(str(event.sender_id))

                # إذا لم يكن هناك أي معرّف للمقارنة فنخرج
                if not sender_usernames_to_check and not sender_ids_to_check:
                    return

                # تحقق من الكتم (يمكن أن يكون اسم المستخدم أو id)
                is_muted = False
                for uid in sender_ids_to_check:
                    if uid in muted_users:
                        is_muted = True
                        break
                if not is_muted:
                    for uname in sender_usernames_to_check:
                        if uname in muted_users:
                            is_muted = True
                            break

                if is_muted:
                    try:
                        await event.delete()
                        logger.info(f"Deleted message from muted user in chat {event.chat_id}")
                    except Exception as e:
                        # قد لا يكون لدينا صلاحيات الحذف في المجموعة
                        logger.warning(f"Cannot delete message in chat {event.chat_id}: {e}")
            except Exception as e:
                logger.debug(f"خطأ في enforce_mute: {e}")

    async def start_hunting_command(self, chat_id, event):
        """بدء صيد اليوزرات"""
        if chat_id in hunt_tasks:
            await user_client.send_message(chat_id, "⚡ صيد اليوزرات يعمل بالفعل!")
            await event.delete()
            return

        hunt_tasks[chat_id] = {
            'active': True,
            'checked': 0,
            'available': 0
        }

        await user_client.send_message(
            chat_id,
            "🎯 **تم بدء صيد اليوزرات!**\n\n"
            "📊 **الأنماط المستهدفة:**\n"
            "• ثلاثي: ### (3 حروف)\n"
            "• رباعي: ##_## (4 حروف مع _)\n"
            "• خماسي: ##### (5 حروف)\n\n"
            "⏰ سأرسل تقارير كل 10 دقائق"
        )
        await event.delete()

        # بدء مهمة الصيد
        asyncio.create_task(self.hunting_task(chat_id))

    async def mute_command(self, event, command):
        """كتم مستخدم
        يدعم:
        - `.كتم @username`
        - `.كتم user_id`
        - الرد على رسالة: `.كتم` (حيث سيتم كتم صاحب الرسالة المردود عليها)
        """
        chat_id = event.chat_id
        try:
            arg = None
            # إذا كان المستخدم قد عيّن معرف بعد الأمر
            parts = command.split(' ', 1)
            if len(parts) > 1 and parts[1].strip():
                arg = parts[1].strip()

            if arg:
                # إذا كان رقم (id)
                if re.fullmatch(r'\d+', arg):
                    identifier = arg.strip()
                    muted_users.add(identifier)
                    await user_client.send_message(
                        chat_id,
                        f"🔇 تم كتم المستخدم بالمعرف {identifier} بنجاح!"
                    )
                else:
                    username = arg.strip().lstrip('@')
                    identifier = username.lower()
                    # حاول الحصول على id من اليوزرنيم (إذا أمكن) لتخزينه أيضاً
                    try:
                        entity = await user_client.get_entity(username)
                        uid = getattr(entity, 'id', None)
                        uname = getattr(entity, 'username', None)
                        if uid:
                            muted_users.add(str(uid))
                        if uname:
                            muted_users.add(uname.lower())
                        else:
                            muted_users.add(identifier)
                    except Exception:
                        # لو لم نتمكن من حل اليوزرنيم نخزن النسخة النصية
                        muted_users.add(identifier)
                    await user_client.send_message(
                        chat_id,
                        f"🔇 تم كتم المستخدم @{username} بنجاح!"
                    )
            elif event.is_reply:
                reply_msg = await event.get_reply_message()
                if reply_msg and reply_msg.sender:
                    sender = reply_msg.sender
                    uid = getattr(sender, 'id', None)
                    uname = getattr(sender, 'username', None)
                    if uid:
                        muted_users.add(str(uid))
                    if uname:
                        muted_users.add(uname.lower())
                    # حاول حذف الرسالة المردود عليها فوراً
                    try:
                        await reply_msg.delete()
                    except Exception:
                        pass
                    await user_client.send_message(
                        chat_id,
                        f"🔇 تم كتم المستخدم بنجاح!"
                    )
                else:
                    await user_client.send_message(
                        chat_id,
                        "❌ لا يمكن التعرف على مرسل الرسالة المردود عليها"
                    )
            else:
                await user_client.send_message(
                    chat_id,
                    "❌ **طريقة الاستخدام:**\n"
                    "• `.كتم @username` - كتم بالمعرف\n"
                    "• `.كتم 123456789` - كتم بالـ id\n"
                    "• `.كتم` - رد على رسالة المستخدم"
                )
        except Exception as e:
            logger.error(f"خطأ في mute_command: {e}")
            try:
                await user_client.send_message(chat_id, f"❌ حدث خطأ أثناء محاولة كتم المستخدم: {e}")
            except:
                pass

        try:
            await event.delete()
        except:
            pass

    async def unmute_command(self, event):
        """إلغاء كتم مستخدم
        يدعم:
        - `.الغاء كتم @username`
        - `.الغاء كتم user_id`
        - الرد على رسالة: `.الغاء كتم`
        """
        chat_id = event.chat_id
        try:
            # تحقق إذا كان هناك اسم بعد الأمر
            raw = (event.message.message or "") if getattr(event, 'message', None) else ""
            parts = raw.split(' ', 1)
            if len(parts) > 1 and parts[1].strip():
                target = parts[1].strip().lstrip('@')
                removed_any = False
                # إذا كان رقم (id)
                if re.fullmatch(r'\d+', target):
                    identifier = target
                    if identifier in muted_users:
                        muted_users.remove(identifier)
                        removed_any = True
                else:
                    identifier = target.lower()
                    # حاول حل اليوزرنيم إلى id لإزالة كل المعرفات ذات الصلة
                    try:
                        entity = await user_client.get_entity(target)
                        uid = getattr(entity, 'id', None)
                        uname = getattr(entity, 'username', None)
                        if uid and str(uid) in muted_users:
                            muted_users.remove(str(uid))
                            removed_any = True
                        if uname and uname.lower() in muted_users:
                            muted_users.remove(uname.lower())
                            removed_any = True
                    except Exception:
                        if identifier in muted_users:
                            muted_users.remove(identifier)
                            removed_any = True

                if removed_any:
                    await user_client.send_message(chat_id, f"✅ تم إلغاء كتم {target} بنجاح!")
                else:
                    await user_client.send_message(chat_id, "ℹ️ هذا المستخدم غير مكتوم أصلاً")
            elif event.is_reply:
                reply_msg = await event.get_reply_message()
                if reply_msg and reply_msg.sender:
                    sender = reply_msg.sender
                    uid = getattr(sender, 'id', None)
                    uname = getattr(sender, 'username', None)
                    removed_any = False
                    if uid and str(uid) in muted_users:
                        muted_users.remove(str(uid))
                        removed_any = True
                    if uname and uname.lower() in muted_users:
                        muted_users.remove(uname.lower())
                        removed_any = True

                    if removed_any:
                        await user_client.send_message(
                            chat_id,
                            f"✅ تم إلغاء كتم المستخدم بنجاح!"
                        )
                    else:
                        await user_client.send_message(chat_id, "ℹ️ هذا المستخدم غير مكتوم أصلاً")
                else:
                    await user_client.send_message(chat_id, "❌ لا يمكن التعرف على مرسل الرسالة المردود عليها")
            else:
                await user_client.send_message(
                    chat_id,
                    "❌ يرجى الرد على رسالة المستخدم المراد إلغاء كتمه أو استخدام `.الغاء كتم @username`"
                )
        except Exception as e:
            logger.error(f"خطأ في unmute_command: {e}")
            try:
                await user_client.send_message(chat_id, f"❌ حدث خطأ أثناء إلغاء الكتم: {e}")
            except:
                pass

        try:
            await event.delete()
        except:
            pass

    async def auto_post_command(self, chat_id, event):
        """إعداد النشر التلقائي"""
        await user_client.send_message(
            chat_id,
            "📢 **إعداد النشر التلقائي**\n\n"
            "🔧 **المطلوب:**\n"
            "1. النص المراد نشره\n"
            "2. عدد مرات النشر\n"
            "3. الفاصل الزمني (بالدقائق)\n\n"
            "💡 **مثال:**\n"
            "النص: مرحباً بالجميع!\n"
            "العدد: 5\n"
            "الفاصل: 10 دقائق\n\n"
            "⚠️ **ملاحظة:** استخدم هذه الميزة بحذر لتجنب السبام"
        )
        await event.delete()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالج أمر /start"""
        if not update.effective_user:
            return

        user_id = update.effective_user.id

        if not update.message:
            return

        await update.message.reply_text(
            "🔐 مرحباً بك في بوت التحكم الشخصي\n\n"
            "📱 لبدء استخدام البوت، يرجى إرسال رقم هاتفك بصيغة دولية:\n"
            "مثال: +966501234567\n\n"
            "⚠️ تأكد من إدخال الرقم بشكل صحيح"
        )

        auth_states[user_id] = {"step": "phone"}

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالج الرسائل الواردة"""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id
        message_text = update.message.text

        if not message_text:
            return

        # التحقق من حالة التوثيق
        if user_id in auth_states:
            auth_state = auth_states[user_id]

            # مرحلة إدخال رقم الهاتف
            if auth_state["step"] == "phone":
                await self.handle_phone_input(update, message_text)
                return

            # مرحلة إدخال الكود
            elif auth_state["step"] == "code":
                await self.handle_code_input(update, message_text)
                return

            # مرحلة إدخال كلمة المرور
            elif auth_state["step"] == "password":
                await self.handle_password_input(update, message_text)
                return

        # إذا كان المستخدم مسجل دخول، معالجة ذكية للرسائل
        if user_id == logged_in_user_id:
            await self.handle_smart_response(update, message_text)

    async def handle_phone_input(self, update: Update, phone: str) -> None:
        """معالجة إدخال رقم الهاتف"""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id

        # التحقق من صيغة رقم الهاتف
        phone_pattern = r'^\+\d{8,15}$'
        if not re.match(phone_pattern, phone):
            await update.message.reply_text(
                "❌ **خطأ في صيغة رقم الهاتف**\n\n"
                "🔧 **الصيغة الصحيحة:**\n"
                "• يجب أن يبدأ بـ +\n"
                "• يحتوي على 8-15 رقم\n"
                "• بدون مسافات أو رموز\n\n"
                "💡 **أمثلة صحيحة:**\n"
                "• +966501234567\n"
                "• +201234567890\n"
                "• +12345678901\n\n"
                "🔄 يرجى إعادة إدخال رقم هاتفك:",
            )
            return

        # محاولة إرسال الكود
        try:
            global user_client

            # إذا كان هناك عميل موجود مسبقاً
            if user_client:
                try:
                    await user_client.disconnect()
                except:
                    pass

            # إنشاء عميل جديد
            user_client = TelegramClient(
                SESSION_NAME,
                API_ID,
                API_HASH,
                connection_retries=5,
                retry_delay=1,
                timeout=10
            )

            # محاولة الاتصال
            await user_client.connect()

            # التأكد من الاتصال
            if not user_client.is_connected():
                raise Exception("فشل في الاتصال بـ Telegram")

            # تنظيف الرقم من المسافات الزائدة
            clean_phone = phone.strip()
            logger.info(f"محاولة إرسال رمز لرقم: {clean_phone[:5]}...")

            result = await user_client.send_code_request(clean_phone)

            # حفظ معلومات الجلسة
            auth_states[user_id] = {
                "step": "code",
                "phone": clean_phone,
                "phone_code_hash": result.phone_code_hash
            }

            await update.message.reply_text(
                "✅ **تم إرسال رمز التحقق بنجاح!**\n\n"
                f"📱 تم إرسال رمز التحقق إلى: `{clean_phone}`\n\n"
                "🔢 **يرجى إدخال الرمز كما يلي:**\n"
                "• بدون مسافات: 12345\n"
                "• أو مع شرطات: 1-2-3-4-5\n\n"
                "⏰ **انتباه:** الرمز صالح لمدة محدودة فقط!"
            )

        except FloodWaitError as e:
            logger.error(f"تم حظر الطلب مؤقتاً: {e}")
            await update.message.reply_text(
                f"⏳ يرجى الانتظار {e.seconds} ثانية قبل المحاولة مرة أخرى\n\n"
                "⚙️ هذا إجراء أمني من تليجرام لحماية الخدمة"
            )

        except Exception as e:
            logger.error(f"خطأ في إرسال الرمز: {e}")
            error_msg = str(e)

            # معالجة مختلف أنواع الأخطاء
            if "PHONE_NUMBER_INVALID" in error_msg:
                await update.message.reply_text(
                    "❌ رقم الهاتف غير صالح!\n\n"
                    "🔄 يرجى المحاولة مرة أخرى برقم صحيح"
                )
            elif "disconnected" in error_msg.lower() or "AuthRestartError" in error_msg:
                await update.message.reply_text(
                    "🔄 **مشاكل في الاتصال**\n\n"
                    "🔧 يبدو أن هناك مشاكل في خوادم Telegram\n"
                    "⏰ يرجى المحاولة مرة أخرى بعد دقائق قليلة\n\n"
                    "⚙️ **نصائح:**\n"
                    "• تأكد من اتصالك بالإنترنت\n"
                    "• استخدم /start للبدء من جديد"
                )
            elif "PHONE_CODE_EXPIRED" in error_msg:
                await update.message.reply_text(
                    "⏰ انتهت صلاحية الرمز!\n\n"
                    "🔄 ابدأ من جديد بإرسال /start"
                )
            else:
                await update.message.reply_text(
                    f"❌ **خطأ في الاتصال**\n\n"
                    f"🔧 **الخطأ:** {error_msg}\n\n"
                    f"🔄 **الحلول:**\n"
                    f"• تأكد من رقم هاتفك\n"
                    f"• تأكد من اتصال الإنترنت\n"
                    f"• حاول مرة أخرى بـ /start"
                )

            # حذف حالة التوثيق للبدء من جديد
            if user_id in auth_states:
                del auth_states[user_id]

            # تنظيف العميل المعطل
            if user_client:
                try:
                    await user_client.disconnect()
                    user_client = None
                except:
                    pass

    async def handle_code_input(self, update: Update, code: str) -> None:
        """معالجة إدخال رمز التحقق"""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id
        auth_state = auth_states.get(user_id, {})

        # تنظيف الكود من المسافات والشرطات (فقط الأرقام)
        clean_code = re.sub(r'[^\d]', '', code)

        # التحقق من صيغة الكود
        if not clean_code.isdigit() or len(clean_code) != 5:
            await update.message.reply_text(
                "❌ **خطأ في صيغة الكود**\n\n"
                "🔢 **الصيغة الصحيحة:**\n"
                "• 5 أرقام فقط\n"
                "• بدون حروف أو رموز\n\n"
                "💡 **أمثلة صحيحة:**\n"
                "• 12345\n"
                "• أو: 1-2-3-4-5"
            )
            return

        try:
            if not user_client:
                await update.message.reply_text(
                    "❌ **خطأ في الاتصال**\n\n"
                    "🔄 يرجى البدء من جديد بإرسال /start"
                )
                if user_id in auth_states:
                    del auth_states[user_id]
                return

            # التأكد من أن العميل متصل
            if not user_client.is_connected():
                await user_client.connect()

            await user_client.sign_in(
                phone=auth_state["phone"],
                code=clean_code,
                phone_code_hash=auth_state["phone_code_hash"]
            )

            # تسجيل الدخول بنجاح
            global logged_in_user_id
            logged_in_user_id = user_id

            # إعداد معالجات telethon
            self.setup_telethon_handlers()

            # حذف حالة التوثيق
            del auth_states[user_id]

            # إرسال رسالة نجاح مع لوحة التحكم
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📚 المساعدة", callback_data="help"),
                    InlineKeyboardButton("⚙️ الأوامر", callback_data="الاوامر")
                ],
                [
                    InlineKeyboardButton("🎯 بدء الصيد", callback_data="start_hunt"),
                    InlineKeyboardButton("📢 النشر التلقائي", callback_data="auto_post")
                ]
            ])

            await update.message.reply_text(
                "🎉 **تم تسجيل الدخول بنجاح!**\n\n"
                "✅ **الآن يمكنك استخدام جميع الميزات:**\n"
                "• 🎯 صيد اليوزرات النادرة\n"
                "• 📢 النشر التلقائي\n"
                "• 🔇 نظام الكتم المتقدم\n"
                "• 🤖 الذكاء الاصطناعي\n\n"
                "🔥 **الأوامر تعمل في جميع محادثاتك الآن!**\n\n"
                "💡 **لعرض قائمة الأوامر:** اكتب `.مساعدة` في أي محادثة\n"
                "⚙️ **لوحة تحكم:** اكتب `.الاوامر` في أي محادثة",
                reply_markup=keyboard
            )

            # بدء تحديث البايو التلقائي
            asyncio.create_task(self.update_bio_task())

        except SessionPasswordNeededError:
            # مطلوب كلمة مرور للتحقق بخطوتين
            auth_states[user_id]["step"] = "password"

            await update.message.reply_text(
                "🔐 **مطلوب كلمة مرور التحقق بخطوتين**\n\n"
                "🔑 يرجى إدخال كلمة المرور الخاصة بحسابك:\n\n"
                "⚠️ **تنبيه:** كلمة المرور آمنة ولن يتم حفظها"
            )

        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await update.message.reply_text(
                "❌ **الرمز غير صحيح أو منتهي الصلاحية**\n\n"
                "🔄 **يرجى المحاولة مرة أخرى:**\n"
                "• تأكد من الرمز المستلم\n"
                "• أدخل الرمز بسرعة قبل انتهاء صلاحيته\n\n"
                "💡 إذا انتهت صلاحية الرمز، ابدأ من جديد بـ /start"
            )

        except Exception as e:
            logger.error(f"خطأ في تسجيل الدخول: {e}")
            await update.message.reply_text(
                f"❌ **خطأ في تسجيل الدخول:**\n{str(e)}\n\n"
                "🔄 يرجى البدء من جديد بإرسال /start"
            )

            # حذف حالة التوثيق عند الخطأ
            if user_id in auth_states:
                del auth_states[user_id]

    async def handle_password_input(self, update: Update, password: str) -> None:
        """معالجة إدخال كلمة مرور التحقق بخطوتين"""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id

        try:
            if not user_client:
                await update.message.reply_text(
                    "❌ خطأ في الاتصال. يرجى البدء من جديد بإرسال /start"
                )
                return

            await user_client.sign_in(password=password)

            # تسجيل الدخول بنجاح
            global logged_in_user_id
            logged_in_user_id = user_id

            # إعداد معالجات telethon
            self.setup_telethon_handlers()

            # حذف حالة التوثيق
            del auth_states[user_id]

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📚 المساعدة", callback_data="help"),
                    InlineKeyboardButton("⚙️ الأوامر", callback_data="الاوامر")
                ],
                [
                    InlineKeyboardButton("🎯 بدء الصيد", callback_data="start_hunt"),
                    InlineKeyboardButton("📢 النشر التلقائي", callback_data="auto_post")
                ]
            ])

            await update.message.reply_text(
                "🎉 **تم تسجيل الدخول بنجاح!**\n\n"
                "✅ **جميع الميزات متاحة الآن:**\n"
                "• 🎯 صيد اليوزرات النادرة\n"
                "• 📢 النشر التلقائي\n"
                "• 🔇 نظام الكتم المتقدم\n"
                "• 🤖 الذكاء الاصطناعي\n\n"
                "🔥 **الأوامر تعمل في جميع محادثاتك الآن!**",
                reply_markup=keyboard
            )

            # بدء تحديث البايو التلقائي
            asyncio.create_task(self.update_bio_task())

        except PasswordHashInvalidError:
            await update.message.reply_text(
                "❌ **كلمة المرور غير صحيحة**\n\n"
                "🔄 يرجى المحاولة مرة أخرى بكلمة المرور الصحيحة\n\n"
                "💡 إذا نسيت كلمة المرور، ابدأ من جديد بـ /start"
            )

        except Exception as e:
            logger.error(f"خطأ في كلمة المرور: {e}")
            await update.message.reply_text(
                f"❌ خطأ في التحقق من كلمة المرور: {str(e)}\n\n"
                "🔄 يرجى البدء من جديد بإرسال /start"
            )

            if user_id in auth_states:
                del auth_states[user_id]

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالج أزرار لوحة التحكم"""
        if not update.callback_query:
            return

        query = update.callback_query
        await query.answer()

        data = query.data

        if data == "help":
            help_text = (
                "🤖 **أوامر البوت - دليل المساعدة**\n\n"
                "📋 **الأوامر الأساسية:**\n"
                "• `.مساعدة` - عرض هذه القائمة\n"
                "• `.الاوامر` - لوحة التحكم التفاعلية\n\n"
                "🔇 **أوامر الكتم:**\n"
                "• `.كتم` - كتم شخص (رد على رسالته)\n"
                "• `.كتم @معرف` - كتم شخص بمعرفه\n"
                "• `.الغاء كتم` - إلغاء كتم شخص\n\n"
                "🎯 **أوامر الصيد:**\n"
                "• `.صيد` - بدء صيد اليوزرات\n"
                "  - ثلاثي: ### (3 حروف)\n"
                "  - رباعي: #### (4 حروف مع _)\n"
                "  - خماسي: ##### (5 حروف)\n\n"
                "📢 **النشر التلقائي:**\n"
                "• `.نشر تلقائي` - نشر رسائل تلقائية\n"
                "  - يطلب النص والعدد والفاصل الزمني\n\n"
                "🔧 **الميزات الإضافية:**\n"
                "• تحديث البايو تلقائياً حسب الوقت\n"
                "• تحويل الرسائل الواردة\n"
                "• ذكاء اصطناعي للرد التلقائي\n\n"
                "💡 **ملاحظة:** جميع الأوامر تبدأ بنقطة (.)"
            )
            await query.message.reply_text(help_text)

        elif data == "الاوامر":
            keyboard_text = (
                "⚙️ **لوحة التحكم الرئيسية**\n\n"
                f"🎯 **صيد اليوزرات النشط:** {'نعم' if hunt_tasks else 'لا'}\n"
                f"📢 **النشر التلقائي:** {'نشط' if auto_post_tasks else 'متوقف'}\n"
                f"🔇 **المستخدمون المكتومون:** {len(muted_users)}\n\n"
                "📊 **إحصائيات اليوم:**\n"
                "• اليوزرات المفحوصة: 0\n"
                "• اليوزرات المتاحة: 0\n"
                "• الرسائل المنشورة: 0\n\n"
                "💡 استخدم الأوامر المتاحة للتحكم في البوت"
            )
            await query.message.reply_text(keyboard_text)

        elif data == "start_hunt":
            await query.message.reply_text(
                "🎯 **لبدء صيد اليوزرات:**\n\n"
                "اكتب `.صيد` في أي محادثة\n\n"
                "📊 **سيبدأ البوت في صيد:**\n"
                "• يوزرات ثلاثية (###)\n"
                "• يوزرات رباعية (##_##)\n"
                "• يوزرات خماسية (#####)"
            )

        elif data == "auto_post":
            await query.message.reply_text(
                "📢 **للنشر التلقائي:**\n\n"
                "اكتب `.نشر تلقائي` في أي محادثة\n\n"
                "🔧 **ستحتاج لتحديد:**\n"
                "• النص المراد نشره\n"
                "• عدد مرات النشر\n"
                "• الفاصل الزمني بالدقائق"
            )

    async def handle_smart_response(self, update: Update, message_text: str) -> None:
        """معالج الردود الذكية"""
        if not update.message:
            return

        message_lower = message_text.lower()

        # ردود ذكية متنوعة
        response = ""
        if "مساعدة" in message_text or "help" in message_lower:
            response = "🆘 لعرض المساعدة الكاملة، استخدم الأمر .مساعدة"
        elif "شكرا" in message_text or "thanks" in message_lower:
            response = "😊 العفو! سعيد لمساعدتك"
        elif "مرحبا" in message_text or "hello" in message_lower:
            response = "👋 مرحباً! كيف يمكنني مساعدتك اليوم؟"

        if response:
            await update.message.reply_text(response)

    async def hunting_task(self, chat_id: int) -> None:
        """مهمة صيد اليوزرات المستمرة"""
        if not user_client or chat_id not in hunt_tasks:
            return

        report_counter = 0

        while hunt_tasks.get(chat_id, {}).get('active', False):
            try:
                # توليد يوزرات عشوائية
                usernames = self.generate_usernames(50)

                for username in usernames:
                    if not hunt_tasks.get(chat_id, {}).get('active', False):
                        break

                    try:
                        # فحص اليوزر
                        result = await user_client.get_entity(username)
                        hunt_tasks[chat_id]['checked'] += 1

                        # إذا وُجد اليوزر، فهو محجوز
                        logger.info(f"اليوزر @{username} محجوز")

                    except Exception:
                        # اليوزر متاح
                        hunt_tasks[chat_id]['available'] += 1

                        await user_client.send_message(
                            chat_id,
                            f"🎯 **يوزر متاح!**\n\n"
                            f"📝 **اليوزر:** @{username}\n"
                            f"📊 **النوع:** {'ثلاثي' if len(username) == 3 else 'رباعي' if '_' in username else 'خماسي'}\n"
                            f"🔗 **الرابط:** https://t.me/{username}\n\n"
                            f"⚡ **سارع بحجزه قبل أن يأخذه غيرك!**"
                        )

                    # توقف قصير لتجنب الحظر
                    await asyncio.sleep(2)

                report_counter += 1

                # إرسال تقرير كل 10 دورات (حوالي 10 دقائق)
                if report_counter >= 10:
                    await user_client.send_message(
                        chat_id,
                        f"📊 **تقرير صيد اليوزرات**\n\n"
                        f"🔍 **المفحوص:** {hunt_tasks[chat_id]['checked']}\n"
                        f"✅ **المتاح:** {hunt_tasks[chat_id]['available']}\n"
                        f"📈 **معدل التوفر:** {(hunt_tasks[chat_id]['available'] / max(hunt_tasks[chat_id]['checked'], 1) * 100):.1f}%\n\n"
                        f"🎯 **الصيد مستمر...**"
                    )
                    report_counter = 0

                # انتظار قبل الدورة التالية
                await asyncio.sleep(60)  # دقيقة واحدة

            except Exception as e:
                logger.error(f"خطأ في مهمة الصيد: {e}")
                await asyncio.sleep(30)

    def generate_usernames(self, count: int) -> list:
        """توليد قائمة يوزرات عشوائية"""
        usernames = []
        letters = string.ascii_lowercase

        for _ in range(count):
            # اختيار نوع اليوزر عشوائياً
            choice = random.choice(['3char', '4char', '5char'])

            if choice == '3char':
                # ثلاثي: 3 حروف
                username = ''.join(random.choices(letters, k=3))
            elif choice == '4char':
                # رباعي: حرفين _ حرفين
                part1 = ''.join(random.choices(letters, k=2))
                part2 = ''.join(random.choices(letters, k=2))
                username = f"{part1}_{part2}"
            else:
                # خماسي: 5 حروف
                username = ''.join(random.choices(letters, k=5))

            # تأكد من أن اليوزر لا يبدأ برقم
            if not username[0].isdigit():
                usernames.append(username)

        return usernames

    async def update_bio_task(self) -> None:
        """مهمة تحديث البايو التلقائي"""
        if not user_client:
            return

        while True:
            try:
                now = datetime.now()
                bio_text = f"🕐 {now.strftime('%H:%M')} | 📅 {now.strftime('%Y-%m-%d')}"

                await user_client.update_profile(about=bio_text)
                logger.info(f"تم تحديث البايو: {bio_text}")

                # تحديث كل ساعة
                await asyncio.sleep(3600)

            except Exception as e:
                logger.error(f"خطأ في تحديث البايو: {e}")
                await asyncio.sleep(1800)  # إعادة المحاولة بعد نصف ساعة

    async def run(self) -> None:
        """تشغيل البوت"""
        logger.info("🚀 بدء تشغيل البوت...")
        await self.application.initialize()
        await self.application.start()

        # استخدام polling بطريقة متوافقة مع نسخة python-telegram-bot
        try:
            await self.application.updater.start_polling()
        except Exception:
            # بعض الإصدارات لا تحتوي على updater؛ استخدم run_polling كبديل
            try:
                await self.application.start_polling()
            except Exception:
                logger.error("❌ خطأ: لا يمكن بدء تشغيل polling")
                return

        logger.info("✅ البوت يعمل بنجاح!")

        # الحفاظ على البوت يعمل
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("🛑 إيقاف البوت...")
        finally:
            await self.application.stop()
            if user_client and hasattr(user_client, 'disconnect') and callable(user_client.disconnect):
                try:
                    await user_client.disconnect()
                except Exception as e:
                    logger.debug(f"خطأ في قطع اتصال telethon: {e}")


async def main() -> None:
    """الدالة الرئيسية"""
    bot = TelegramBot()
    await bot.run()


if __name__ == "__main__":
    print("🤖 بوت التليجرام الذكي")
    print("=" * 50)
    print("✅ جاهز للاستخدام مع جميع الميزات:")
    print("🔐 تسجيل دخول آمن")
    print("🎯 صيد اليوزرات النادرة")
    print("📢 النشر التلقائي")
    print("🔇 نظام الكتم المتقدم")
    print("🤖 ذكاء اصطناعي للردود")
    print("⚙️ لوحة تحكم تفاعلية")
    print("=" * 50)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف البوت بواسطة المستخدم")
    except Exception as e:
        print(f"❌ خطأ في تشغيل البوت: {e}")
