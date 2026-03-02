import os

import telebot
from telebot import types
from dotenv import load_dotenv
from supabase import Client, create_client

from app import config
from app.handlers import register_handlers


def create_bot() -> telebot.TeleBot:
    load_dotenv()

    token = (os.getenv('TELEGRAM_BOT_TOKEN') or '').strip()
    supabase_url = (os.getenv('SUPABASE_URL') or '').strip()
    supabase_service_role_key = (os.getenv('SUPABASE_SERVICE_ROLE_KEY') or '').strip()

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing in .env")

    if not supabase_url or not supabase_service_role_key:
        raise RuntimeError("Supabase credentials missing (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")

    supabase: Client = create_client(supabase_url, supabase_service_role_key)

    try:
        supabase.table('users').select('user_id').limit(1).execute()
        print("Supabase connection established")
    except Exception as e:  # noqa: BLE001
        print("Warning: Unable to query 'users' table. Ensure it exists before running the bot.")
        print(f"Supabase error: {e}")

    bot = telebot.TeleBot(token)
    try:
        bot.set_my_commands([
            types.BotCommand("start", "Start registration"),
        ])
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: Unable to set default commands: {exc}")

    admin_commands = [
        types.BotCommand("all", "Send to all users"),
        types.BotCommand("year", "Send to a specific year"),
        types.BotCommand("lang", "Send to a specific language"),
        types.BotCommand("yearlang", "Send to year + language"),
    ]

    year_admin_commands = [
        types.BotCommand("year", "Send to a specific year"),
        types.BotCommand("yearlang", "Send to year + language"),
    ]

    year_admin_ids = set()
    for ids in config.YEAR_ADMINS.values():
        year_admin_ids.update(ids)

    for admin_id in config.MASTER_ADMINS:
        try:
            bot.set_my_commands(admin_commands, scope=types.BotCommandScopeChat(admin_id))
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: Unable to set admin commands for {admin_id}: {exc}")

    for admin_id in year_admin_ids.difference(config.MASTER_ADMINS):
        try:
            bot.set_my_commands(year_admin_commands, scope=types.BotCommandScopeChat(admin_id))
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: Unable to set year admin commands for {admin_id}: {exc}")
    register_handlers(bot, supabase)
    return bot
