@echo off
echo Starting Discord Bot...

:: Activate virtual environment
call .venv\Scripts\activate.bat

echo Installing Libraries...
pip install -r requirements.txt

:: Run the bot
python bot.py

:: Keep the window open if there's an error
pause 