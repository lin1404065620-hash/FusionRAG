@echo off
setlocal enabledelayedexpansion
title Data Import

set "VENV_PYTHON=.venv\Scripts\python.exe"
cd /d "%~dp0"

echo ===========================================
echo   数据导入工具
echo ===========================================
echo.

:: ============================================
:: [1/4] 停止查询服务 (8001)
:: ============================================
echo   [1/4] 停止查询服务 (8001)...

set "killed=0"

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001 " ^| findstr "LISTENING"') do (
    echo   发现端口 8001 被 PID=%%a 占用，正在关闭...
    taskkill /PID %%a /F >nul 2>&1
    if not errorlevel 1 set "killed=1"
)

if !killed! equ 0 (
    echo   查询服务未运行
) else (
    echo   查询服务已停止，等待端口释放...
    timeout /t 3 /nobreak >nul
)

:: 验证端口释放（最多重试 5 次）
set "retry=0"
:verify_8001
set "port_busy=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001 " ^| findstr "LISTENING"') do set "port_busy=1"

if !port_busy! equ 1 (
    if !retry! lss 5 (
        set /a retry+=1
        echo   [!retry!/5] 端口 8001 仍被占用，强制关闭...
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001 " ^| findstr "LISTENING"') do (
            taskkill /F /PID %%a >nul 2>&1
        )
        timeout /t 3 /nobreak >nul
        goto :verify_8001
    )
    echo   [错误] 无法释放端口 8001，请手动关闭后重试
    pause
    exit /b 1
)
echo   端口 8001 已释放

:: ============================================
:: [2/4] 检查 MongoDB + MinIO
:: ============================================
echo.
echo   [2/4] 检查基础服务...

netstat -an | findstr ":27017 " | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo   MongoDB 就绪
) else (
    echo   正在启动 MongoDB...
    REM 请替换为你的 MongoDB 安装路径
    REM 示例: start "MongoDB" /MIN "C:\mongodb\bin\mongod.exe" --dbpath C:\mongodb\data\db --logpath C:\mongodb\log\mongodb.log --logappend --bind_ip 127.0.0.1 --port 27017
    echo   [错误] 请在脚本中配置 MongoDB 路径后再运行
    timeout /t 4 /nobreak >nul
    echo   MongoDB 已启动
)

netstat -an | findstr ":9000 " | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo   MinIO 就绪
) else (
    echo   正在启动 MinIO...
    REM 请替换为你的 MinIO 安装路径
    REM 示例: start "MinIO" /MIN "D:\minio\minio.exe" server "D:\minio\data" --address ":9000"
    echo   [错误] 请在脚本中配置 MinIO 路径后再运行
    timeout /t 4 /nobreak >nul
    echo   MinIO 已启动
)

:: ============================================
:: [3/4] 启动导入服务 (8000)
:: ============================================
echo.
echo   [3/4] 启动导入服务 (8000)...

start "ImportServer" /MIN "%VENV_PYTHON%" -m app.import_process.api.import_server

set "import_ready=0"
for /l %%i in (1,1,15) do (
    timeout /t 2 /nobreak >nul
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do set "import_ready=1"
    if !import_ready! equ 1 goto :import_ready_done
    echo   等待导入服务启动... (%%i/15)
)
:import_ready_done

if !import_ready! equ 1 (
    echo   导入服务已启动 (端口 8000)
) else (
    echo   [警告] 导入服务可能启动失败，请检查
)

:: ============================================
:: [4/4] 打开上传页面
:: ============================================
echo.
echo   [4/4] 打开上传页面...
start "" "http://127.0.0.1:8000/import"

echo.
echo ===========================================
echo   请在浏览器中上传文件
echo   上传完成后按任意键继续...
echo ===========================================
pause >nul

:: ============================================
:: 清理：停止导入服务
:: ============================================
echo.
echo   正在停止导入服务...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
    echo   导入服务已停止 (PID %%a)
)
timeout /t 2 /nobreak >nul

:: ============================================
:: 重启查询服务
:: ============================================
echo.
echo   正在重启查询服务...
start "QueryServer" /MIN "%VENV_PYTHON%" -m app.query_process.api.query_server

set "query_ready=0"
for /l %%i in (1,1,10) do (
    timeout /t 2 /nobreak >nul
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001 " ^| findstr "LISTENING"') do set "query_ready=1"
    if !query_ready! equ 1 goto :query_ready_done
    echo   等待查询服务启动... (%%i/10)
)
:query_ready_done

if !query_ready! equ 1 (
    echo   查询服务已启动 (端口 8001)
    start "" "http://127.0.0.1:8001/chat.html"
) else (
    echo   [警告] 查询服务可能启动失败
)

echo.
echo ===========================================
echo   导入流程完成
echo ===========================================
pause
endlocal
