@echo off
title bot.py
echo Starting Discord Bot...

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Run the bot
python bot.py

:: Keep the window open if there's an error
pause