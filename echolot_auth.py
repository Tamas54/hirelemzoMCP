"""Auth + fiók + API-kulcs réteg (plan 3a + 3c alapok).

Jelszavas auth, KÜLSŐ FÜGGŐSÉG NÉLKÜL: stdlib pbkdf2_hmac (200k iteráció,
per-user só), session-cookie (httponly, 30 nap), API-kulcsok az MCP-hez
napi tier-kvótával. Magic-link később adható hozzá (Resend-kulcs kell).

Táblák:
  users(id, email UNIQUE, pw_hash, salt, tier, created_at, last_seen)
  sessions(token PK, user_id, expires_at)
  api_keys(key PK, user_id, created_at, calls_total, calls_today, day, revoked)

Tier-kvóták (MCP tool-hívás / nap) — a tier a users.tier mezőből jön,
az admin-lapról kézzel állítható (Stripe majd a 3d-ben):
  free: 200 · pro: 2000 · power: 20000 · admin: korlátlan
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone

TIERS = ("free", "pro", "power", "admin")
DAILY_QUOTA = {"free": 200, "pro": 2000, "power": 20000, "admin": 10**9}
SESSION_DAYS = 30
_PBKDF_ITER = 200_000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def _conn(db_path: str) -> sqlite3.Connection:
    c = sqlite3.connect(str(db_path), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def ensure_tables(db_path: str) -> None:
    conn = _conn(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                email      TEXT NOT NULL UNIQUE,
                pw_hash    TEXT NOT NULL,
                salt       TEXT NOT NULL,
                tier       TEXT NOT NULL DEFAULT 'free',
                created_at TEXT NOT NULL,
                last_seen  TEXT
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                expires_at TEXT NOT NULL
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key         TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                created_at  TEXT NOT NULL,
                calls_total INTEGER DEFAULT 0,
                calls_today INTEGER DEFAULT 0,
                day         TEXT,
                revoked     INTEGER DEFAULT 0
            )""")
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_pw(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _PBKDF_ITER).hex()


# ─── Regisztráció / belépés ─────────────────────────────────────────────

def create_user(db_path: str, email: str, password: str) -> tuple[bool, str]:
    """(ok, hibaüzenet-kulcs). Jelszó minimum 8 karakter."""
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        return False, "bad_email"
    if len(password or "") < 8:
        return False, "short_password"
    ensure_tables(db_path)
    salt = secrets.token_hex(16)
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO users (email, pw_hash, salt, tier, created_at) "
            "VALUES (?,?,?,'free',?)",
            (email, _hash_pw(password, salt), salt, _now()))
        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "exists"
    finally:
        conn.close()


def verify_login(db_path: str, email: str, password: str) -> int | None:
    """Sikeres belépésnél user_id, különben None. Konstans-idejű összevetés."""
    email = (email or "").strip().lower()
    ensure_tables(db_path)
    conn = _conn(db_path)
    try:
        row = conn.execute(
            "SELECT id, pw_hash, salt FROM users WHERE email=?",
            (email,)).fetchone()
        if not row:
            # dummy hash a timing-egyenlőséghez
            _hash_pw(password or "x", "00" * 16)
            return None
        uid, pw_hash, salt = row
        if secrets.compare_digest(_hash_pw(password or "", salt), pw_hash):
            conn.execute("UPDATE users SET last_seen=? WHERE id=?", (_now(), uid))
            conn.commit()
            return uid
        return None
    finally:
        conn.close()


# ─── Session ────────────────────────────────────────────────────────────

def create_session(db_path: str, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
           ).isoformat(timespec="seconds")
    conn = _conn(db_path)
    try:
        conn.execute("INSERT INTO sessions VALUES (?,?,?)", (token, user_id, exp))
        # lejárt sessionök takarítása
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))
        conn.commit()
        return token
    finally:
        conn.close()


def get_session_user(db_path: str, token: str) -> dict | None:
    """Session-token → {id, email, tier} vagy None."""
    if not token:
        return None
    ensure_tables(db_path)
    conn = _conn(db_path)
    try:
        row = conn.execute(
            """SELECT u.id, u.email, u.tier FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE s.token=? AND s.expires_at >= ?""",
            (token, _now())).fetchone()
        return {"id": row[0], "email": row[1], "tier": row[2]} if row else None
    finally:
        conn.close()


def destroy_session(db_path: str, token: str) -> None:
    if not token:
        return
    conn = _conn(db_path)
    try:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
    finally:
        conn.close()


# ─── API-kulcsok (MCP-csatlakoztató, plan 3c) ───────────────────────────

def create_api_key(db_path: str, user_id: int) -> str:
    """Max 3 aktív kulcs / user."""
    conn = _conn(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM api_keys WHERE user_id=? AND revoked=0",
            (user_id,)).fetchone()[0]
        if n >= 3:
            return ""
        key = "eck_" + secrets.token_urlsafe(24)
        conn.execute(
            "INSERT INTO api_keys (key, user_id, created_at, day) VALUES (?,?,?,?)",
            (key, user_id, _now(), ""))
        conn.commit()
        return key
    finally:
        conn.close()


def revoke_api_key(db_path: str, user_id: int, key: str) -> None:
    conn = _conn(db_path)
    try:
        conn.execute("UPDATE api_keys SET revoked=1 WHERE key=? AND user_id=?",
                     (key, user_id))
        conn.commit()
    finally:
        conn.close()


def list_api_keys(db_path: str, user_id: int) -> list[dict]:
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            """SELECT key, created_at, calls_total, calls_today, day
               FROM api_keys WHERE user_id=? AND revoked=0
               ORDER BY created_at""", (user_id,)).fetchall()
        return [{"key": r[0], "created_at": r[1], "calls_total": r[2],
                 "calls_today": r[3] if r[4] == _today() else 0} for r in rows]
    finally:
        conn.close()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def validate_api_key(db_path: str, key: str) -> tuple[bool, str]:
    """(engedélyezve, ok). Kvóta-számláló bump atomikusan.

    ok: 'ok' | 'missing' | 'invalid' | 'quota' — a 401/429 válaszhoz."""
    if not key or not key.startswith("eck_") or len(key) > 64:
        return False, "missing" if not key else "invalid"
    ensure_tables(db_path)
    conn = _conn(db_path)
    try:
        row = conn.execute(
            """SELECT k.key, k.calls_today, k.day, u.tier
               FROM api_keys k JOIN users u ON u.id = k.user_id
               WHERE k.key=? AND k.revoked=0""", (key,)).fetchone()
        if not row:
            return False, "invalid"
        _, calls_today, day, tier = row
        today = _today()
        if day != today:
            calls_today = 0
        quota = DAILY_QUOTA.get(tier, DAILY_QUOTA["free"])
        if calls_today >= quota:
            return False, "quota"
        conn.execute(
            """UPDATE api_keys SET calls_total = calls_total + 1,
                   calls_today = CASE WHEN day=? THEN calls_today + 1 ELSE 1 END,
                   day = ? WHERE key=?""", (today, today, key))
        conn.commit()
        return True, "ok"
    finally:
        conn.close()


# ─── Admin-segédek ──────────────────────────────────────────────────────

def list_users(db_path: str, limit: int = 200) -> list[dict]:
    ensure_tables(db_path)
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            """SELECT u.id, u.email, u.tier, u.created_at, u.last_seen,
                      (SELECT COUNT(*) FROM api_keys k
                       WHERE k.user_id=u.id AND k.revoked=0) AS keys
               FROM users u ORDER BY u.id DESC LIMIT ?""", (limit,)).fetchall()
        return [{"id": r[0], "email": r[1], "tier": r[2], "created_at": r[3],
                 "last_seen": r[4], "keys": r[5]} for r in rows]
    finally:
        conn.close()


def set_user_tier(db_path: str, user_id: int, tier: str) -> bool:
    if tier not in TIERS:
        return False
    conn = _conn(db_path)
    try:
        conn.execute("UPDATE users SET tier=? WHERE id=?", (tier, int(user_id)))
        conn.commit()
        return True
    finally:
        conn.close()
