"""Module de sécurité et de chiffrement pour JURIA."""
import hashlib
import hmac

def hash_password(password: str) -> str:
    """Génère un hash simple pour les mots de passe si nécessaire."""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_token(token: str, expected: str) -> bool:
    """Vérifie un jeton de sécurité de manière sécurisée contre les attaques temporelles."""
    return hmac.compare_digest(token, expected)
