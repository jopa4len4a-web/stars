from cryptography.fernet import Fernet
from .config import settings

def _fernet():
    if not settings.master_key:
        raise RuntimeError("MASTER_KEY is not configured")
    return Fernet(settings.master_key.encode())

def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()

def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
