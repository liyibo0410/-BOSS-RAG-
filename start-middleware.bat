@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 自动识别 docker compose 命令形态：
REM   优先 v2 插件写法（docker compose），检测不到时回退 v1 独立命令（docker-compose）
REM   部分机器只装了 docker-compose，直接写 "docker compose up -d" 会报 unknown command
set "DC=docker-compose"
docker compose version >nul 2>&1
if not errorlevel 1 set "DC=docker compose"

echo ============================================================
echo  Starting middleware: Milvus + MinIO + MongoDB
echo  Using: %DC%
echo  First run downloads images (~2GB), please be patient...
echo ============================================================
echo.

%DC% up -d
if errorlevel 1 (
    echo.
    echo [ERROR] docker compose failed. Make sure Docker Desktop is running.
    pause
    exit /b 1
)

echo.
echo Waiting for services to become healthy (Milvus may take 1-2 min)...
echo.

set /a RETRY=0
:WAIT
set /a RETRY+=1
if %RETRY% gtr 30 (
    echo [WARN] Timeout waiting for health check. Showing status:
    %DC% ps
    goto DONE
)

for /f %%i in ('docker inspect -f "{{.State.Health.Status}}" milvus-standalone 2^>nul') do set MILVUS_HEALTH=%%i
if "%MILVUS_HEALTH%"=="healthy" goto HEALTHY

timeout /t 10 /nobreak >nul
echo   ...waiting (%RETRY%/30), milvus=%MILVUS_HEALTH%
goto WAIT

:HEALTHY
echo [OK] All core services are healthy.

:DONE
echo.
echo ---------------- Container status ----------------
%DC% ps
echo.
echo  MinIO console : http://localhost:9001  (minioadmin / minioadmin)
echo  Milvus        : localhost:19530
echo  MongoDB       : localhost:27017
echo.
echo Next: run check_env.py to verify connectivity
echo   .venv\Scripts\python.exe check_env.py
echo.
pause
