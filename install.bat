@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "RAG_READY=0"

echo ============================================================
echo   Unity AI 开发助手 v1.0.0 — 一键安装脚本
echo ============================================================
echo.

REM ── 检测 Python ──────────────────────────────────────────────
echo [1/6] 检测 Python 环境...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [√] Python %PYVER% 已检测

REM ── 检测 Python 版本 ≥ 3.10 ─────────────────────────────────
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>nul
if %errorlevel% neq 0 (
    echo [错误] Python 版本必须 ≥ 3.10，当前: %PYVER%
    pause
    exit /b 1
)

REM ── 创建虚拟环境 ────────────────────────────────────────────
echo.
echo [2/6] 创建 Python 虚拟环境...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if !errorlevel! neq 0 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
    echo [√] 虚拟环境已创建
) else (
    echo [√] 虚拟环境已存在，跳过创建
)

REM ── 安装 Python 依赖 ────────────────────────────────────────
echo.
echo [3/6] 安装 Python 依赖...
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败，请检查网络连接后重试
    pause
    exit /b 1
)
echo [√] Python 依赖安装完成

REM Graph model comes from the same configuration as the server.
for /f "delims=" %%m in ('.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'Server/src'); from core.config import config; print(config.rag_model)"') do set "RAG_MODEL=%%m"
echo [4/6] 检查按需图谱模型 !RAG_MODEL!...
where ollama >nul 2>&1
if !errorlevel! equ 0 (
    ollama show "!RAG_MODEL!" >nul 2>&1
    if !errorlevel! equ 0 (
        set "RAG_READY=1"
        echo [√] 图谱模型已安装: !RAG_MODEL!
    ) else (
        echo [!] 图谱模型尚未安装或 Ollama 服务未启动。
        echo     启动 Ollama 后运行: ollama pull !RAG_MODEL!
    )
) else (
    echo [!] 未找到 Ollama。Unity 工具和向量检索可独立使用；图谱检索暂不可用。
)

REM ── 验证知识库完整性 ────────────────────────────────────────
echo.
echo [5/6] 验证知识库...
set "KB_DIR=%~dp0Server\data\base_kb"
if exist "%KB_DIR%\chroma_db_v3" (
    echo [√] ChromaDB 向量库目录存在，运行时检查实际内容
) else (
    echo [!] ChromaDB 向量库未找到，知识检索将不可用
)
if exist "%KB_DIR%\lightrag_db_v3_structured" (
    echo [√] LightRAG 知识图谱目录存在，运行时检查实际内容
) else (
    echo [!] 知识图谱未找到，图谱搜索将不可用
)

REM ── 生成 CodeBuddy 配置 ─────────────────────────────────────
echo.
echo [6/6] 生成 CodeBuddy MCP 配置...
set "PRODUCT_ROOT=%~dp0"
set "TEMPLATE=%PRODUCT_ROOT%mcp.json.template"
set "MCP_FILE=%PRODUCT_ROOT%mcp.json"
set "PRODUCT_ROOT_FWD=%PRODUCT_ROOT:\=/%"

if not exist "%TEMPLATE%" (
    echo [!] mcp.json.template 未找到，请手动配置
    goto :mcp_config_done
)

REM 已有 mcp.json 且路径与当前目录一致则跳过；否则（含换电脑）重新生成
set "MCP_NEED_GEN=1"
if exist "%MCP_FILE%" (
    findstr /I /C:"%PRODUCT_ROOT_FWD%" "%MCP_FILE%" >nul 2>&1
    if !errorlevel! equ 0 set "MCP_NEED_GEN=0"
)

if "!MCP_NEED_GEN!"=="0" (
    echo [√] mcp.json 已存在且路径与当前目录一致，跳过生成。
) else (
    if exist "%MCP_FILE%" echo [!] mcp.json 路径与当前目录不一致，重新生成...
    powershell -Command "(Get-Content '%TEMPLATE%' -Raw -Encoding UTF8) -replace '\{\{PRODUCT_ROOT\}\}', '%PRODUCT_ROOT_FWD%' | Set-Content '%MCP_FILE%' -Encoding UTF8"
    echo [√] mcp.json 配置已生成
)
:mcp_config_done

echo.
echo ============================================================
echo   Python 依赖安装完成。
if "!RAG_READY!"=="0" echo   图谱检索尚未就绪，请按上方提示配置 Ollama。
echo.
echo   下一步:
echo   1. 将此次生成的 mcp.json 复制到 CodeBuddy 的 MCP 配置目录
echo      (%USERPROFILE%\.codebuddy\mcp.json)
echo.
echo   2. 在 Unity 中导入 UnityPlugin 目录:
echo      Window → Package Manager → + → Add package from disk
echo      → 选择 %PRODUCT_ROOT%\UnityPlugin\package.json
echo.
echo   3. 在终端中输入 "codebuddy" 启动 AI 助手
echo ============================================================
echo.

pause
