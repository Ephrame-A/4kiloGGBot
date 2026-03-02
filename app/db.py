from typing import Any, Dict, Optional

from supabase import Client


def fetch_users(supabase: Client, filters: Optional[Dict[str, Any]] = None) -> list[dict[str, Any]]:
    query = supabase.table('users').select('user_id,name')
    if filters:
        for key, value in filters.items():
            query = query.eq(key, value)
    response = query.execute()
    return response.data if getattr(response, 'data', None) else []


def save_user_to_db(
    supabase: Client,
    user_id: int,
    name: str | None,
    gender: str | None,
    dept: str | None,
    year: int | None,
    preferred_language: str | None,
) -> None:
    try:
        response = supabase.table('users').upsert({
            'user_id': user_id,
            'name': name,
            'gender': gender,
            'department': dept,
            'year': year,
            'preferred_language': preferred_language,
        }).execute()
        if getattr(response, 'error', None):
            print(f"Supabase upsert error: {response.error}")
    except Exception as e:  # noqa: BLE001
        print(f"Supabase save error: {e}")
