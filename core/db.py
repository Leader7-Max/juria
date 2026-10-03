
"""Gestion de la base de données SQLite pour Juria."""
from contextlib import contextmanager
from datetime import datetime
import sqlite3
import numpy as np
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT NOT NULL,
    country TEXT,
    domain TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER,
    filename TEXT NOT NULL,
    file_path TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    country TEXT,
    domain TEXT,
    status TEXT,
    application_date TEXT,
    content TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    text TEXT NOT NULL,
    embedding BLOB,
    FOREIGN KEY(source_id) REFERENCES sources(id)
);
"""

def now() -> str:
    return datetime.utcnow().isoformat()

@contextmanager
def conn():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def _one(sql, params=()):
    with conn() as c:
        row = c.execute(sql, params).fetchone()
        return dict(row) if row else None

def _rows(sql, params=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]

def _exec(sql, params=()):
    with conn() as c:
        c.execute(sql, params)

def init():
    with conn() as c:
        c.executescript(SCHEMA)
        cols = [r["name"] for r in c.execute("PRAGMA table_info(users)")]
        if "is_active" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
        if "last_login" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN last_login TEXT")

# ---------- administration des utilisateurs ----------
def get_user_by_id(uid):
    return _one("SELECT * FROM users WHERE id=?", (uid,))

def touch_login(uid):
    _exec("UPDATE users SET last_login=? WHERE id=?", (now(), uid))

def update_password(uid, pw_hash, salt):
    _exec("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (pw_hash, salt, uid))

def list_users():
    return _rows(
        "SELECT u.id, u.email, u.is_admin, u.is_active, u.created_at, u.last_login, "
        "(SELECT COUNT(*) FROM cases c WHERE c.user_id=u.id) AS cases, "
        "(SELECT COUNT(*) FROM messages m JOIN cases c ON c.id=m.case_id "
        "WHERE c.user_id=u.id AND m.role='user') AS questions "
        "FROM users u ORDER BY u.id"
    )

def set_user_flag(uid, field, value):
    if field not in ("is_admin", "is_active"):
        raise ValueError("Champ invalide")
    _exec(f"UPDATE users SET {field}=? WHERE id=?", (int(value), uid))

def admin_count():
    res = _one("SELECT COUNT(*) n FROM users WHERE is_admin=1 AND is_active=1")
    return res["n"] if res else 0

def stats():
    n = lambda sql: _one(sql)["n"] if _one(sql) else 0
    return {
        "Utilisateurs": n("SELECT COUNT(*) n FROM users"),
        "Comptes actifs": n("SELECT COUNT(*) n FROM users WHERE is_active=1"),
        "Dossiers": n("SELECT COUNT(*) n FROM cases"),
        "Questions posées": n("SELECT COUNT(*) n FROM messages WHERE role='user'"),
        "Documents analysés": n("SELECT COUNT(*) n FROM documents"),
        "Sources juridiques": n("SELECT COUNT(*) n FROM sources"),
    }

# ---------- RAG & Recherche (nécessaires pour rag.py) ----------
def add_source(meta: dict, chunks: list[str], embs: list) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO sources (title, country, domain, status, application_date, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                meta.get("title", "Document"),
                meta.get("country", ""),
                meta.get("domain", ""),
                meta.get("status", "en_vigueur"),
                meta.get("application_date", ""),
                meta.get("content", ""),
                now()
            )
        )
        source_id = cur.lastrowid
        for i, text in enumerate(chunks):
            emb_blob = None
            if embs and i < len(embs) and embs[i] is not None:
                emb_blob = np.array(embs[i], dtype=np.float32).tobytes()
            c.execute(
                "INSERT INTO chunks (source_id, text, embedding) VALUES (?, ?, ?)",
                (source_id, text, emb_blob)
            )
        return source_id

def fts_search(query: str, country: str, domain: str, today: str) -> list[int]:
    # Recherche basique de secours par mots-clés si FTS n'est pas configuré
    sql = """
        SELECT ch.id FROM chunks ch
        JOIN sources s ON ch.source_id = s.id
        WHERE (s.country = ? OR ? = '') AND (s.domain = ? OR ? = '')
    """
    rows = _rows(sql, (country, country, domain, domain))
    return [r["id"] for r in rows]

def vector_candidates(country: str, domain: str, today: str) -> list[tuple]:
    sql = """
        SELECT ch.id, ch.embedding FROM chunks ch
        JOIN sources s ON ch.source_id = s.id
        WHERE ch.embedding IS NOT NULL AND (s.country = ? OR ? = '') AND (s.domain = ? OR ? = '')
    """
    with conn() as c:
        rows = c.execute(sql, (country, country, domain, domain)).fetchall()
        cands = []
        for r in rows:
            if r["embedding"]:
                arr = np.frombuffer(r["embedding"], dtype=np.float32)
                cands.append((r["id"], arr))
        return cands

def chunks_by_ids(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join(["?"] * len(ids))
    sql = f"""
        SELECT ch.id, ch.source_id, ch.text, s.title, s.country, s.domain 
        FROM chunks ch 
        JOIN sources s ON ch.source_id = s.id 
        WHERE ch.id IN ({placeholders})
    """
    return _rows(sql, tuple(ids))
