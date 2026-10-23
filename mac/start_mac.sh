#!/usr/bin/env bash
# 手动导出一份明确确认的剪贴板快照。
set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
    echo "未检测到 Python 3，请先安装 Python 3。" >&2
    exit 1
fi

echo "正在启动手动剪贴板导出工具……"
exec python3 "$script_dir/sync_mac_clipboard.py" "$@"
