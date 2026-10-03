"""Gestion de la sécurité, des hachages de mots de passe et de l'authentification pour Juria."""
import hashlib
import os

def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """Hache un mot de passe avec un sel (salt)."""
    if not salt:
        salt = os.urandom(16).hex()
    pwd_hash = hashlib.sha256((password + salt).encode('utf-8')).hexdigest()
    return pwd_hash, salt

def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    """Vérifie si un mot de passe correspond au hachage enregistré."""
    test_hash, _ = hash_password(password, salt)
    return test_hash == pw_hash
