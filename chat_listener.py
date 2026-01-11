import asyncio
import json
import socket
import urllib.request
import os
import time
import websockets
import config

# Пытаемся импортировать pytchat
try:
    import pytchat
except ImportError:
    pytchat = None
    print("⚠️ Pytchat не установлен. YouTube чат будет отключен.")

try:
    from TikTokLive import TikTokLiveClient
    try:
        from TikTokLive.events import CommentEvent
        from TikTokLive.client.errors import WebcastBlocked200Error
    except ImportError:
        from TikTokLive.types.events import CommentEvent
        try:
            from TikTokLive.types.errors import WebcastBlocked200Error
        except ImportError:
            class WebcastBlocked200Error(Exception): pass
except ImportError as e:
    TikTokLiveClient = None
    class WebcastBlocked200Error(Exception): pass
    print(f"⚠️ Ошибка импорта TikTokLive: {e}")
    print("⚠️ TikTok чат будет отключен. (pip install TikTokLive)")

PORT = os.environ.get("PORT", 8765)
WS_URL = f"ws://127.0.0.1:{PORT}"
msg_queue = asyncio.Queue()

async def twitch_listener():
    print("🎮 Запуск слушателя Twitch...")
    while True:
        try:
            reader, writer = await asyncio.open_connection(config.IRC_SERVER, config.IRC_PORT)
            
            async def send_line(s):
                writer.write(f"{s}\r\n".encode())
                await writer.drain()

            await send_line(f"PASS {config.IRC_TOKEN}")
            await send_line(f"NICK {config.IRC_NICK}")
            await send_line(f"JOIN {config.IRC_CHANNEL}")
            print("🎮 Twitch подключен")

            while True:
                raw = await reader.readline()
                if not raw:
                    print("⚠️ Twitch соединение разорвано")
                    break
                
                line = raw.decode('utf-8', errors='ignore').strip()

                if line.startswith('PING'):
                    await send_line('PONG :tmi.twitch.tv')
                    continue

                if 'PRIVMSG' not in line:
                    continue

                try:
                    # Парсим сообщение
                    parts = line.split(':', 2)
                    if len(parts) < 3: continue
                    
                    username = line.split('!')[0][1:]
                    message = parts[2].strip()
                    
                    # Отправляем в очередь для пересылки
                    await msg_queue.put({
                        "type": "remote_vote",
                        "source": "twitch",
                        "username": username,
                        "message": message,
                        "timestamp": time.time()
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"⚠️ Ошибка Twitch: {e}. Реконнект через 5с...")
            await asyncio.sleep(5)

async def youtube_listener():
    if not pytchat:
        return
    
    print("🔴 Запуск слушателя YouTube...")
    while True:
        video_id = getattr(config, 'YOUTUBE_VIDEO_ID', None)
        if not video_id:
            channel_id = getattr(config, 'YOUTUBE_CHANNEL_ID', None)
            if channel_id:
                try:
                    url = f"https://www.youtube.com/channel/{channel_id}/live"
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req) as response:
                        final_url = response.geturl()
                        if "v=" in final_url:
                            video_id = final_url.split("v=")[1].split("&")[0]
                except Exception:
                    pass
        
        if not video_id:
            await asyncio.sleep(30)
            continue

        print(f"🔴 Подключение к YouTube ID: {video_id}")
        try:
            chat = pytchat.create(video_id=video_id)
            while chat.is_alive():
                for c in chat.get().sync_items():
                    await msg_queue.put({
                        "type": "remote_vote",
                        "source": "youtube",
                        "username": c.author.name,
                        "message": c.message,
                        "timestamp": time.time(),
                        "message_id": c.id  # Добавляем ID сообщения
                    })
                await asyncio.sleep(1)
            print("🔴 YouTube чат отключился")
        except Exception as e:
            print(f"⚠️ Ошибка YouTube: {e}")
        
        await asyncio.sleep(10)

async def tiktok_listener():
    if not TikTokLiveClient:
        return
    
    tiktok_user = getattr(config, 'TIKTOK_USERNAME', None)
    if not tiktok_user:
        return
    
    # Получаем Webhook Secret от EulerStream
    webhook_secret = getattr(config, 'EULERSTREAM_WEBHOOK_SECRET', None)
    
    if webhook_secret:
        print(f"🔑 Используется EulerStream Webhook Secret")
        # Библиотека TikTokLive автоматически использует бесплатный сервис EulerStream
        # Webhook secret нужен только для получения уведомлений через webhooks
    else:
        print(f"⚠️ Webhook Secret не найден - используется бесплатный лимит EulerStream")
        print(f"   Для увеличения лимита зарегистрируйтесь на https://www.eulerstream.com")

    print(f"🎵 Запуск слушателя TikTok для @{tiktok_user}...")
    
    consecutive_offline_errors = 0
    
    while True:
        try:
            # Создаем клиента (ключ читается из переменной окружения автоматически)
            client = TikTokLiveClient(unique_id=tiktok_user)

            @client.on(CommentEvent)
            async def on_comment(event: CommentEvent):
                ts = getattr(event, 'create_time', None)
                if ts and ts > 100000000000:
                    ts = ts / 1000.0
                
                # Получаем ID сообщения (если доступен)
                msg_id = getattr(event, 'id', None) or getattr(event, 'msg_id', None)

                await msg_queue.put({
                    "type": "remote_vote",
                    "source": "tiktok",
                    "username": event.user.nickname or event.user.unique_id,
                    "message": event.comment,
                    "timestamp": ts,
                    "message_id": msg_id
                })
            
            print("🔗 Подключение к TikTok стриму...")
            start_time = time.time()
            await client.start()
            
            # Если мы здесь - значит стрим закончился или соединение разорвано
            consecutive_offline_errors = 0
            duration = int(time.time() - start_time)
            if duration < 10:
                print(f"⚠️ TikTok соединение разорвано слишком быстро ({duration}с). Пауза 5с...")
                await asyncio.sleep(5)
            else:
                print(f"📴 TikTok соединение закрыто (длительность: {duration}с). Реконнект...")
            
        except WebcastBlocked200Error:
            print(f"⚠️ TikTok: Доступ заблокирован (DEVICE_BLOCKED). Пауза 5 минут...")
            await asyncio.sleep(300)
            consecutive_offline_errors = 0
            continue
            
        except Exception as e:
            error_msg = str(e)
            
            # Если это rate limit - ждем ДОЛГО
            if "RATE_LIMIT" in error_msg or "rate_limit" in error_msg:
                print("⏳ Rate limit достигнут. Пауза 10 минут...")
                consecutive_offline_errors = 0
                await asyncio.sleep(600)
                continue
            
            # Если пользователь оффлайн
            if "offline" in error_msg.lower():
                consecutive_offline_errors += 1
                
                # Адаптивная пауза: чем больше ошибок подряд, тем дольше ждем
                if consecutive_offline_errors < 3:
                    wait_time = 60  # 1 минута
                elif consecutive_offline_errors < 10:
                    wait_time = 180  # 3 минуты
                else:
                    wait_time = 600  # 10 минут
                
                print(f"💤 Оффлайн (попытка {consecutive_offline_errors}). Пауза {wait_time//60} мин...")
                await asyncio.sleep(wait_time)
                continue
            
            # Другие ошибки
            print(f"⚠️ TikTok ошибка: {error_msg}")
            consecutive_offline_errors = 0
        
        # Обычная пауза между переподключениями (если стрим нормально завершился)
        await asyncio.sleep(5)

async def ws_sender():
    """Пересылает сообщения из очереди в основной скрипт через WebSocket"""
    while True:
        try:
            print(f"🔌 Подключение к основному скрипту {WS_URL}...")
            async with websockets.connect(WS_URL) as ws:
                print("✅ Связь с основным скриптом установлена")
                
                # Фоновая задача для чтения сообщений (чтобы не переполнялся буфер)
                async def reader():
                    try:
                        async for _ in ws: pass
                    except: pass
                
                reader_task = asyncio.create_task(reader())
                try:
                    while True:
                        data = await msg_queue.get()
                        await ws.send(json.dumps(data))
                        msg_queue.task_done()
                finally:
                    reader_task.cancel()
        except Exception:
            await asyncio.sleep(3)

async def main():
    print("\n--- Выбор сервисов для запуска ---")

    # Автоматическое определение на основе наличия настроек в config.py (env vars)
    use_twitch = bool(config.IRC_TOKEN and config.IRC_NICK)
    print(f"🎮 Twitch: {'ВКЛ' if use_twitch else 'ВЫКЛ (нет токена)'}")

    use_youtube = False
    if pytchat:
        use_youtube = bool(config.YOUTUBE_VIDEO_ID or config.YOUTUBE_CHANNEL_ID)
        print(f"🔴 YouTube: {'ВКЛ' if use_youtube else 'ВЫКЛ (нет ID)'}")

    use_tiktok = False
    tt_user = getattr(config, 'TIKTOK_USERNAME', None)
    if TikTokLiveClient and tt_user:
        use_tiktok = True
        print(f"🎵 TikTok: ВКЛ (@{tt_user})")

    print("-" * 30)

    tasks = [ws_sender()]
    if use_twitch:
        tasks.append(twitch_listener())
    if use_youtube:
        tasks.append(youtube_listener())
    if use_tiktok:
        tasks.append(tiktok_listener())
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass