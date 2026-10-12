import hashlib, hmac, json, time
from urllib.parse import parse_qsl
from .config import settings

def validate_telegram_init_data(init_data: str, max_age_seconds: int = 86400) -> dict:
    if not settings.bot_token or not init_data:
        raise ValueError("Telegram authentication is not configured")
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("Missing Telegram signature")
    auth_date = int(data.get("auth_date", "0"))
    if auth_date <= 0 or abs(time.time() - auth_date) > max_age_seconds:
        raise ValueError("Expired Telegram session")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise ValueError("Invalid Telegram signature")
    user = json.loads(data.get("user", "{}"))
    if not user.get("id"):
        raise ValueError("Missing Telegram user")
    return user
