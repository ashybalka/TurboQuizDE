#!/bin/bash
# Запускаем основной квиз в фоновом режиме
python quiz_stream_show.py &

# Ждем пару секунд и запускаем слушателя чата
sleep 5
python chat_listener.py