from pyrogram import Client, filters

# بيانات API من my.telegram.org
api_id = 29668409
api_hash = "6ff15390ad84e8ed5029cec215ee589d"

# ID القنوات
source_channel = -2396595955  # القناة المصدر (ضع ID)
target_channel = -2737286794  # القناة الوجهة (ضع ID)

app = Client("forwarder", api_id=api_id, api_hash=api_hash)

@app.on_message(filters.chat(source_channel))
async def forward_to_channel(client, message):
    await message.copy(target_channel)

print("Bot is running...")
app.run()
