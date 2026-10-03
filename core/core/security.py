"""Module de sécurité et de chiffrement pour JURIA."""
import hashlib
import hmac
import os
import re
from cryptography.fernet import Fernet

# Clé de chiffrement interne pour les documents au repos
_SECRET_KEY = os.environ.get("JURIA_ENCRYPTION_KEY", Fernet.generate_key())
try:
    _fernet = Fernet(_SECRET_KEY if isinstance(_SECRET_KEY, bytes) else _SECRET_KEY.encode())
except Exception:
    _fernet = Fernet(Fernet.generate_key())

def hash_password(password: str) -> tuple[str, str]:
    """Génère un sel et un hash sécurisé pour le mot de passe."""
    salt = os.urandom(16).hex()
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100_000
    ).hex()
    return pwd_hash, salt

def verify_password(provided_password: str, stored_hash: str, stored_salt: str) -> bool:
    """Vérifie un mot de passe par rapport à son hash et son sel."""
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        provided_password.encode('utf-8'),
        stored_salt.encode('utf-8'),
        100_000
    ).hex()
    return hmac.compare_digest(pwd_hash, stored_hash)

def strong_password(password: str) -> bool:
    """Vérifie si le mot de passe respecte la politique de sécurité (10 caractères min)."""
    return len(password) >= 10

def valid_email(email: str) -> bool:
    """Vérifie grossièrement la validité d'une adresse e-mail."""
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return bool(re.match(pattern, email))

def encrypt(data: bytes) -> bytes:
    """Chiffre des données binaires (pour les documents au repos)."""
    return _fernet.encrypt(data)

def decrypt(token: bytes) -> bytes:
    """Déchiffre des données binaires."""
    return _fernet.decrypt(token)

def verify_token(token: str, expected: str) -> bool:
    """Vérifie un jeton de sécurité contre les attaques temporelles."""
    return hmac.compare_digest(token, expected)
