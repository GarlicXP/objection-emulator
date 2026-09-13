@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo 首次运行，正在创建虚拟环境并安装依赖（约 1-2 分钟）...
    where py >nul 2>&1 && py -3 -m venv .venv || python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)
start "" ".venv\Scripts\pythonw.exe" "main.py"
