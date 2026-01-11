from collections import defaultdict
import sqlite3
import os
import time

VALID_ANSWERS = {
    "A": "A", "B": "B", "C": "C", "D": "D",
    "1": "A", "2": "B", "3": "C", "4": "D"
}

# votes: mapping of 'source:username' -> letter (A/B/C/D)
votes = {}

# Трекинг обработанных сообщений для предотвращения дубликатов
# Формат: (source, username, message, rounded_timestamp) -> True
processed_messages = {}

# ID последнего обработанного сообщения для каждого источника
last_message_ids = {}

# Флаг: открыто ли голосование
_voting_open = False
question_start_time = 0

def set_voting_open(is_open: bool):
    global _voting_open, question_start_time
    _voting_open = is_open
    if is_open:
        question_start_time = time.time()
        print(f"🗳️ Голосование открыто. Время начала: {question_start_time}")

# --- simple SQLite score DB ---
DB_PATH = os.path.join(os.path.dirname(__file__), "scores.db")

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS scores (
        username TEXT PRIMARY KEY,
        score INTEGER NOT NULL DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()


def reset_question():
    global processed_messages
    votes.clear()
    # Очищаем ВЕСЬ кеш сообщений при новом вопросе
    # чтобы старые сообщения не засчитывались
    old_count = len(processed_messages)
    processed_messages.clear()
    print(f"🔄 Голоса сброшены. Очищено {old_count} старых сообщений из кеша")


def accept_vote(source: str, username: str, message: str, timestamp: float = None, message_id: str = None):
    """Normalize and accept a vote from any chat source.
    Returns True if the vote was accepted (not duplicate and valid), False otherwise.
    """
    # Нормализуем timestamp
    if timestamp is not None:
        if timestamp > 10000000000:
            timestamp = timestamp / 1000.0
    else:
        timestamp = time.time()
    
    # Проверка по message_id (если передан) - для TikTok/YouTube
    if message_id:
        msg_id_key = f"{source}:{message_id}"
        if msg_id_key in last_message_ids:
            return False
        last_message_ids[msg_id_key] = True
    
    # Создаем уникальный ключ для сообщения
    # Округляем timestamp до секунды
    msg_key = (source, username, message.strip().upper(), int(timestamp))
    
    # Проверка: уже обрабатывали это сообщение?
    if msg_key in processed_messages:
        return False
    
    # Отмечаем сообщение как обработанное
    processed_messages[msg_key] = True
    
    if not _voting_open:
        return False

    if not username:
        return False
    
    uname = f"{source}:{username}" if source else username
    
    # Проверка дубликата - уже проголосовал?
    if uname in votes:
        return False

    # Проверяем, что сообщение пришло ПОСЛЕ начала вопроса (с буфером 5 секунд)
    if timestamp < (question_start_time - 5):
        return False

    msg = (message or "").strip().upper()
    
    # Убираем префикс !ANSWER если есть
    if msg.startswith('!ANSWER'):
        msg = msg.replace('!ANSWER', '').strip()

    if msg in VALID_ANSWERS:
        letter = VALID_ANSWERS[msg]
        votes[uname] = letter
        print(f"✅ [{source}] {username} → {letter}")
        return True

    return False


def get_counts_and_percentages():
    counts = defaultdict(int)
    for v in votes.values():
        counts[v] += 1
    total = sum(counts.values())
    percentages = {}
    for k in ['A', 'B', 'C', 'D']:
        cnt = counts.get(k, 0)
        pct = round((cnt / total) * 100, 1) if total > 0 else 0.0
        percentages[k] = pct
    return dict(counts), percentages, total


def get_voters_for_letter(letter: str):
    # return list of (source, username) tuples for voters who chose 'letter'
    res = []
    for uname, v in votes.items():
        if v == letter:
            if ':' in uname:
                src, user = uname.split(':', 1)
            else:
                src, user = '', uname
            res.append((src, user))
    return res


def award_points(user_tuples, points=1):
    """user_tuples: iterable of (source, username)"""
    if not user_tuples:
        return
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    for _, username in user_tuples:
        cur.execute("SELECT score FROM scores WHERE username = ?", (username,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE scores SET score = score + ? WHERE username = ?", (points, username))
        else:
            cur.execute("INSERT INTO scores(username, score) VALUES(?, ?)", (username, points))
    conn.commit()
    conn.close()


def get_top_scores(limit=10):
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username, score FROM scores ORDER BY score DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [{'username': r[0], 'score': r[1]} for r in rows]


# initialize DB file on import
init_db()