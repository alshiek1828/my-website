from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.ext import MessageHandler, filters
import logging
import os

# التوكن اللي أخدته من BotFather
TOKEN = "8049186197:AAEO9KWbs9V6wxSLUe1ByAdjhRB25ZbPzzA"

# رابط موقعك على Render + مسار Webhook
WEBHOOK_URL = f"https://my-website-flmq.onrender.com/webhook"

# Logging عشان تشوف الأخطاء
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

# دالة start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"مرحبا يا {update.effective_user.first_name} 👋")

# دالة echo للرد على أي رسالة
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"رسالتك: {update.message.text}")

# إنشاء التطبيق
app = ApplicationBuilder().token(TOKEN).build()

# إضافة الهاندلرز
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# ضبط Webhook
app.run_webhook(
    listen="0.0.0.0",       # يستمع لكل الطلبات الواردة
    port=int(os.environ.get("PORT", 10000)),  # Render يعطي PORT تلقائي
    webhook_url=WEBHOOK_URL
)
