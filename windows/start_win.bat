@echo off
setlocal
chcp 65001 >nul
title 手动文本传递助手

where python >nul 2>nul
if errorlevel 1 (
    echo 未找到 Python。请先自行安装包含 Tcl/Tk 的 Python 3.9 或更新版本，并将其加入 PATH。
    pause
    exit /b 1
)

echo 启动手动文本传递助手。仅使用 Python 标准库，不自动安装依赖。
python "%~dp0ruankao_paste_assistant.py" %*
set "bridge_exit_code=%errorlevel%"
if not "%bridge_exit_code%"=="0" pause
exit /b %bridge_exit_code%
