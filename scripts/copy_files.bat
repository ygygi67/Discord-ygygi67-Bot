@echo off
cd /d "%~dp0\.."
chcp 65001 >nul

echo Copying files to dist\DiscordBot...

set "TARGET=%~dp0dist\DiscordBot"

:: Copy folders
xcopy "%~dp0cogs" "%TARGET%\cogs\" /E /I /Y >nul
xcopy "%~dp0data" "%TARGET%\data\" /E /I /Y >nul
xcopy "%~dp0music" "%TARGET%\music\" /E /I /Y >nul
xcopy "%~dp0music_player" "%TARGET%\music_player\" /E /I /Y >nul
xcopy "%~dp0ffmpeg" "%TARGET%\ffmpeg\" /E /I /Y >nul

:: Copy files
copy "%~dp0.env" "%TARGET%\.env" >nul 2>&1
copy "%~dp0data\channels.json" "%TARGET%\data\channels.json" >nul 2>&1
copy "%~dp0data\stats.json" "%TARGET%\data\stats.json" >nul 2>&1
copy "%~dp0data\storage.json" "%TARGET%\data\storage.json" >nul 2>&1

echo Done! Files copied to %TARGET%
pause
