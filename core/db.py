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
        "FROM users u ORDER BY u.id")


def set_user_flag(uid, field, value):
    if field not in ("is_admin", "is_active"):
        raise ValueError("Champ invalide")
    _exec(f"UPDATE users SET {field}=? WHERE id=?", (int(value), uid))


def admin_count():
    return _one("SELECT COUNT(*) n FROM users WHERE is_admin=1 AND is_active=1")["n"]


def stats():
    n = lambda sql: _one(sql)["n"]
    return {
        "Utilisateurs": n("SELECT COUNT(*) n FROM users"),
        "Comptes actifs": n("SELECT COUNT(*) n FROM users WHERE is_active=1"),
        "Dossiers": n("SELECT COUNT(*) n FROM cases"),
        "Questions posées": n("SELECT COUNT(*) n FROM messages WHERE role='user'"),
        "Documents analysés": n("SELECT COUNT(*) n FROM documents"),
        "Sources juridiques": n("SELECT COUNT(*) n FROM sources"),
    }
