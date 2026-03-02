from app import config
from app.state import user_sessions


def translate(language: str, key: str) -> str:
    """Return the localized text for the provided key."""
    language_pack = config.TRANSLATIONS.get(language) or {}
    fallback_pack = config.TRANSLATIONS.get(config.DEFAULT_LANGUAGE, {})
    return language_pack.get(key) or fallback_pack.get(key) or key


def get_language_for_chat(chat_id: int) -> str:
    session = user_sessions.get(chat_id)
    preferred = (session or {}).get('preferred_language')
    if preferred in config.LANGUAGE_OPTIONS:
        return preferred
    return config.DEFAULT_LANGUAGE


def translate_for_chat(chat_id: int, key: str) -> str:
    return translate(get_language_for_chat(chat_id), key)
