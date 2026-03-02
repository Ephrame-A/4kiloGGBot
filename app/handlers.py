from typing import Any, Dict, Optional

from telebot import types

from app import config
from app import db
from app import i18n
from app.state import UserSession, user_sessions


def extract_arguments(raw_text: str) -> str:
    """Return the part of the command after the first space."""
    if not raw_text:
        return ''
    parts = raw_text.split(' ', 1)
    return parts[1].strip() if len(parts) > 1 else ''


def parse_language_command_args(raw_args: str) -> tuple[Optional[str], str]:
    """Parse language + message, supporting languages with spaces."""
    if not raw_args:
        return None, ''

    args = raw_args.strip()
    if not args:
        return None, ''

    sorted_languages = sorted(config.LANGUAGE_OPTIONS, key=len, reverse=True)
    for lang in sorted_languages:
        if args.lower().startswith(lang.lower() + ' '):
            message = args[len(lang):].strip()
            return lang, message

    return None, args


def normalize_gender(gender_text: str) -> Optional[str]:
    """Return canonical gender value from config if provided text matches."""
    cleaned = (gender_text or '').strip().lower()
    for option in config.GENDER_OPTIONS:
        if cleaned == option.lower():
            return option
    return None


def parse_optional_gender_prefix(raw_args: str) -> tuple[Optional[str], str]:
    """Parse optional leading gender token from args and return (gender, message)."""
    args = (raw_args or '').strip()
    if not args:
        return None, ''

    parts = args.split(' ', 1)
    maybe_gender = normalize_gender(parts[0])
    if maybe_gender:
        message = parts[1].strip() if len(parts) > 1 else ''
        return maybe_gender, message

    return None, args


def normalize_department(department_text: str) -> Optional[str]:
    """Return canonical department value from config if provided text matches."""
    cleaned = (department_text or '').strip().lower()
    for option in config.DEPARTMENTS:
        if cleaned == option.lower():
            return option
    return None


def parse_optional_filters_prefix(raw_args: str) -> tuple[Optional[str], Optional[str], str]:
    """Parse optional gender/department prefixes from the start of args."""
    remaining = (raw_args or '').strip()
    selected_gender: Optional[str] = None
    selected_department: Optional[str] = None

    for _ in range(2):
        if not remaining:
            break

        parts = remaining.split(' ', 1)
        first_token = parts[0].strip()

        if selected_gender is None:
            maybe_gender = normalize_gender(first_token)
            if maybe_gender:
                selected_gender = maybe_gender
                remaining = parts[1].strip() if len(parts) > 1 else ''
                continue

        if selected_department is None:
            sorted_departments = sorted(config.DEPARTMENTS, key=len, reverse=True)
            matched_department: Optional[str] = None
            for department in sorted_departments:
                if remaining.lower() == department.lower():
                    matched_department = department
                    remaining = ''
                    break
                if remaining.lower().startswith(department.lower() + ' '):
                    matched_department = department
                    remaining = remaining[len(department):].strip()
                    break
            if matched_department:
                selected_department = matched_department
                continue

        break

    return selected_gender, selected_department, remaining


def require_session(chat_id: int, bot) -> Optional[UserSession]:
    session = user_sessions.get(chat_id)
    if not session:
        bot.send_message(chat_id, i18n.translate(config.DEFAULT_LANGUAGE, 'session_expired'))
        return None
    return session


def build_language_keyboard() -> types.ReplyKeyboardMarkup:
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    for lang in config.LANGUAGE_OPTIONS:
        markup.add(lang)
    return markup


def register_handlers(bot, supabase) -> None:
    def prompt_language(chat_id: int, reply_to_message: Optional[types.Message] = None) -> None:
        prompt_text = i18n.translate(config.DEFAULT_LANGUAGE, 'ask_language')
        markup = build_language_keyboard()
        if reply_to_message is not None:
            msg = bot.reply_to(reply_to_message, prompt_text, reply_markup=markup)
        else:
            msg = bot.send_message(chat_id, prompt_text, reply_markup=markup)
        bot.register_next_step_handler(msg, process_language_step)

    def ask_name(chat_id: int) -> None:
        msg = bot.send_message(
            chat_id,
            i18n.translate_for_chat(chat_id, 'ask_name'),
            reply_markup=types.ReplyKeyboardRemove()
        )
        bot.register_next_step_handler(msg, process_name_step)

    def ask_gender(chat_id: int) -> None:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add(*config.GENDER_OPTIONS)
        msg = bot.send_message(
            chat_id,
            i18n.translate_for_chat(chat_id, 'ask_gender'),
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_gender_step)

    def ask_department(chat_id: int) -> None:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add(*config.DEPARTMENTS)
        msg = bot.send_message(
            chat_id,
            i18n.translate_for_chat(chat_id, 'ask_dept'),
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_dept_step)

    def ask_year(chat_id: int) -> None:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add(*(str(year) for year in config.YEAR_CHOICES))
        msg = bot.send_message(
            chat_id,
            i18n.translate_for_chat(chat_id, 'ask_year'),
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_year_step)

    def finalize_registration(chat_id: int) -> None:
        user_data = require_session(chat_id, bot)
        if not user_data:
            return

        language = user_data.get('preferred_language', config.DEFAULT_LANGUAGE)

        db.save_user_to_db(
            supabase,
            chat_id,
            user_data.get('name'),
            user_data.get('gender'),
            user_data.get('dept'),
            user_data.get('year'),
            user_data.get('preferred_language'),
        )

        del user_sessions[chat_id]

        bot.send_message(
            chat_id,
            i18n.translate(language, 'registration_success'),
            reply_markup=types.ReplyKeyboardRemove()
        )

    def is_master_admin(user_id: int) -> bool:
        return user_id in config.MASTER_ADMINS

    def can_manage_year(user_id: int, year: int) -> bool:
        return is_master_admin(user_id) or user_id in config.YEAR_ADMINS.get(year, set())

    def send_bulk_message(message_text: str, filters: Optional[Dict[str, Any]] = None) -> None:
        if not message_text:
            return

        try:
            students = db.fetch_users(supabase, filters)
        except Exception as e:  # noqa: BLE001
            print(f"Supabase bulk fetch error: {e}")
            return

        for student in students:
            user_id = student.get('user_id')
            name = student.get('name') or 'Student'
            try:
                personalized_message = message_text.replace('{name}', str(name))
                bot.send_message(user_id, personalized_message)
            except Exception as send_err:  # noqa: BLE001
                print(f"Failed to send broadcast to {user_id}: {send_err}")

    @bot.message_handler(commands=['start'])
    def start_cmd(message: types.Message) -> None:
        chat_id = message.chat.id
        user_sessions[chat_id] = {}
        prompt_language(chat_id, reply_to_message=message)

    def process_language_step(message: types.Message) -> None:
        chat_id = message.chat.id
        language = (message.text or '').strip()

        if language not in config.LANGUAGE_OPTIONS:
            bot.reply_to(message, i18n.translate(config.DEFAULT_LANGUAGE, 'invalid_language'))
            prompt_language(chat_id)
            return

        session = user_sessions.get(chat_id, {})
        session['preferred_language'] = language
        user_sessions[chat_id] = session
        ask_name(chat_id)

    def process_name_step(message: types.Message) -> None:
        chat_id = message.chat.id
        session = require_session(chat_id, bot)
        if not session:
            return

        name = (message.text or '').strip()
        if not name:
            msg = bot.reply_to(message, i18n.translate_for_chat(chat_id, 'invalid_name'))
            bot.register_next_step_handler(msg, process_name_step)
            return

        session['name'] = name
        ask_gender(chat_id)

    def process_gender_step(message: types.Message) -> None:
        chat_id = message.chat.id
        session = require_session(chat_id, bot)
        if not session:
            return

        gender = (message.text or '').strip()
        if gender not in config.GENDER_OPTIONS:
            msg = bot.reply_to(message, i18n.translate_for_chat(chat_id, 'invalid_gender'))
            bot.register_next_step_handler(msg, process_gender_step)
            return

        session['gender'] = gender
        ask_department(chat_id)

    def process_dept_step(message: types.Message) -> None:
        chat_id = message.chat.id
        session = require_session(chat_id, bot)
        if not session:
            return

        dept = (message.text or '').strip()
        session['dept'] = dept
        ask_year(chat_id)

    def process_year_step(message: types.Message) -> None:
        chat_id = message.chat.id
        session = require_session(chat_id, bot)
        if not session:
            return

        year_text = (message.text or '').strip()
        if not year_text.isdigit() or int(year_text) not in config.YEAR_CHOICES:
            msg = bot.reply_to(message, i18n.translate_for_chat(chat_id, 'invalid_year'))
            bot.register_next_step_handler(msg, process_year_step)
            return

        session['year'] = int(year_text)
        finalize_registration(chat_id)

    @bot.message_handler(commands=['all'])
    def handle_broadcast(message: types.Message) -> None:
        if not is_master_admin(message.from_user.id):
            return

        gender_options_text = '/'.join(config.GENDER_OPTIONS)
        usage_text = (
            f"Usage: /all [<{gender_options_text}>] [<department>] <message>"
        )

        args = extract_arguments(message.text)
        gender, department, announcement = parse_optional_filters_prefix(args)
        if not announcement:
            bot.reply_to(message, usage_text)
            return

        filters: Dict[str, Any] = {}
        if gender:
            filters['gender'] = gender
        if department:
            filters['department'] = department
        send_bulk_message(announcement, filters)
        bot.reply_to(message, "Broadcast sent to all registered students.")

    @bot.message_handler(commands=['year'])
    def handle_notify_year(message: types.Message) -> None:
        sender_id = message.from_user.id
        year_options_text = '/'.join(str(year) for year in config.YEAR_CHOICES)
        gender_options_text = '/'.join(config.GENDER_OPTIONS)
        usage_text = (
            f"Usage: /year <{year_options_text}> [<{gender_options_text}>] [<department>] <message>"
        )

        args = extract_arguments(message.text)
        if not args:
            bot.reply_to(message, usage_text)
            return

        parts = args.split(' ', 1)
        if len(parts) < 2 or not parts[0].isdigit():
            bot.reply_to(message, usage_text)
            return

        year = int(parts[0])
        if year not in config.YEAR_CHOICES:
            allowed_years = ', '.join(str(option) for option in config.YEAR_CHOICES)
            bot.reply_to(message, f"Year must be one of: {allowed_years}.")
            return

        if not can_manage_year(sender_id, year):
            bot.reply_to(message, "You are not authorized to notify this year.")
            return

        gender, department, announcement = parse_optional_filters_prefix(parts[1])
        if not announcement:
            bot.reply_to(message, "Please provide a message after the year.")
            return

        filters: Dict[str, Any] = {'year': year}
        if gender:
            filters['gender'] = gender
        if department:
            filters['department'] = department
        send_bulk_message(announcement, filters)
        bot.reply_to(message, f"Notification sent to year {year} students.")

    @bot.message_handler(commands=['lang'])
    def handle_notify_language(message: types.Message) -> None:
        if not is_master_admin(message.from_user.id):
            return

        language_options_text = '/'.join(config.LANGUAGE_OPTIONS)
        gender_options_text = '/'.join(config.GENDER_OPTIONS)
        usage_text = (
            f"Usage: /lang <{language_options_text}> [<{gender_options_text}>] [<department>] <message>"
        )

        args = extract_arguments(message.text)
        if not args:
            bot.reply_to(message, usage_text)
            return

        language, language_tail = parse_language_command_args(args)
        if not language:
            allowed_languages = ', '.join(config.LANGUAGE_OPTIONS)
            bot.reply_to(message, f"Language must be one of: {allowed_languages}.")
            return

        gender, department, announcement = parse_optional_filters_prefix(language_tail)

        if not announcement:
            bot.reply_to(message, "Please provide a message after the language.")
            return

        filters: Dict[str, Any] = {'preferred_language': language}
        if gender:
            filters['gender'] = gender
        if department:
            filters['department'] = department
        send_bulk_message(announcement, filters)
        bot.reply_to(message, f"Notification sent to {language} users.")

    @bot.message_handler(commands=['yearlang'])
    def handle_notify_year_language(message: types.Message) -> None:
        sender_id = message.from_user.id
        year_options_text = '/'.join(str(year) for year in config.YEAR_CHOICES)
        language_options_text = '/'.join(config.LANGUAGE_OPTIONS)
        gender_options_text = '/'.join(config.GENDER_OPTIONS)
        usage_text = (
            f"Usage: /yearlang <{year_options_text}> <{language_options_text}> "
            f"[<{gender_options_text}>] [<department>] <message>"
        )

        args = extract_arguments(message.text)
        if not args:
            bot.reply_to(message, usage_text)
            return

        parts = args.split(' ', 1)
        if len(parts) < 2 or not parts[0].isdigit():
            bot.reply_to(message, usage_text)
            return

        year = int(parts[0])
        if year not in config.YEAR_CHOICES:
            allowed_years = ', '.join(str(option) for option in config.YEAR_CHOICES)
            bot.reply_to(message, f"Year must be one of: {allowed_years}.")
            return

        if not can_manage_year(sender_id, year):
            bot.reply_to(message, "You are not authorized to notify this year.")
            return

        language, language_tail = parse_language_command_args(parts[1])
        if not language:
            allowed_languages = ', '.join(config.LANGUAGE_OPTIONS)
            bot.reply_to(message, f"Language must be one of: {allowed_languages}.")
            return

        gender, department, announcement = parse_optional_filters_prefix(language_tail)

        if not announcement:
            bot.reply_to(message, "Please provide a message after the language.")
            return

        filters: Dict[str, Any] = {'year': year, 'preferred_language': language}
        if gender:
            filters['gender'] = gender
        if department:
            filters['department'] = department
        send_bulk_message(announcement, filters)
        bot.reply_to(message, f"Notification sent to year {year} ({language}).")
