import asyncio
import os
import time
import urllib.request

from datetime import datetime

from TikTokLive import TikTokLiveClient
from TikTokLive.client.web.web_settings import WebDefaults
from TikTokLive.events import CommentEvent
from TikTokLive.client.errors import WebcastBlocked200Error

# ======================
# НАСТРОЙКИ
# ======================
TIKTOK_USERNAME = "turbotechde"
EULERSTREAM_API_KEY = "euler_MjViMDQ0YTExMTc5N2U1MDQ2NmQ3MGEyNThlMTE1OTc4YzIzMDNmNWM1NDViNzE0MmM3NmE5"  
RECONNECT_BASE = 30      # базовая пауза между реконнектами (сек)
RECONNECT_MAX = 600      # макс пауза (10 мин)
MAX_OFFLINE_RETRIES = 10


# ======================
# ГЛОБАЛЬНАЯ УСТАНОВКА API KEY
# ======================
WebDefaults.tiktok_sign_api_key = EULERSTREAM_API_KEY


# ======================
# Проверка, что стрим онлайн
# ======================
def is_stream_live(username: str) -> bool:
    url = f"https://www.tiktok.com/@{username}/live"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as response:
            final_url = response.geturl()
            # Если в URL есть /live или video_id, считаем онлайн
            return "/live" in final_url or "video_id" in final_url
    except:
        return False

# ======================
# Главная функция
# ======================
def main():
    consecutive_offline = 0

    while True:
        if not is_stream_live(TIKTOK_USERNAME):
            consecutive_offline += 1
            wait_time = min(RECONNECT_MAX, CHECK_INTERVAL * consecutive_offline)
            print(f"💤 Стрим оффлайн, ждем {wait_time}s...")
            time.sleep(wait_time)
            if consecutive_offline > MAX_OFFLINE_RETRIES:
                print("⚠️ Слишком много оффлайн попыток, пауза 10 минут...")
                time.sleep(600)
                consecutive_offline = 0
            continue

        try:
            # Создаем клиент один раз
            client = TikTokLiveClient(unique_id=TIKTOK_USERNAME)

            @client.on(CommentEvent)
            async def on_comment(event: CommentEvent):
                ts = getattr(event, "create_time", None)

                # TikTok иногда присылает миллисекунды
                if ts and ts > 100000000000:
                    ts = ts / 1000

                # Если времени нет — берём текущее
                if ts:
                    time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
                else:
                    time_str = datetime.now().strftime("%H:%M:%S")

                username = event.user.nickname or event.user.unique_id
                message = event.comment

                print(f"[{time_str}] [TikTok] {username}: {message}")    

            print(f"🔗 Подключение к @{TIKTOK_USERNAME} через EulerStream API Key...")
            start_time = time.time()
            consecutive_offline = 0

            client.run()

            duration = int(time.time() - start_time)
            print(f"📴 Стрим завершился, длительность: {duration}s")
            time.sleep(RECONNECT_BASE)

        except WebcastBlocked200Error:
            print("⛔ DEVICE_BLOCKED — пауза 5 минут")
            consecutive_offline = 0
            time.sleep(300)

        except Exception as e:
            msg = str(e)
            print(f"⚠️ TikTok ошибка: {msg}")

            if "RATE_LIMIT" in msg:
                print("⏳ Rate limit достигнут. Пауза 10 минут...")
                consecutive_offline = 0
                time.sleep(600)
            else:
                consecutive_offline += 1
                wait_time = min(RECONNECT_MAX, RECONNECT_BASE * (2 ** consecutive_offline))
                print(f"🔁 Ошибка, ждём {wait_time}s...")
                time.sleep(wait_time)

# ======================
# Запуск
# ======================
if __name__ == "__main__":
    if not EULERSTREAM_API_KEY:
        raise RuntimeError("❌ Пожалуйста, установите EULERSTREAM_API_KEY в окружении")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹ Остановлено пользователем")