@echo off
title VoiceLoggerBot
setlocal
cd /d "%~dp0"

echo =======================================
echo     Voice Logger Bot (Secretary)
echo =======================================

:: 1. Virtual Environment Check
if not exist ".venv\Scripts\python.exe" (
    echo [*] Virtual environment not found. Creating...
    python -m venv .venv
    echo [*] Installing dependencies...
    .\.venv\Scripts\pip install py-cord[voice] openai-whisper python-dotenv
)

:: 2. RUN the bot using the venv python directly
echo [*] Starting the bot...
.\.venv\Scripts\python bot.py

pause