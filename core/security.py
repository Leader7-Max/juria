import hashlib
import re
import os
from cryptography.fernet import Fernet

# Clé de chiffrement interne (générée ou dérivée si besoin)
_KEY = os.environ.get("JURIA_ENCRYPTION_KEY", Fernet.generate_key())
if isinstance(_KEY, str):
    _KEY = _KEY.encode()
_FERNET = Fernet(_KEY if len(_KEY) == 44 else Fernet.generate_key())

def hash_password(password: str) -> tuple[str, str]:
    salt = os.urandom(16).hex()
    h = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return h, salt

def verify_password(password: str, hashed: str, salt: str) -> bool:
    h = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return h == hashed

def strong_password(password: str) -> bool:
    return len(password) >= 10

def valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))

def encrypt(data: bytes) -> bytes:
    return _FERNET.encrypt(data)

def decrypt(data: bytes) -> bytes:
    return _FERNET.decrypt(data)
