#!/usr/bin/env bash
# 一键启动 Mac 端剪贴板同步守护脚本

cd "$(dirname "$0")"

# 检查 Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ 未检测到 Python 3，请先安装 Python 3"
    exit 1
fi

echo "🚀 正在启动 Mac 剪贴板守护进程..."
python3 sync_mac_clipboard.py "$@"
