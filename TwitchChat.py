import socket
import vote_manager
import config

def reset_question():
    """Сброс при новом вопросе"""
    vote_manager.reset_question()
    print("\n🔄 Новый вопрос — ответы принимаются\n")

# === ПОДКЛЮЧЕНИЕ ===
sock = socket.socket()
sock.connect((SERVER, PORT))

sock.send(f"PASS {config.IRC_TOKEN}\r\n".encode())
sock.send(f"NICK {config.IRC_NICK}\r\n".encode())
sock.send(f"JOIN {config.IRC_CHANNEL}\r\n".encode())

print("🎮 Чат подключён. Ожидаем ответы...")

# === ОСНОВНОЙ ЦИКЛ ===
while True:
    resp = sock.recv(2048).decode("utf-8")

    if resp.startswith("PING"):
        sock.send("PONG :tmi.twitch.tv\r\n".encode())
        continue

    for line in resp.split("\r\n"):
        if "PRIVMSG" not in line:
            continue

        try:
            username = line.split("!")[0][1:]
            message = line.split(":", 2)[2].strip().upper()

            # команда для ручного сброса (пишешь в чат сам)
            if message == "!RESET" and username.lower() == config.IRC_NICK.lower():
                reset_question()
                continue

            if message.startswith("!ANSWER"):
                message = message.replace("!ANSWER", "").strip()

            # передаём в общий менеджер голосов
            accepted = vote_manager.accept_vote('twitch', username, message)
            if accepted:
                print(f"✅ {username} → {message}")
                print(f"📊 {dict(vote_manager.answers)}")

        except Exception:
            pass
