#!/bin/bash

# Load credentials
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    echo "Error: .env file not found!"
    exit 1
fi

# Start the bot
python3 bot.py "$BOT_TOKEN" "$CHAT_ID"
