@echo off
cd /d "%~dp0\.."
chcp 65001 >nul
cls

echo ==========================================
echo Building Discord Bot Executable Package
echo ==========================================
echo.

set "SOURCE_DIR=%~dp0"
set "DIST_DIR=%SOURCE_DIR%dist\DiscordBot"

:: Clean old build
if exist "%DIST_DIR%" (
    echo Cleaning old build...
    rmdir /s /q "%DIST_DIR%"
)

:: Run PyInstaller
echo.
echo [Step 1] Running PyInstaller...
echo รอสักครู่ (อาจใช้เวลา 3-10 นาที)...
echo.

pyinstaller DiscordBot.spec --clean --noconfirm

if errorlevel 1 (
    echo ❌ PyInstaller failed!
    echo กรุณาตรวจสอบ error ข้างต้น
    pause
    exit /b 1
)

echo ✅ PyInstaller build complete!

:: Create necessary directories
echo.
echo [Step 2] Creating directories...
mkdir "%DIST_DIR%\cogs" 2>nul
mkdir "%DIST_DIR%\data" 2>nul
mkdir "%DIST_DIR%\logs" 2>nul
mkdir "%DIST_DIR%\music" 2>nul
mkdir "%DIST_DIR%\music\downloads" 2>nul
mkdir "%DIST_DIR%\ffmpeg" 2>nul

:: Copy cogs
echo [Step 3] Copying cogs...
xcopy "%SOURCE_DIR%cogs\*.py" "%DIST_DIR%\cogs\" /Y /Q >nul

:: Copy data files (but not .db files)
echo [Step 4] Copying data files...
if exist "%SOURCE_DIR%data" (
    for %%f in ("%SOURCE_DIR%data\*") do (
        if not "%%~xf"==".db" (
            copy "%%f" "%DIST_DIR%\data\" >nul 2>&1
        )
    )
)

:: Copy ffmpeg
echo [Step 5] Copying ffmpeg...
if exist "%SOURCE_DIR%ffmpeg" (
    xcopy "%SOURCE_DIR%ffmpeg\*" "%DIST_DIR%\ffmpeg\" /E /I /Y /Q >nul 2>&1
)

:: Copy essential files
echo [Step 6] Copying essential files...
copy "%SOURCE_DIR%.env.example" "%DIST_DIR%\" >nul 2>&1
copy "%SOURCE_DIR%requirements.txt" "%DIST_DIR%\" >nul 2>&1
copy "%SOURCE_DIR%README.md" "%DIST_DIR%\" >nul 2>&1

:: Create start.bat for the exe
echo [Step 7] Creating start.bat...
(
echo @echo off
cd /d "%~dp0\.."
echo chcp 65001 ^>nul
echo echo ==========================================
echo echo  Discord Bot - ygygi67
echo echo ==========================================
echo echo.
echo echo 1. สร้างไฟล์ .env จาก .env.example
echo echo 2. ใส่ Discord Token ใน .env
echo echo 3. รัน DiscordBot.exe
echo echo.
echo pause
echo DiscordBot.exe
) > "%DIST_DIR%\start.bat"

echo.
echo ==========================================
echo  ✅ Build Complete!
echo ==========================================
echo.
echo Location: %DIST_DIR%
echo.
echo Files included:
echo   - DiscordBot.exe (Main executable)
echo   - cogs/ (Commands)
echo   - data/ (Database folder)
echo   - ffmpeg/ (Audio processing)
echo   - .env.example (Template)
echo   - start.bat (Quick start script)
echo.
echo To share:
echo   1. Zip the DiscordBot folder
echo   2. Remove .env if exists before sharing
echo   3. Tell users to create their own .env
echo.

pause

