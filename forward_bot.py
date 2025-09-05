from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

BOT_TOKEN = "8049186197:AAEO9KWbs9V6wxSLUe1ByAdjhRB25ZbPzzA"

def start(update: Update, context: CallbackContext):
    update.message.reply_text("نورت ✨")

updater = Updater(BOT_TOKEN)
updater.dispatcher.add_handler(CommandHandler("start", start))

print("البوت شغال 🚀")
updater.start_polling()  # <<< هنا البوت يعمل polling
updater.idle()
