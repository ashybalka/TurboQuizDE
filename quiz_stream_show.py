import asyncio
import random
import json
import re
import urllib.request
import config
import vote_manager
import io
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "1"

try:
    import websockets
except Exception:
    print("Требуется пакет 'websockets'. Установите: pip install websockets")
    raise

try:
    import edge_tts
except Exception:
    print("Требуется пакет 'edge-tts'. Установите: pip install edge-tts")
    edge_tts = None

try:
    import pygame
    import pygame._sdl2.audio as sdl2_audio
except ImportError:
    pygame = None

# -------------------------------
# Настройки
# -------------------------------
ALL_QUIZZES_FILE = "Deutsch_Quiz.txt"
OUTPUT_FILE = "quiz.txt"
ANSWER_FILE = "answer.txt"    # файл для правильного ответа
QUIZ_INTERVAL = 60            # время между вопросами
ANSWER_DELAY = 50             # время до показа правильного ответа
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

# vote state now in vote_manager

async def ws_handler(websocket, path=None):
    clients.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                # Обработка голосов от внешнего скрипта chat_listener.py
                if data.get("type") == "remote_vote":
                    source = data.get("source", "unknown")
                    username = data.get("username")
                    msg = data.get("message")
                    accepted = vote_manager.accept_vote(source, username, msg)
                    if accepted:
                        print(f"✅ [{source}] {username} → {msg}")
                        await broadcast_votes_once()
            except Exception:
                pass
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

    for c in list(clients):
        t = asyncio.create_task(_send_safe(c))
        background_tasks.add(t)
        t.add_done_callback(background_tasks.discard)

# Broadcast current vote counts and percentages to connected clients
async def broadcast_votes_once():
    counts, percentages, total = vote_manager.get_counts_and_percentages()
    payload = json.dumps({"type": "votes", "counts": counts, "percentages": percentages, "total": total})
    await broadcast(payload)

async def broadcast_votes_periodic(interval=1.0):
    while True:
        try:
            await broadcast_votes_once()
        except Exception:
            pass
        await asyncio.sleep(interval)

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
# Озвучка через Edge TTS
# -------------------------------
def setup_local_audio():
    if not pygame:
        return

    device_name = getattr(config, 'TTS_DEVICE_NAME', None)
    if not device_name:
        return

    try:
        pygame.init()
        pygame.mixer.init()
        
        devices = sdl2_audio.get_audio_device_names(False)
        target = next((d for d in devices if device_name.lower() in d.lower()), None)
        
        if target:
            print(f"🔊 Вывод звука на устройство: {target}")
            pygame.mixer.quit()
            pygame.mixer.init(devicename=target)
        else:
            print(f"⚠️ Устройство '{device_name}' не найдено. Доступные: {devices}")
    except Exception as e:
        print(f"Ошибка настройки аудио: {e}")

async def play_local_audio(audio_data: bytes):
    """Проигрывает аудио локально и ждет завершения"""
    if pygame and pygame.mixer.get_init():
        try:
            pygame.mixer.music.load(io.BytesIO(audio_data))
            pygame.mixer.music.play()
            # Ждем окончания, чтобы губы аватара двигались синхронно и фразы не накладывались
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Ошибка воспроизведения: {e}")

async def speak_text(text: str, voice: str = "de-DE-KatjaNeural"):
    """Генерирует аудио через Edge TTS и возвращает (base64, bytes)"""
    if not edge_tts:
        return None, None
    try:
        communicate = edge_tts.Communicate(text, voice)
        import base64
        
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        
        # Кодируем в base64 для отправки через WebSocket
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        return audio_base64, audio_data
    except Exception as e:
        print(f"Ошибка генерации аудио: {e}")
        return None, None

async def speak_question_and_answers(quiz_text: str):
    """Генерирует аудио для вопроса и вариантов ответов, отправляет в браузер"""
    if not edge_tts:
        return
    
    lines = [line.strip() for line in quiz_text.splitlines() if line.strip() and "✅" not in line]
    
    # Извлекаем вопрос и варианты ответов
    question = ""
    options = []
    
    for line in lines:
        if line.startswith("Thema:"):
            continue
        # Проверяем, является ли строка вариантом ответа (A), B), C), D))
        if re.match(r'^[A-D]\)\s*', line, re.IGNORECASE):
            options.append(line)
        elif not question and line:
            question = line
    
    # Генерируем и отправляем аудио для вопроса
    if question:
        print(f"🔊 Генерирую аудио для вопроса: {question}")
        audio_base64, audio_bytes = await speak_text(question)
        if audio_base64:
            try:
                await broadcast(json.dumps({
                    "type": "audio",
                    "audio": audio_base64,
                    "text": question,
                    "isQuestion": True
                }))
            except Exception as e:
                print(f"Ошибка отправки аудио: {e}")
            
            # Проигрываем локально ПОСЛЕ отправки в вебсокет
            if audio_bytes:
                await play_local_audio(audio_bytes)

        # Пауза после вопроса перед вариантами ответов
        await asyncio.sleep(1.5)
    
    # Генерируем и отправляем аудио для вариантов ответов
    for option in options:
        print(f"🔊 Генерирую аудио для варианта: {option}")
        audio_base64, audio_bytes = await speak_text(option)
        if audio_base64:
            try:
                await broadcast(json.dumps({
                    "type": "audio",
                    "audio": audio_base64,
                    "text": option,
                    "isQuestion": False
                }))
            except Exception as e:
                print(f"Ошибка отправки аудио: {e}")
            
            if audio_bytes:
                await play_local_audio(audio_bytes)

        await asyncio.sleep(0.3)  # Пауза между вариантами

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
    # Award points to users who answered correctly
    try:
        if correct_letter:
            voters = vote_manager.get_voters_for_letter(correct_letter)
            if voters:
                vote_manager.award_points(voters, points=1)
    except Exception:
        pass
    
    # Обновляем лидерборд из базы при каждом ответе
    try:
        leaderboard = vote_manager.get_top_scores(10)
        await broadcast(json.dumps({"type": "scores", "leaderboard": leaderboard}))
    except Exception:
        pass
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
background_tasks = set()

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

        # Сбрасываем счётчики голосов перед показом нового вопроса
        vote_manager.reset_question()
        # Отправляем вопрос как JSON (включая номер и общее количество)
        lines = [l for l in quiz.splitlines() if l.strip() and "✅" not in l]
        question_text = "\n".join(lines)
        meta = {"type": "question", "text": question_text, "current": len(used_indices), "total": len(valid_idxs)}
        try:
            # send initial zeroed votes so overlay shows 0% immediately
            await broadcast(json.dumps(meta))
            await broadcast_votes_once()
            # Отправляем актуальный лидерборд в начале каждого вопроса
            leaderboard = vote_manager.get_top_scores(10)
            await broadcast(json.dumps({"type": "scores", "leaderboard": leaderboard}))
        except Exception:
            pass

        # Озвучиваем вопрос и варианты ответов
        try:
            t = asyncio.create_task(speak_question_and_answers(quiz))
            background_tasks.add(t)
            t.add_done_callback(background_tasks.discard)
        except Exception as e:
            print(f"Ошибка запуска озвучки: {e}")

        await show_question_with_answer(quiz)

        # Ненужный дополнительный sleep удалён — показ правильного ответа
        # и отправка таймеров до следующего вопроса уже выполняются в
        # show_question_with_answer(), поэтому здесь спать не нужно.

async def main():
    setup_local_audio()
    ws_server = await websockets.serve(ws_handler, WS_HOST, WS_PORT)
    print(f"WebSocket server running on ws://{WS_HOST}:{WS_PORT}")
    # start background IRC listener and periodic vote broadcaster
    try:
        for coro in [broadcast_votes_periodic(1.0)]:
            t = asyncio.create_task(coro)
            background_tasks.add(t)
            t.add_done_callback(background_tasks.discard)
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