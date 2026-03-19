@echo off
chcp 65001 >nul

set "SOURCE_DIR=%~dp0"
set "DIST_DIR=%SOURCE_DIR%dist\DiscordBot"

echo ==========================================
echo Building Discord Bot Executable Package
echo ==========================================
echo.

:: Clean old build and recreate
if exist "%DIST_DIR%" (
    echo Cleaning old build...
    rmdir /s /q "%DIST_DIR%"
)

echo.
echo Please wait for PyInstaller to complete...
echo Then run this script again to copy files.
echo.
pause
