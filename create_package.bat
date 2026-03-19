@echo off
chcp 65001 >nul
cls

echo ==========================================
echo  Discord Bot - Package Builder
echo ==========================================
echo.

set "SOURCE=%~dp0"
set "BUILD_DIR=%SOURCE%dist\DiscordBot"
set "PACKAGE_DIR=%SOURCE%dist\DiscordBot_Package"
set "FINAL_ZIP=%SOURCE%dist\DiscordBot_Standalone.zip"

:: Clean old build
if exist "%PACKAGE_DIR%" rmdir /s /q "%PACKAGE_DIR%"
if exist "%FINAL_ZIP%" del "%FINAL_ZIP%"

:: Create package structure
mkdir "%PACKAGE_DIR%\DiscordBot"
mkdir "%PACKAGE_DIR%\DiscordBot\cogs"
mkdir "%PACKAGE_DIR%\DiscordBot\data"
mkdir "%PACKAGE_DIR%\DiscordBot\logs"
mkdir "%PACKAGE_DIR%\DiscordBot\music"
mkdir "%PACKAGE_DIR%\DiscordBot\ffmpeg"

echo [1/4] Copying executable and core files...
copy "%BUILD_DIR%\DiscordBot.exe" "%PACKAGE_DIR%\DiscordBot\" >nul
copy "%SOURCE%\.env" "%PACKAGE_DIR%\DiscordBot\" >nul 2>&1
copy "%SOURCE%\requirements.txt" "%PACKAGE_DIR%\DiscordBot\" >nul
copy "%SOURCE%\README.md" "%PACKAGE_DIR%\DiscordBot\" >nul 2>&1

echo [2/4] Copying cogs...
xcopy "%SOURCE%\cogs\*.py" "%PACKAGE_DIR%\DiscordBot\cogs\" /Y >nul 2>&1

echo [3/4] Copying data folders...
xcopy "%SOURCE%\data\*" "%PACKAGE_DIR%\DiscordBot\data\" /E /I /Y >nul 2>&1
xcopy "%SOURCE%\music\*" "%PACKAGE_DIR%\DiscordBot\music\" /E /I /Y >nul 2>&1
xcopy "%SOURCE%\ffmpeg\*" "%PACKAGE_DIR%\DiscordBot\ffmpeg\" /E /I /Y >nul 2>&1

echo [4/4] Creating ZIP package...
cd /d "%SOURCE%dist"
powershell Compress-Archive -Path "DiscordBot_Package\DiscordBot" -DestinationPath "DiscordBot_Standalone.zip" -Force

echo.
echo ==========================================
echo  Package Complete!
echo ==========================================
echo.
echo Location: %FINAL_ZIP%
echo.
echo Contents:
echo   - DiscordBot.exe (Bot executable)
echo   - cogs/ (Commands)
echo   - data/ (Database)
echo   - ffmpeg/ (Audio processing)
echo   - .env (Token file - REMOVE BEFORE SHARING!)
echo   - logs/ (Will be created on first run)
echo.
echo To share with others:
echo   1. Remove .env from the zip FIRST
echo   2. Tell them to create their own .env file
echo   3. Share the zip without your token
echo.
pause
