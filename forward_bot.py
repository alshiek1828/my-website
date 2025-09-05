# forward_bot.py
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# توكن البوت
BOT_TOKEN = "8049186197:AAEO9KWbs9V6wxSLUe1ByAdjhRB25ZbPzzA"

# إنشاء Flask سيرفر صغير
app = Flask("")

@app.route("/")
def home():
    return "Bot is running!"

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# دالة /start
def start(update: Update, context: CallbackContext):
    update.message.reply_text("نورت ✨")

# إعداد البوت
updater = Updater(BOT_TOKEN)
updater.dispatcher.add_handler(CommandHandler("start", start))

# شغل السيرفر عشان Railway يعتبر الخدمة نشطة
keep_alive()

print("البوت شغال 🚀")
updater.start_polling()
updater.idle()
