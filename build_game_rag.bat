@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   游戏源码知识库构建 (game-rag-knowledge-base)
echo ============================================================
echo.

REM ── 检查虚拟环境 ────────────────────────────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv\Scripts\python.exe
    echo        请先运行 install.bat 完成安装。
    pause
    exit /b 1
)

REM ── 检查源码目录 ────────────────────────────────────────────
if not exist "Server\data\game-rag-knowledge-base\game_source" (
    echo [错误] 未找到源码目录 Server\data\game-rag-knowledge-base\game_source
    pause
    exit /b 1
)

REM ── 进入构建目录 ────────────────────────────────────────────
cd /d "%~dp0Server\data\game-rag-knowledge-base"

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo 开始构建，请稍候（首次构建会下载/加载嵌入模型，耗时较长）...
echo 可用参数：--clear 全量重建  --incremental 增量  --stats 查看统计
echo.

"%~dp0.venv\Scripts\python.exe" build_game_rag.py %*

echo.
if %errorlevel% equ 0 (
    echo [√] 构建完成。
) else (
    echo [错误] 构建失败，请查看上方日志。
)
echo.
pause
