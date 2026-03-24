@echo off
cd /d "%~dp0\.."
echo Fixing Matplotlib Font Cache...

:: Remove matplotlib cache to prevent freezing
rmdir /s /q "%USERPROFILE%\.matplotlib" 2>nul
rmdir /s /q "%APPDATA%\matplotlib" 2>nul

echo Matplotlib cache cleared!
echo.
echo Starting bot...
python bot.py

pause
