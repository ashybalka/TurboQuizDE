from collections import defaultdict
import sqlite3
import os
import time
from typing import Dict, Tuple, Iterable

# ---------------- CONFIG ----------------

VALID_ANSWERS = {
    "A": "A", "B": "B", "C": "C", "D": "D",
    "1": "A", "2": "B", "3": "C", "4": "D"
}

DB_PATH = os.path.join(os.path.dirname(__file__), "scores.db")

MESSAGE_ID_TTL = 3600        # 1 час
DUPLICATE_TIME_WINDOW = 1   # 1 секунда

# ---------------- STATE ----------------

votes: Dict[str, str] = {}
processed_messages: Dict[Tuple, float] = {}
global_message_ids: Dict[str, float] = {}

_voting_open = False
question_start_time = 0.0


# ---------------- VOTING ----------------

def set_voting_open(is_open: bool):
    global _voting_open, question_start_time
    _voting_open = is_open
    if is_open:
        question_start_time = time.time()
        print(f"🗳️ Голосование открыто ({question_start_time:.0f})")


def reset_question():
    votes.clear()
    processed_messages.clear()
    _cleanup_global_message_ids()
    print(f"🔄 Вопрос сброшен | ID cache: {len(global_message_ids)}")


def accept_vote(
    source: str,
    username: str,
    message: str,
    timestamp: float | None = None,
    message_id: str | None = None
) -> bool:

    if not _voting_open or not username:
        return False

    timestamp = _normalize_timestamp(timestamp)

    if timestamp < question_start_time - 5:
        return False

    if message_id and _is_duplicate_message_id(source, message_id, timestamp):
        return False

    msg_key = _build_message_key(source, username, message, timestamp)
    if msg_key in processed_messages:
        return False

    processed_messages[msg_key] = timestamp

    uname = f"{source}:{username}"
    if uname in votes:
        return False

    letter = _extract_answer(message)
    if not letter:
        return False

    votes[uname] = letter
    print(f"✅ [{source}] {username} → {letter}")
    return True


# ---------------- HELPERS ----------------

def _normalize_timestamp(ts: float | None) -> float:
    if ts is None:
        return time.time()
    return ts / 1000 if ts > 1e10 else ts


def _build_message_key(source, username, message, timestamp):
    return (
        source,
        username,
        message.strip().upper(),
        int(timestamp / DUPLICATE_TIME_WINDOW)
    )


def _is_duplicate_message_id(source, message_id, timestamp) -> bool:
    key = f"{source}:{message_id}"
    if key in global_message_ids:
        return True
    global_message_ids[key] = timestamp
    return False


def _cleanup_global_message_ids():
    cutoff = time.time() - MESSAGE_ID_TTL
    for k in list(global_message_ids):
        if global_message_ids[k] < cutoff:
            del global_message_ids[k]


def _extract_answer(message: str) -> str | None:
    msg = message.strip().upper()
    if msg.startswith("!ANSWER"):
        msg = msg[7:].strip()
    return VALID_ANSWERS.get(msg)


# ---------------- STATS ----------------

def get_counts_and_percentages():
    counts = defaultdict(int)
    for v in votes.values():
        counts[v] += 1

    total = sum(counts.values())
    percentages = {
        k: round((counts.get(k, 0) / total) * 100, 1) if total else 0.0
        for k in ("A", "B", "C", "D")
    }
    return dict(counts), percentages, total


def get_voters_for_letter(letter: str):
    return [
        tuple(uname.split(":", 1))
        for uname, v in votes.items()
        if v == letter
    ]


# ---------------- DATABASE ----------------

def _get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                username TEXT PRIMARY KEY,
                score INTEGER NOT NULL DEFAULT 0
            )
        """)


def award_points(users: Iterable[Tuple[str, str]], points=1):
    users = {u for _, u in users}
    if not users:
        return

    init_db()
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.executemany("""
            INSERT INTO scores(username, score)
            VALUES(?, ?)
            ON CONFLICT(username)
            DO UPDATE SET score = score + excluded.score
        """, [(u, points) for u in users])


def get_top_scores(limit=10):
    init_db()
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT username, score
            FROM scores
            ORDER BY score DESC
            LIMIT ?
        """, (limit,))
        return [
            {"username": u, "score": s}
            for u, s in cur.fetchall()
        ]


# init DB on import
init_db()
