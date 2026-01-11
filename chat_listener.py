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

def is_stream_live(username: str) -> bool:
    """Проверка, что TikTok стрим онлайн"""
    url = f"https://www.tiktok.com/@{username}/live"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            final_url = response.geturl()
            # Если в URL есть /live или video_id, считаем онлайн
            return "/live" in final_url or "video_id" in final_url
    except:
        return False


async def tiktok_listener():
    if not TikTokLiveClient:
        return
    
    tiktok_user = getattr(config, 'TIKTOK_USERNAME', None)
    if not tiktok_user:
        return
    
    # Устанавливаем API ключ глобально через WebDefaults
    eulerstream_key = getattr(config, 'EULERSTREAM_API_KEY', None)
    if eulerstream_key and WebDefaults:
        WebDefaults.tiktok_sign_api_key = eulerstream_key
        print(f"🔑 Используется EulerStream API Key")
    else:
        print(f"⚠️ API Key не найден - используется бесплатный лимит EulerStream")
        print(f"   Для увеличения лимита зарегистрируйтесь на https://www.eulerstream.com")
    
    print(f"🎵 Запуск слушателя TikTok для @{tiktok_user}...")
    
    consecutive_offline = 0
    
    while True:
        # Проверяем статус стрима перед подключением
        if not is_stream_live(tiktok_user):
            consecutive_offline += 1
            wait_time = min(RECONNECT_MAX, CHECK_INTERVAL * consecutive_offline)
            print(f"💤 Стрим @{tiktok_user} оффлайн, ждем {wait_time}s...")
            await asyncio.sleep(wait_time)
            
            if consecutive_offline > MAX_OFFLINE_RETRIES:
                print("⚠️ Слишком много оффлайн попыток, пауза 10 минут...")
                await asyncio.sleep(600)
                consecutive_offline = 0
            continue
        
        try:
            # Создаем клиента
            client = TikTokLiveClient(unique_id=tiktok_user)
            
            @client.on(CommentEvent)
            async def on_comment(event: CommentEvent):
                ts = getattr(event, 'create_time', None)
                
                # TikTok иногда присылает миллисекунды
                if ts and ts > 100000000000:
                    ts = ts / 1000
                
                # Если времени нет — берём текущее
                if not ts:
                    ts = time.time()
                
                # Получаем ID сообщения (если доступен)
                msg_id = getattr(event, 'id', None) or getattr(event, 'msg_id', None)
                
                username = event.user.nickname or event.user.unique_id
                message = event.comment
                
                time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
                print(f"[{time_str}] [TikTok] {username}: {message}")
                
                await msg_queue.put({
                    "type": "remote_vote",
                    "source": "tiktok",
                    "username": username,
                    "message": message,
                    "timestamp": ts,
                    "message_id": msg_id
                })
            
            print(f"🔗 Подключение к @{tiktok_user} через EulerStream...")
            start_time = time.time()
            consecutive_offline = 0
            
            # Запускаем клиент (синхронный вызов в async функции)
            client.run()
            
            # Если дошли сюда - стрим завершился
            duration = int(time.time() - start_time)
            print(f"📴 Стрим завершился, длительность: {duration}s")
            await asyncio.sleep(RECONNECT_BASE)
            
        except WebcastBlocked200Error:
            print("⛔ DEVICE_BLOCKED — пауза 5 минут")
            consecutive_offline = 0
            await asyncio.sleep(300)
            
        except Exception as e:
            msg = str(e)
            print(f"⚠️ TikTok ошибка: {msg}")
            
            if "RATE_LIMIT" in msg or "rate_limit" in msg:
                print("⏳ Rate limit достигнут. Пауза 10 минут...")
                consecutive_offline = 0
                await asyncio.sleep(600)
            elif "offline" in msg.lower():
                consecutive_offline += 1
                wait_time = min(RECONNECT_MAX, CHECK_INTERVAL * consecutive_offline)
                print(f"💤 Оффлайн (попытка {consecutive_offline}). Пауза {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                consecutive_offline += 1
                wait_time = min(RECONNECT_MAX, RECONNECT_BASE * (2 ** min(consecutive_offline, 7)))
                print(f"🔁 Ошибка, ждём {wait_time}s...")
                await asyncio.sleep(wait_time)

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