import sqlite3
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

DB_PATH = "justsignup.db"
SGT = timezone(timedelta(hours=8))


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets you access columns by name
    return conn


def init_db():
    """Create all tables if they don't exist. Safe to call on every startup."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel         TEXT,
            channel_username TEXT,  -- for link construction
            message_id      INTEGER, -- Telegram message ID
            chat_id         INTEGER,
            raw_text        TEXT,
            title           TEXT,
            event_type      TEXT,
            synopsis        TEXT,
            organisation    TEXT,
            target_audience TEXT,   -- stored as JSON array string
            date            TEXT,
            date_iso        TEXT,
            day_of_week     TEXT,
            location        TEXT,
            fee             REAL,
            signup_link     TEXT,
            deadline        TEXT,
            key_speakers    TEXT,
            refreshments    TEXT,
            contacts        TEXT,
            claude_score    INTEGER,
            adjusted_score  INTEGER,
            why_go          TEXT,
            matched_tags    TEXT,   -- stored as JSON array string
            created_at      TEXT    -- ISO timestamp
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    INTEGER UNIQUE,
            sent_at     TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            key     TEXT PRIMARY KEY,
            value   TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_event(channel: str, raw_text: str, extracted: dict,
               message_id: int = None, channel_username: str = None, chat_id: int = None) -> int:
    """
    Save an extracted event to the DB.
    claude_score, adjusted_score, why_go, matched_tags are null at this stage.
    Returns the new event's id.
    """
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        INSERT INTO events (
            channel, channel_username, message_id, chat_id, raw_text,
            title, event_type, synopsis, organisation,
            target_audience, date, date_iso, day_of_week, location, fee,
            signup_link, deadline, key_speakers, refreshments, contacts,
            claude_score, adjusted_score, why_go, matched_tags, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        channel,
        channel_username,
        message_id,
        chat_id,
        raw_text,
        extracted.get("title"),
        extracted.get("event_type"),
        extracted.get("synopsis"),
        extracted.get("organisation"),
        json.dumps(extracted.get("target_audience") or []),
        extracted.get("date"),
        extracted.get("date_iso"),
        extracted.get("day_of_week"),
        extracted.get("location"),
        extracted.get("fee"),
        extracted.get("signup_link"),
        extracted.get("deadline"),
        extracted.get("key_speakers"),
        extracted.get("refreshments"),
        extracted.get("contacts"),
        None,   # claude_score — filled in after Step 3
        None,   # adjusted_score — filled in after Step 4
        None,   # why_go — filled in after Step 3
        None,   # matched_tags — filled in after Step 3
        datetime.now(SGT).isoformat()
    ))

    event_id = c.lastrowid
    conn.commit()
    conn.close()
    return event_id


def update_scores(event_id: int, claude_score: int, adjusted_score: int,
                  why_go: str, matched_tags: list):
    """Update score fields after pipeline Steps 3 and 4 complete."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        UPDATE events
        SET claude_score   = ?,
            adjusted_score = ?,
            why_go         = ?,
            matched_tags   = ?
        WHERE id = ?
    """, (
        claude_score,
        adjusted_score,
        why_go,
        json.dumps(matched_tags or []),
        event_id
    ))

    conn.commit()
    conn.close()


def get_unsent_events(limit: int = 5) -> list[dict]:
    """
    Return top 5 undelivered events by adjusted_score within the digest frequency window,
    sorted by adjusted_score descending. Events with null date_iso appear at the bottom.
    """

    profile_conn = get_connection()
    pc = profile_conn.cursor()
    pc.execute("SELECT value FROM profile WHERE key = 'digest_frequency'")
    row = pc.fetchone()
    profile_conn.close()

    frequency = row["value"] if row else "Daily"

    cutoff_map = {
        "Daily":        timedelta(days=1),
        "2x in a week": timedelta(days=3),
        "Weekly":       timedelta(days=7),
        "Biweekly":     timedelta(days=14),
    }
    delta = cutoff_map.get(frequency, timedelta(days=1))
    cutoff = (datetime.now(SGT) - delta).isoformat()

    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT e.*
        FROM events e
        LEFT JOIN sent_events s ON e.id = s.event_id
        WHERE s.event_id IS NULL
          AND e.created_at >= ?
        ORDER BY
            CASE WHEN e.date_iso IS NULL THEN 1 ELSE 0 END,
            e.adjusted_score DESC
        LIMIT ?
    """, (cutoff, limit))

    rows = [dict(row) for row in c.fetchall()]
    conn.close()

    for row in rows:
        row["target_audience"] = json.loads(row["target_audience"] or "[]")
        row["matched_tags"] = json.loads(row["matched_tags"] or "[]")

    return rows


def mark_sent(event_id: int):
    """Record that an event was delivered in the digest."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        INSERT OR IGNORE INTO sent_events (event_id, sent_at)
        VALUES (?, ?)
    """, (event_id, datetime.now(SGT).isoformat()))

    conn.commit()
    conn.close()


def search_events(query: str) -> list[dict]:
    """Search across title, synopsis, organisation, matched_tags."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT * FROM events
        WHERE title        LIKE ?
           OR synopsis     LIKE ?
           OR organisation LIKE ?
           OR matched_tags LIKE ?
        ORDER BY adjusted_score DESC NULLS LAST
    """, tuple(f"%{query}%" for _ in range(4)))

    rows = [dict(row) for row in c.fetchall()]
    conn.close()

    for row in rows:
        row["target_audience"] = json.loads(row["target_audience"] or "[]")
        row["matched_tags"] = json.loads(row["matched_tags"] or "[]")

    return rows


def get_event_by_title(partial_title: str) -> Optional[dict]:
    """Fetch a single event by partial title match. Used by /explain."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT * FROM events
        WHERE title LIKE ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (f"%{partial_title}%",))

    row = c.fetchone()
    conn.close()

    if not row:
        return None

    result = dict(row)
    result["target_audience"] = json.loads(result["target_audience"] or "[]")
    result["matched_tags"] = json.loads(result["matched_tags"] or "[]")
    return result


def get_profile() -> dict:
    """Return the full profile as a flat dict."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT key, value FROM profile")
    rows = c.fetchall()
    conn.close()

    return {row["key"]: row["value"] for row in rows}


def save_profile(updates: dict):
    """Upsert one or more profile fields."""
    conn = get_connection()
    c = conn.cursor()

    for key, value in updates.items():
        c.execute("""
            INSERT INTO profile (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, str(value)))

    conn.commit()
    conn.close()


def event_exists(title: str) -> bool:
    """Return True if an event with a sufficiently similar title already exists in the DB."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT COUNT(*) as cnt FROM events
        WHERE LOWER(title) = LOWER(?)
    """, (title.strip(),))

    row = c.fetchone()
    conn.close()
    return row["cnt"] > 0