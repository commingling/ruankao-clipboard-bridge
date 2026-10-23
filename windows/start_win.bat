@echo off
chcp 65001 >nul
title 软考机考粘贴助手启动器

echo ==================================================
echo   🚀 软考机考粘贴助手 (Windows VM 端)
echo ==================================================

:: 检查 Python 环境
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo ❌ 未检测到 Python 环境！请先安装 Python 3.8+ 并勾选 "Add Python to PATH"。
    pause
    exit /b 1
)

:: 检查并自动安装 uiautomation 依赖
python -c "import uiautomation" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo 📦 正在自动安装依赖: uiautomation...
    pip install uiautomation -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo 🟢 正在启动注入助手...
cd /d "%~dp0"
start "" python "ruankao_paste_assistant.py"
exit
