@echo off
title Product Assistant - Stop

echo ===========================================
echo   Stopping all services...
echo ===========================================

echo.
echo   [1/3] Stopping Query Server (port 8001)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001.*LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1 && echo   Query Server stopped
)

echo   [2/3] Stopping MinIO (port 9000)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9000.*LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1 && echo   MinIO stopped
)

echo   [3/3] Stopping MongoDB (port 27017)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":27017.*LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1 && echo   MongoDB stopped
)

echo.
echo ===========================================
echo   All services stopped.
echo ===========================================

pause
