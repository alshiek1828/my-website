from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8049186197:AAEO9KWbs9V6wxSLUe1ByAdjhRB25ZbPzzA"

flask_app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

# أوامر البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"مرحبا يا {update.effective_user.first_name} 👋")

application.add_handler(CommandHandler("start", start))

# Webhook endpoint - Telegram راح يبعث التحديثات لهون
@flask_app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put_nowait(update)
    return "ok", 200

# Health check - Render يستعمله عشان يتأكد السيرفر شغال
@flask_app.route("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=10000)
