@echo off
cd /d "%~dp0\.."
chcp 65001 >nul
cls

echo ==========================================
echo  GitHub Push Helper - Discord Bot
echo ==========================================
echo.

:: Check if git is installed
git --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Git ไม่ได้ติดตั้ง กรุณาติดตั้ง Git ก่อน
    echo Download: https://git-scm.com/download/win
    pause
    exit /b 1
)

echo ✅ Git พร้อมใช้งาน

:: Check if already a git repo
if exist ".git" (
    echo ✅ Git repository มีอยู่แล้ว
    goto :menu
) else (
    echo 📝 สร้าง Git repository ใหม่...
    git init
    git branch -M main
    echo ✅ Repository สร้างสำเร็จ
)

:menu
cls
echo ==========================================
echo  GitHub Push Helper - Discord Bot
echo ==========================================
echo.
echo  [1] ตรวจสอบไฟล์ก่อนอัพ (Safety Check)
echo  [2] ดูสถานะไฟล์ (Git Status)
echo  [3] อัพโหลดขึ้น GitHub (Push)
echo  [4] ตั้งค่า GitHub Repository URL
echo  [5] ออก (Exit)
echo.
set /p choice="เลือก (1-5): "

if "%choice%"=="1" goto :safety_check
if "%choice%"=="2" goto :git_status
if "%choice%"=="3" goto :push_to_github
if "%choice%"=="4" goto :set_remote
if "%choice%"=="5" goto :end
goto :menu

:safety_check
cls
echo ==========================================
echo  🔒 Safety Check - ตรวจสอบความปลอดภัย
echo ==========================================
echo.

set SAFE=1

:: Check for .env
echo [1/6] ตรวจสอบ .env...
if exist ".env" (
    echo    ⚠️  พบไฟล์ .env (Token อาจหลุดได้!)
    echo    💡 แนะนำ: ตรวจสอบว่า .env อยู่ใน .gitignore
    set SAFE=0
) else (
    echo    ✅ ไม่พบไฟล์ .env (ปลอดภัย)
)

:: Check .gitignore exists
echo [2/6] ตรวจสอบ .gitignore...
if exist ".gitignore" (
    echo    ✅ มีไฟล์ .gitignore
    
    :: Check if .env is in .gitignore
    findstr /C:".env" .gitignore >nul
    if errorlevel 1 (
        echo    ⚠️  .env ไม่ได้อยู่ใน .gitignore!
        set SAFE=0
    ) else (
        echo    ✅ .env อยู่ใน .gitignore
    )
) else (
    echo    ❌ ไม่มีไฟล์ .gitignore!
    echo    💡 สร้างไฟล์ .gitignore ก่อนอัพ
    set SAFE=0
)

:: Check for token files
echo [3/6] ตรวจสอบไฟล์ที่อาจมี Token...
for %%f in ("*token*.txt" "*Token*.txt" "DISCORD TOKEN.txt") do (
    if exist "%%f" (
        echo    ⚠️  พบไฟล์ที่อาจมี Token: %%f
        set SAFE=0
    )
)
if %SAFE%==1 echo    ✅ ไม่พบไฟล์ Token

:: Check for database files
echo [4/6] ตรวจสอบ Database...
for %%f in (*.db *.sqlite *.sqlite3) do (
    if exist "%%f" (
        echo    ⚠️  พบไฟล์ Database: %%f
        echo    💡 Database ไม่ควรอัพขึ้น Git
    )
)
echo    ✅ ตรวจสอบ Database เสร็จสิ้น

:: Check for logs
echo [5/6] ตรวจสอบ Logs...
if exist "logs" (
    echo    ⚠️  พบโฟลเดอร์ logs/
    echo    💡 Logs ไม่ควรอัพขึ้น Git
)

:: Check for build/dist
echo [6/6] ตรวจสอบ Build Files...
if exist "dist" (
    echo    ⚠️  พบโฟลเดอร์ dist/
)
if exist "build" (
    echo    ⚠️  พบโฟลเดอร์ build/
)

:: Summary
echo.
echo ==========================================
if %SAFE%==1 (
    echo ✅ ผ่านการตรวจสอบความปลอดภัย!
    echo ไฟล์พร้อมอัพโหลดขึ้น GitHub
) else (
    echo ⚠️  พบปัญหาความปลอดภัย!
    echo กรุณาแก้ไขก่อนอัพโหลด
)
echo ==========================================
echo.
pause
goto :menu

:git_status
cls
echo ==========================================
echo  📊 Git Status
echo ==========================================
echo.
git status
echo.
echo ==========================================
echo.
pause
goto :menu

:set_remote
cls
echo ==========================================
echo  🔗 ตั้งค่า GitHub Repository
echo ==========================================
echo.
echo วิธีสร้าง Repository บน GitHub:
echo 1. ไปที่ https://github.com/new
echo 2. ใส่ชื่อ Repository (เช่น: discord-bot)
echo 3. เลือก Public หรือ Private
echo 4. อย่าเพิ่ม README (เรามีแล้ว)
echo 5. กด Create repository
echo.
echo 6. คัดลอก URL ที่ขึ้น (เช่น: https://github.com/username/repo.git)
echo.
set /p repo_url="วาง URL ที่นี่: "

git remote add origin %repo_url% 2>nul
if errorlevel 1 (
    git remote set-url origin %repo_url%
)

echo ✅ ตั้งค่า Remote URL: %repo_url%
echo.
pause
goto :menu

:push_to_github
cls
echo ==========================================
echo  🚀 Push to GitHub
echo ==========================================
echo.

:: Safety check first
echo 🔒 ตรวจสอบความปลอดภัยก่อนอัพ...
if exist ".env" (
    echo ⚠️  ⚠️  ⚠️  ⚠️  ⚠️  ⚠️  ⚠️  ⚠️  ⚠️  ⚠️
    echo.
    echo  พบไฟล์ .env ที่อาจมี TOKEN!
    echo  หากอัพขึ้น GitHub Token จะหลุด!
    echo.
    echo ⚠️  ⚠️  ⚠️  ⚠️  ⚠️  ⚠️  ⚠️  ⚠️  ⚠️  ⚠️
    echo.
    set /p confirm="แน่ใจว่าต้องการอัพต่อ? (YES/NO): "
    if /I not "%confirm%"=="YES" goto :menu
)

:: Check remote
if exist ".git" (
    git remote get-url origin >nul 2>&1
    if errorlevel 1 (
        echo ❌ ยังไม่ได้ตั้งค่า GitHub URL
        echo กรุณาเลือกเมนู 4 ก่อน
        pause
        goto :menu
    )
)

:: Show what will be pushed
echo 📁 ไฟล์ที่จะอัพโหลด:
git status --short
echo.

set /p commit_msg="📝 ข้อความ Commit (บอกว่าแก้อะไร): "
if "%commit_msg%"=="" set commit_msg="Update bot files"

echo.
echo 🚀 กำลังอัพโหลด...
git add .
git commit -m "%commit_msg%"
git push -u origin main

if errorlevel 1 (
    echo.
    echo ❌ Push ไม่สำเร็จ
    echo ลอง push ด้วย force:
    echo git push -u origin main --force
) else (
    echo.
    echo ✅ อัพโหลดสำเร็จ!
    echo.
    echo ดูที่ GitHub:
    git remote get-url origin
)

echo.
pause
goto :menu

:end
cls
echo ==========================================
echo  บายบาย! 👋
echo ==========================================
echo.
timeout /t 2 >nul
exit
