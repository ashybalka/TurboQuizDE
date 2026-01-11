import os

#Twitch credentials
IRC_SERVER = "irc.chat.twitch.tv"
IRC_PORT = 6667
IRC_NICK = os.environ.get("IRC_NICK", "turboquizde")
IRC_TOKEN = os.environ.get("IRC_TOKEN", "")
IRC_CHANNEL = os.environ.get("IRC_CHANNEL", "#turboquizde")

#YouTube credentials
YOUTUBE_VIDEO_ID = os.environ.get("YOUTUBE_VIDEO_ID", "")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")

#TikTok credentials
TTS_DEVICE_NAME = os.environ.get("TTS_DEVICE_NAME", "")
TIKTOK_USERNAME = os.environ.get("TIKTOK_USERNAME", "")
EULERSTREAM_API_KEY = os.environ.get("EULERSTREAM_API_KEY", "")

# General settings
BACKGROUND_MUSIC_URL = os.environ.get("BACKGROUND_MUSIC_URL", "")