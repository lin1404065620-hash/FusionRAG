@echo off
title Product Assistant

REM 请根据你的实际安装路径设置以下变量
REM 示例: set "MONGOD_EXE=C:\mongodb\bin\mongod.exe"
REM 示例: set "MONGOD_DATA=C:\mongodb\data\db"
REM 示例: set "MONGOD_LOG=C:\mongodb\log\mongodb.log"
REM 示例: set "MINIO_EXE=D:\minio\minio.exe"
REM 示例: set "MINIO_DATA=D:\minio\data"
set "MONGOD_EXE="
set "MONGOD_DATA="
set "MONGOD_LOG="
set "MINIO_EXE="
set "MINIO_DATA="

echo ===========================================
echo   [1/3] MongoDB ...
echo ===========================================
netstat -an | findstr ":27017.*LISTENING" >nul
if %errorlevel% equ 0 (
    echo   MongoDB already running
) else (
    echo   Starting MongoDB...
    start "MongoDB" /MIN "%MONGOD_EXE%" --dbpath "%MONGOD_DATA%" --logpath "%MONGOD_LOG%" --logappend --bind_ip 127.0.0.1 --port 27017
    ping 127.0.0.1 -n 4 >nul
    echo   MongoDB started
)

echo ===========================================
echo   [2/3] MinIO ...
echo ===========================================
netstat -an | findstr ":9000.*LISTENING" >nul
if %errorlevel% equ 0 (
    echo   MinIO already running
) else (
    echo   Starting MinIO...
    start "MinIO" /MIN "%MINIO_EXE%" server "%MINIO_DATA%" --address ":9000"
    ping 127.0.0.1 -n 4 >nul
    echo   MinIO started
)

echo ===========================================
echo   [3/3] Query Server ...
echo ===========================================
netstat -an | findstr ":8001.*LISTENING" >nul
if %errorlevel% equ 0 (
    echo   Query server already running
) else (
    echo   Starting query server...
    cd /d "%~dp0"
    start "QueryServer" /MIN ".venv\Scripts\python.exe" -m app.query_process.api.query_server
    echo   Waiting 10 seconds...
    ping 127.0.0.1 -n 10 >nul
    netstat -an | findstr ":8001.*LISTENING" >nul
    if %errorlevel% equ 0 (
        echo   Query server started OK
    ) else (
        echo   WARNING: Query server may not have started
    )
)

echo ===========================================
echo   Opening browser...
echo ===========================================
start "" "http://127.0.0.1:8001/chat.html"

echo.
echo   Done! Close this window or press any key.
pause
