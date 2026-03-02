from app.bootstrap import create_bot

bot = create_bot()

print("Bot is running...")
try:
    bot.infinity_polling(timeout=90, long_polling_timeout=5)
except Exception as e:  # noqa: BLE001
    print(f"Polling error: {e}")
