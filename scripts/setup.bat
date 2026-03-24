@echo off
cd /d "%~dp0\.."
echo Setting up Discord Bot...

:: Create virtual environment if it doesn't exist
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Upgrade pip
python -m pip install --upgrade pip

:: Install requirements
echo Installing dependencies...
pip install -r requirements.txt

:: Create .env file if it doesn't exist
if not exist .env (
    echo Creating .env file...
    echo DISCORD_TOKEN=your_token_here > .env
    echo.
    echo IMPORTANT: Please follow these steps to get your bot token:
    echo 1. Go to https://discord.com/developers/applications
    echo 2. Select your application
    echo 3. Go to the "Bot" section
    echo 4. Click "Reset Token" if needed
    echo 5. Copy the token and paste it in the .env file
    echo 6. Replace "your_token_here" with your actual token
    echo.
    echo After setting up the token, run start.bat to start the bot
    pause
    exit
)

echo Setup complete! Run start.bat to start the bot.
pause 