from collections import defaultdict

VALID_ANSWERS = {
    "A": "A", "B": "B", "C": "C", "D": "D",
    "1": "A", "2": "B", "3": "C", "4": "D"
}

answers = defaultdict(int)
users_answered = set()


def reset_question():
    answers.clear()
    users_answered.clear()


def accept_vote(source: str, username: str, message: str):
    """Normalize and accept a vote from any chat source.
    Returns True if the vote was accepted (not duplicate and valid), False otherwise.
    """
    if not username:
        return False
    uname = f"{source}:{username}" if source else username
    # prevent duplicates per question
    if uname in users_answered:
        return False

    msg = (message or "").strip().upper()
    if msg.startswith('!ANSWER'):
        msg = msg.replace('!ANSWER', '').strip()

    if msg in VALID_ANSWERS:
        letter = VALID_ANSWERS[msg]
        users_answered.add(uname)
        answers[letter] += 1
        return True

    return False


def get_counts_and_percentages():
    total = sum(answers.values())
    counts = dict(answers)
    percentages = {}
    for k in ['A', 'B', 'C', 'D']:
        cnt = counts.get(k, 0)
        pct = round((cnt / total) * 100, 1) if total > 0 else 0.0
        percentages[k] = pct
    return counts, percentages, total
