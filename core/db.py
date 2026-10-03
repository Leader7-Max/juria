import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path("juria.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            pw_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            country TEXT,
            domain TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER,
            role TEXT,
            kind TEXT,
            content TEXT,
            risk TEXT,
            meta TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER,
            filename TEXT,
            mime TEXT,
            path TEXT,
            analysis TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER,
            event_date TEXT,
            label TEXT,
            FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country TEXT,
            domain TEXT,
            jurisdiction TEXT,
            title TEXT,
            article TEXT,
            url TEXT,
            published TEXT,
            effective_from TEXT,
            effective_to TEXT,
            status TEXT,
            confidence TEXT,
            last_verified TEXT,
            content TEXT
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

def get_user(email: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

def get_user_by_id(uid: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        return dict(row) if row else None

def create_user(email, pw_hash, salt, is_admin=False):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, pw_hash, salt, is_admin) VALUES (?, ?, ?, ?)",
            (email, pw_hash, salt, 1 if is_admin else 0)
        )
        return cur.lastrowid

def user_count():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def admin_count():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]

def touch_login(uid):
    with get_conn() as conn:
        conn.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (uid,))

def audit(uid, action, details=""):
    with get_conn() as conn:
        conn.execute("INSERT INTO audit (user_id, action, details) VALUES (?, ?, ?)", (uid, action, details))

def list_cases(uid):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM cases WHERE user_id = ? ORDER BY id DESC", (uid,))]

def get_case(cid, uid):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id = ? AND user_id = ?", (cid, uid)).fetchone()
        return dict(row) if row else None

def create_case(uid, title, country, domain):
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO cases (user_id, title, country, domain) VALUES (?, ?, ?, ?)", (uid, title, country, domain))
        return cur.lastrowid

def delete_case(cid, uid):
    with get_conn() as conn:
        conn.execute("DELETE FROM cases WHERE id = ? AND user_id = ?", (cid, uid))

def country_source_count(country):
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM sources WHERE country = ?", (country,)).fetchone()[0]

def get_messages(case_id, uid):
    with get_conn() as conn:
        # Vérifie que le dossier appartient bien à l'utilisateur
        c = conn.execute("SELECT id FROM cases WHERE id = ? AND user_id = ?", (case_id, uid)).fetchone()
        if not c:
            return []
        return [dict(r) for r in conn.execute("SELECT * FROM messages WHERE case_id = ? ORDER BY id ASC", (case_id,))]

def add_message(case_id, role, kind, content, risk=None, meta=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (case_id, role, kind, content, risk, meta) VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, role, kind, content, risk, json.dumps(meta) if meta else None)
        )

def list_documents(case_id, uid):
    with get_conn() as conn:
        c = conn.execute("SELECT id FROM cases WHERE id = ? AND user_id = ?", (case_id, uid)).fetchone()
        if not c:
            return []
        return [dict(r) for r in conn.execute("SELECT * FROM documents WHERE case_id = ? ORDER BY id DESC", (case_id,))]

def add_document(case_id, filename, mime, path, analysis):
    with get_conn() as conn:
        conn.execute("INSERT INTO documents (case_id, filename, mime, path, analysis) VALUES (?, ?, ?, ?, ?)",
                     (case_id, filename, mime, path, analysis))

def add_event(case_id, event_date, label):
    with get_conn() as conn:
        conn.execute("INSERT INTO events (case_id, event_date, label) VALUES (?, ?, ?)", (case_id, event_date, label))

def list_events(case_id, uid):
    with get_conn() as conn:
        c = conn.execute("SELECT id FROM cases WHERE id = ? AND user_id = ?", (case_id, uid)).fetchone()
        if not c:
            return []
        return [dict(r) for r in conn.execute("SELECT * FROM events WHERE case_id = ? ORDER BY event_date DESC", (case_id,))]

def export_user(uid):
    with get_conn() as conn:
        user = dict(conn.execute("SELECT id, email, created_at FROM users WHERE id = ?", (uid,)).fetchone())
        cases = [dict(r) for r in conn.execute("SELECT * FROM cases WHERE user_id = ?", (uid,))]
        for c in cases:
            c["messages"] = [dict(r) for r in conn.execute("SELECT * FROM messages WHERE case_id = ?", (c["id"],))]
            c["documents"] = [dict(r) for r in conn.execute("SELECT filename, mime, analysis, created_at FROM documents WHERE case_id = ?", (c["id"],))]
            c["events"] = [dict(r) for r in conn.execute("SELECT event_date, label FROM events WHERE case_id = ?", (c["id"],))]
        return {"user": user, "cases": cases}

def coverage():
    with get_conn() as conn:
        try:
            return [dict(r) for r in conn.execute("SELECT country, domain, COUNT(*) as count FROM sources GROUP BY country, domain")]
        except Exception:
            return []

def list_sources(limit=50):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM sources ORDER BY id DESC LIMIT ?", (limit,))]

def set_source_status(sid, status, verified_today=False):
    with get_conn() as conn:
        if verified_today:
            conn.execute("UPDATE sources SET status = ?, last_verified = ? WHERE id = ?", (status, datetime.today().strftime('%Y-%m-%d'), sid))
        else:
            conn.execute("UPDATE sources SET status = ? WHERE id = ?", (status, sid))

def stats():
    with get_conn() as conn:
        u = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        c = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        m = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        return {"Utilisateurs": u, "Dossiers": c, "Messages": m}

def list_users():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("""
            USELECT u.id, u.email, u.is_admin, u.is_active, u.created_at, u.last_login,
                   (SELECT COUNT(*) FROM cases c WHERE c.user_id = u.id) as cases,
                   (SELECT COUNT(*) FROM messages m JOIN cases c ON m.case_id = c.id WHERE c.user_id = u.id AND m.role='user') as questions
            FROM users u ORDER BY u.id DESC
        """)]

def set_user_flag(uid, flag, val):
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {flag} = ? WHERE id = ?", (1 if val else 0, uid))

def update_password(uid, h, s):
    with get_conn() as conn:
        conn.execute("UPDATE users SET pw_hash = ?, salt = ? WHERE id = ?", (h, s, uid))

def delete_user(uid):
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))

def recent_audit(limit=30):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]
