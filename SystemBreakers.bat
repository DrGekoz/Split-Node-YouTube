@echo off
title Split Node

echo.
echo   ==============================================
echo         SPLIT NODE
echo     True stories of ordinary people who
echo             beat the system.
echo      AI documentary, fully automated.
echo   ==============================================
echo.

cd /d "F:aaaaVIBECODING\System Breakers"

echo [CHECK] Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Python not found. Please install Python 3.11+
    pause
    exit /b 1
) else (
    echo [OK] Python found
)

echo [CHECK] FFmpeg...
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] FFmpeg not found. Add it to PATH.
    pause
    exit /b 1
) else (
    echo [OK] FFmpeg found
)

echo [CHECK] PocketTTS server (port 8769)...
curl -s -o nul http://127.0.0.1:8769/health 2>nul
if %errorlevel% neq 0 (
    echo [WARN] PocketTTS not running - attempting to start GPU server...
    start "PocketTTS" /B F:\ComfyUI_windows_portable\python_embeded\python.exe -m pocket_tts serve --port 8769 --device cuda
    timeout /t 15 /nobreak >nul
) else (
    echo [OK] PocketTTS server running
)

echo [CHECK] LM Studio (port 1234)...
curl -s -o nul http://localhost:1234/v1/models 2>nul
if %errorlevel% neq 0 (
    echo [WARN] LM Studio not running on port 1234
    echo        Start LM Studio first, then re-run this.
    pause
) else (
    echo [OK] LM Studio ready
)

echo [CHECK] ComfyUI (port 8188)...
curl -s -o nul http://127.0.0.1:8188/system_stats 2>nul
if %errorlevel% neq 0 (
    echo [WARN] ComfyUI not running on port 8188
    echo        Krea 2 image generation needs ComfyUI running.
    echo        Start ComfyUI via run_nvidia_gpu.bat, then re-run this.
    pause
) else (
    echo [OK] ComfyUI ready
)

echo.
echo All checks passed. Starting Split Node...
echo.
python system_breakers.py

echo.
echo Episode complete. Press any key to exit.
pause >nul
