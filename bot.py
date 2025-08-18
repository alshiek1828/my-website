from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = "8049186197:AAEO9KWbs9V6wxSLUe1ByAdjhRB25ZbPzzA"  # استبدل بالتوكن اللي أخذته من BotFather

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"مرحبا يا {update.effective_user.first_name} 👋")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))

app.run_polling()
