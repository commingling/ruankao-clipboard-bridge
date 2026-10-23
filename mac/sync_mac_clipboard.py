#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mac 端剪贴板监听与同步守护进程 (Ruankao Clipboard Bridge - macOS Daemon)
功能：实时侦听 macOS 本地剪贴板变动，毫秒级原子同步写入共享文件桥通道。
"""

import sys
import os
import time
import argparse
import subprocess
import signal

def get_default_bridge_file():
    candidates = [
        os.path.expanduser("~/Desktop/学习作战台/.mac_clipboard.txt"),
        os.path.expanduser("~/Desktop/.mac_clipboard.txt"),
        os.path.expanduser("~/.mac_clipboard.txt"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".mac_clipboard.txt"))
    ]
    for c in candidates:
        parent = os.path.dirname(c)
        if os.path.exists(parent):
            return c
    return candidates[2]

def get_mac_clipboard():
    try:
        p = subprocess.Popen(['pbpaste'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate(timeout=2)
        return out.decode('utf-8', errors='ignore')
    except Exception:
        return ""

def main():
    parser = argparse.ArgumentParser(description="Ruankao Clipboard Bridge - Mac Daemon")
    parser.add_argument(
        "-f", "--file",
        dest="bridge_file",
        default=os.environ.get("RUANKAO_BRIDGE_FILE", get_default_bridge_file()),
        help="跨系统共享剪贴板文件路径"
    )
    parser.add_argument(
        "-i", "--interval",
        type=float,
        default=0.2,
        help="剪贴板检查间隔（秒，默认 0.2s）"
    )
    args = parser.parse_args()

    bridge_file = os.path.abspath(args.bridge_file)
    temp_file = bridge_file + ".tmp"
    os.makedirs(os.path.dirname(bridge_file), exist_ok=True)

    print("==================================================")
    print("  🚀 软考机考 Mac 剪贴板跨系统守护进程 (高稳版) 已启动")
    print(f"  📁 共享通道文件: {bridge_file}")
    print(f"  ⏱️  轮询检查频率: {args.interval} 秒 (原子落盘)")
    print("  💡 在 Mac 上选中任意文本按 ⌘C 即可自动同步至虚拟机")
    print("==================================================")

    last_text = None

    def handle_exit(signum, frame):
        print("\n🛑 守护进程安全退出")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # 首次启动先同步一次当前剪贴板
    try:
        initial_text = get_mac_clipboard()
        if initial_text:
            last_text = initial_text
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(initial_text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, bridge_file)
            print(f"[{time.strftime('%H:%M:%S')}] 初始同步 Mac 剪贴板内容，共 {len(initial_text)} 字")
    except Exception as e:
        print(f"⚠️ 初始写入失败: {e}")

    while True:
        try:
            curr = get_mac_clipboard()
            if curr != last_text:
                last_text = curr
                # 原子替换，防止跨系统网络文件系统读取到 0 字节半截数据
                with open(temp_file, "w", encoding="utf-8") as f:
                    f.write(curr)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_file, bridge_file)
                preview = curr.replace('\n', ' ').strip()[:35]
                if len(curr) > 35:
                    preview += "..."
                print(f"[{time.strftime('%H:%M:%S')}] 🟢 已捕获 Mac 复制: {len(curr)} 字 | 预览: {preview}")
        except Exception:
            pass
        time.sleep(args.interval)

if __name__ == '__main__':
    main()
