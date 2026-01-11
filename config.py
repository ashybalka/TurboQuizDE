import os

# Central configuration for chat integrations
IRC_SERVER = "irc.chat.twitch.tv"
IRC_PORT = 6667
IRC_NICK = os.environ.get("IRC_NICK", "turboquizde")
IRC_TOKEN = os.environ.get("IRC_TOKEN", "")  # Токен берем из переменных окружения
IRC_CHANNEL = os.environ.get("IRC_CHANNEL", "#turboquizde")
YOUTUBE_VIDEO_ID = os.environ.get("YOUTUBE_VIDEO_ID", "")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
TTS_DEVICE_NAME = os.environ.get("TTS_DEVICE_NAME", "")
TIKTOK_USERNAME = os.environ.get("TIKTOK_USERNAME", "")
TIKTOK_SIGN_API_KEY = os.environ.get("TIKTOK_SIGN_API_KEY")