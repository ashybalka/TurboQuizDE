import asyncio
import random
import json
import re

try:
    import websockets
except Exception:
    print("Требуется пакет 'websockets'. Установите: pip install websockets")
    raise

# -------------------------------
# Настройки
# -------------------------------
ALL_QUIZZES_FILE = "Deutsch_Quiz.txt"
OUTPUT_FILE = "quiz.txt"
ANSWER_FILE = "answer.txt"    # файл для правильного ответа
QUIZ_INTERVAL = 30            # время между вопросами
ANSWER_DELAY = 20             # время до показа правильного ответа
TIMER_START = ANSWER_DELAY    # таймер обратного отсчёта

# Установите в None чтобы показывать все квизы,
# или в строку, например 'A1' или 'Thema: Geographie' чтобы фильтровать
QUIZ_FILTER = None

# -------------------------------
# Загрузка квизов
# -------------------------------
with open(ALL_QUIZZES_FILE, "r", encoding="utf-8") as f:
    content = f.read()

all_quizzes = content.strip().split("\n\n⏳ Antworte im Chat!\n\n")
all_quizzes = [q.strip() for q in all_quizzes if q.strip()]
print(f"Загружено квизов: {len(all_quizzes)}")

used_indices = set()

# -------------------------------
# WebSocket clients
# -------------------------------
WS_HOST = "0.0.0.0"
WS_PORT = 8765
clients = set()

async def ws_handler(websocket, path=None):
    clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        clients.remove(websocket)

async def broadcast(msg: str):
    if not clients:
        return

    async def _send_safe(c):
        try:
            await c.send(msg)
        except Exception:
            try:
                clients.discard(c)
            except Exception:
                pass

    tasks = [asyncio.create_task(_send_safe(c)) for c in list(clients)]
    if tasks:
        await asyncio.gather(*tasks)

# -------------------------------
# Файловые операции (синхронные)
# -------------------------------
def write_answer(text):
    with open(ANSWER_FILE, "w", encoding="utf-8") as f:
        f.write(text)
def clear_answer():
    with open(ANSWER_FILE, "w", encoding="utf-8") as f:
        f.write("")

# -------------------------------
# Логика показа вопроса и вещания таймера
# -------------------------------
async def show_question_with_answer(quiz_text):
    lines = quiz_text.splitlines()

    # Извлекаем правильный ответ из строки с "✅"
    correct_answer_line = next((line for line in lines if "✅" in line), None)
    correct_letter = None
    correct_text = None
    if correct_answer_line:
        # убираем чекмарку и пробелы
        clean = correct_answer_line.replace('✅', '').strip()
        # попытка вытащить букву формата 'A) текст'
        m = re.match(r'^([A-Z])\)\s*(.*)$', clean)
        if m:
            correct_letter = m.group(1)
            correct_text = m.group(2).strip()
        else:
            # если формат другой — используем весь текст как правильный ответ
            correct_text = clean
    else:
        correct_text = "Nicht gefunden"

    # Убираем строку с правильным ответом из вопроса
    question_lines = [line for line in lines if "✅" not in line]
    question_text = "\n".join(question_lines)

    # Показ вопроса (без правильного ответа) — вещаем по WebSocket
    # Подготовим мета-информацию (текущий/total будут передаваться из main_loop)
    # clear answer file
    clear_answer()
    print(f"Показан вопрос: {question_lines[1] if len(question_lines) > 1 else 'N/A'}")

    # broadcast question will be sent by caller with metadata

    # Таймер обратного отсчета — вещаем каждую секунду по WebSocket
    for sec in range(TIMER_START, 0, -1):
        try:
            await broadcast(json.dumps({"type": "timer", "seconds": sec}))
        except Exception:
            pass
        await asyncio.sleep(1)

    # Показ правильного ответа в отдельном файле
    # Подготовим текст и запишем в файл
    answer_text = f"✅ Richtige Antwort: {correct_text}"
    write_answer(answer_text)
    try:
        await broadcast(json.dumps({"type": "answer", "text": answer_text, "correct_text": correct_text, "correct_letter": correct_letter}))
    except Exception:
        pass
    print(f"Показан правильный ответ: {correct_text}")
    # После показа правильного ответа — вещаем таймер до следующего вопроса
    post_wait = QUIZ_INTERVAL - ANSWER_DELAY
    if post_wait > 0:
        for sec in range(post_wait, 0, -1):
            try:
                await broadcast(json.dumps({"type": "timer", "seconds": sec, "phase": "answer_wait"}))
            except Exception:
                pass
            await asyncio.sleep(1)

# -------------------------------
# Основной async цикл
# -------------------------------
async def main_loop():
    global used_indices
    while True:
        # Формируем список валидных индексов по фильтру (если задан)
        if QUIZ_FILTER:
            valid_idxs = [i for i, q in enumerate(all_quizzes) if QUIZ_FILTER in q]
            if not valid_idxs:
                print(f"Фильтр '{QUIZ_FILTER}' не дал совпадений. Будут использованы все квизы.")
                valid_idxs = list(range(len(all_quizzes)))
        else:
            valid_idxs = list(range(len(all_quizzes)))

        # Сбрасываем историю только когда все подходящие вопросы показаны
        if len(used_indices) == len(valid_idxs):
            print("Все вопросы показаны. Сбрасываем историю...")
            used_indices.clear()

        available = [i for i in valid_idxs if i not in used_indices]
        idx = random.choice(available)
        used_indices.add(idx)
        quiz = all_quizzes[idx]

        # Отправляем вопрос как JSON (включая номер и общее количество)
        lines = [l for l in quiz.splitlines() if l.strip() and "✅" not in l]
        question_text = "\n".join(lines)
        meta = {"type": "question", "text": question_text, "current": len(used_indices), "total": len(valid_idxs)}
        try:
            await broadcast(json.dumps(meta))
        except Exception:
            pass

        await show_question_with_answer(quiz)

        # Ненужный дополнительный sleep удалён — показ правильного ответа
        # и отправка таймеров до следующего вопроса уже выполняются в
        # show_question_with_answer(), поэтому здесь спать не нужно.

async def main():
    ws_server = await websockets.serve(ws_handler, WS_HOST, WS_PORT)
    print(f"WebSocket server running on ws://{WS_HOST}:{WS_PORT}")
    try:
        await main_loop()
    except asyncio.CancelledError:
        pass
    finally:
        ws_server.close()
        await ws_server.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Скрипт остановлен пользователем.")