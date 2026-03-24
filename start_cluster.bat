@echo off
chcp 65001 >nul
cls

echo ==========================================
echo  Discord Bot - Distributed Cluster Manager
echo ==========================================
echo.
echo เลือกโหมดการทำงาน:
echo.
echo  [1] Standalone Mode (เหมือนเดิม - 1 บอท)
echo  [2] Master Mode (ควบคุมหลาย Shards)
echo  [3] Worker Mode (ประมวลผลงานหนัก)
echo  [4] Cluster Mode (Master + Workers ในเครื่องเดียว)
echo.
set /p choice="เลือก (1-4): "

if "%choice%"=="1" goto standalone
if "%choice%"=="2" goto master
if "%choice%"=="3" goto worker
if "%choice%"=="4" goto cluster
goto end

:standalone
cls
echo ==========================================
echo  Standalone Mode
echo ==========================================
set BOT_MODE=standalone
python bot.py
goto end

:master
cls
echo ==========================================
echo  Master Mode - Sharding Configuration
echo ==========================================
echo.
set /p shards="จำนวน Shards ทั้งหมด (เว้นว่าง = Auto): "
set /p cluster_id="Cluster ID ของเครื่องนี้ (0, 1, 2...): "
set /p total_clusters="จำนวน Cluster ทั้งหมด: "

set BOT_MODE=master
if not "%shards%"=="" set TOTAL_SHARDS=%shards%
set CLUSTER_ID=%cluster_id%
set TOTAL_CLUSTERS=%total_clusters%

python bot.py
goto end

:worker
cls
echo ==========================================
echo  Worker Mode - ประมวลผลงานหนัก
echo ==========================================
echo.
set /p worker_id="Worker ID (0, 1, 2...): "
set /p num_workers="จำนวน Workers ในเครื่องนี้: "

set BOT_MODE=worker
set WORKER_ID=%worker_id%
set NUM_WORKERS=%num_workers%

python worker_node.py --worker-id %worker_id% --num-workers %num_workers%
goto end

:cluster
cls
echo ==========================================
echo  Cluster Mode - Master + Workers
echo ==========================================
echo.
echo รัน Master ใน Terminal ใหม่...
set /p shards="จำนวน Shards (เว้นว่าง = Auto): "
set /p workers="จำนวน Workers: "

:: Start Master
echo Starting Master...
start "Master Bot" cmd /k "set BOT_MODE=master && if not \"%shards%\"==\"\" set TOTAL_SHARDS=%shards% && python bot.py"

:: Start Workers
timeout /t 2 >nul
echo Starting Workers...
for /L %%i in (0,1,%workers%) do (
    start "Worker %%i" cmd /k "python worker_node.py --worker-id %%i --num-workers %workers%"
    timeout /t 1 >nul
)

echo.
echo ==========================================
echo Cluster Started!
echo - Master: Terminal แรก
echo - Workers: %workers% ตัว
echo ==========================================
pause
goto end

:end

pause
