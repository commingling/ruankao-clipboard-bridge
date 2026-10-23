# -*- coding: utf-8 -*-
"""
软考机考答题区粘贴注入助手 (Ruankao Clipboard Bridge - Windows Assistant 终极直驱版)
核心架构突破：
1. 采用原生 Win32 WM_SETTEXT 消息直接对 Delphi TRichViewEdit 写入 GBK 文本；
2. 完全脱离 Windows 系统剪贴板通道，彻底终结与 Parallels Tools (prl_cc.exe) 的剪贴板死锁冲突；
3. 完全不移动物理鼠标光标，彻底避开宿主机/虚拟机鼠标光标争夺导致的漂移问题；
4. 注入后发送虚拟按键刷新事件，驱动 Delphi 内部 OnChange 机制，使考试系统的【共X字】字数统计即时精准刷新！
"""

import tkinter as tk
from tkinter import messagebox
import uiautomation as auto
import ctypes
import time
import os
import sys
import threading

user32 = ctypes.windll.user32
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
VK_SPACE = 0x20
VK_BACK = 0x08

CANDIDATE_PATHS = [
    r"C:\Mac\Home\Desktop\学习作战台\.mac_clipboard.txt",
    r"\\Mac\Home\Desktop\学习作战台\.mac_clipboard.txt",
    r"C:\Mac\Home\Desktop\.mac_clipboard.txt",
    r"\\Mac\Home\Desktop\.mac_clipboard.txt",
    r"C:\Mac\Home\.mac_clipboard.txt",
    r"\\Mac\Home\.mac_clipboard.txt",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".mac_clipboard.txt")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".mac_clipboard.txt"))
]

def resolve_file():
    for p in CANDIDATE_PATHS:
        if os.path.exists(p):
            return p
    return CANDIDATE_PATHS[0]

MAC_CLIP_FILE = resolve_file()

def get_freshest_mac_text():
    global MAC_CLIP_FILE
    if not os.path.exists(MAC_CLIP_FILE):
        MAC_CLIP_FILE = resolve_file()

    for _ in range(3):
        if os.path.exists(MAC_CLIP_FILE):
            try:
                with open(MAC_CLIP_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if content:
                        return content
            except Exception:
                time.sleep(0.04)

    try:
        return auto.GetClipboardText()
    except Exception:
        return ""

def find_exam_window():
    for w in auto.GetRootControl().GetChildren():
        if w.ClassName == 'TfrmMainCenter':
            return w
    return None

def find_rves(win):
    rves = []
    def walk(ctrl):
        if ctrl.ClassName == 'TRichViewEdit':
            rves.append(ctrl)
        for child in ctrl.GetChildren():
            walk(child)
    walk(win)

    abs_rve = None
    body_rve = None

    for r in rves:
        rect = r.BoundingRectangle
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        # 必须是位于右侧答题区域的输入框（left > 1000 且 宽度 > 500）
        if rect.left > 1000 and w > 500:
            if 50 < h < 260:
                abs_rve = r
            elif h > 400:
                body_rve = r

    # 兜底：若只有单个输入框（如案例分析）
    if not abs_rve and not body_rve:
        large_edits = [r for r in rves if (r.BoundingRectangle.right - r.BoundingRectangle.left) > 400]
        if large_edits:
            body_rve = large_edits[-1]
            abs_rve = large_edits[0]

    return abs_rve, body_rve

def inject_text_into_hwnd(hwnd, text, append=False):
    """
    底层核心：直接通过 Win32 WM_SETTEXT 写入 Delphi 控件
    返回 True 表示注入成功
    """
    if not hwnd:
        return False
    try:
        clean_text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')

        if append:
            buf = ctypes.create_string_buffer(65536)
            user32.SendMessageA(hwnd, WM_GETTEXT, 65536, buf)
            existing = buf.value.decode('gbk', errors='ignore')
            if existing.strip():
                clean_text = existing.rstrip('\r\n') + '\r\n\r\n' + clean_text

        encoded = clean_text.encode('gbk', errors='replace')
        # 1. 直接写入底层缓冲区
        user32.SendMessageA(hwnd, WM_SETTEXT, 0, encoded)
        time.sleep(0.04)

        # 2. 触发 Delphi 内部 OnChange 计算，更新机考界面右上角的【共X字】字数
        user32.SendMessageA(hwnd, 0x0100, VK_SPACE, 0)
        user32.SendMessageA(hwnd, 0x0101, VK_SPACE, 0)
        user32.SendMessageA(hwnd, 0x0100, VK_BACK, 0)
        user32.SendMessageA(hwnd, 0x0101, VK_BACK, 0)
        return True
    except Exception:
        return False

def paste_into(target='abstract', clear_first=False, root=None, status_label=None):
    def update_status(text, color):
        if root and status_label:
            root.after(0, lambda: status_label.config(text=text, fg=color))

    text = get_freshest_mac_text()
    if not text:
        update_status("⚠️ 剪贴板为空，请先在 Mac 复制内容！", "#ef4444")
        return

    win = find_exam_window()
    if not win:
        update_status("⚠️ 未找到机考作答窗口！请先进入作答页", "#ef4444")
        return

    abs_rve, body_rve = find_rves(win)
    target_rve = abs_rve if target == 'abstract' else body_rve
    target_name = "论文摘要框" if target == 'abstract' else "论文正文框"

    if not target_rve:
        update_status(f"⚠️ 未找到【{target_name}】！", "#ef4444")
        return

    update_status("⏳ 正在注入文本...", "#2563eb")

    # 同时同步 Windows 本地剪贴板（供想按 Control+V 的用户备用）
    try:
        auto.SetClipboardText(text)
    except Exception:
        pass

    hwnd = target_rve.NativeWindowHandle
    append_mode = (target == 'body' and not clear_first)
    success = inject_text_into_hwnd(hwnd, text, append=append_mode)

    if success:
        update_status(f"✅ 100% 直驱成功！共注入 {len(text)} 字到【{target_name}】", "#059669")
    else:
        # 回退模式（仅当句柄异常时）
        try:
            win.SetActive()
            time.sleep(0.1)
            rect = target_rve.BoundingRectangle
            auto.Click(rect.left + 60, rect.top + 35)
            time.sleep(0.15)
            if clear_first:
                auto.SendKeys('{Ctrl}a{Back}')
                time.sleep(0.1)
            auto.SendKeys('{Ctrl}v')
            update_status(f"✅ 注入成功 {len(text)} 字到【{target_name}】！", "#059669")
        except Exception as e:
            update_status(f"❌ 注入异常: {e}", "#ef4444")

def paste_after_delay(seconds=2, root=None, status_label=None):
    def update_status(text, color):
        if root and status_label:
            root.after(0, lambda: status_label.config(text=text, fg=color))

    text = get_freshest_mac_text()
    if not text:
        update_status("⚠️ 剪贴板为空，请先在 Mac 复制内容！", "#ef4444")
        return

    try:
        auto.SetClipboardText(text)
    except Exception:
        pass

    for s in range(seconds, 0, -1):
        update_status(f"⏳ 请在 {s} 秒内把光标点进目标答题框...", "#2563eb")
        time.sleep(1)

    update_status("⏳ 正在粘贴...", "#2563eb")
    auto.SendKeys('{Ctrl}v')
    time.sleep(0.2)
    update_status(f"✅ 成功粘贴 {len(text)} 字到当前光标处！", "#059669")

def create_gui():
    root = tk.Tk()
    root.title("软考机考粘贴助手 (直驱稳固版)")
    root.attributes('-topmost', True)
    root.geometry("340x355+40+40")
    root.resizable(False, False)
    root.configure(bg="#f8fafc")

    lbl_title = tk.Label(root, text="Mac 剪贴板一键注入助手", font=("Microsoft YaHei", 11, "bold"), bg="#f8fafc", fg="#0f172a")
    lbl_title.pack(pady=(8, 2))

    lbl_tip = tk.Label(root, text="Mac 复制 (⌘C) ➔ 点击下方按钮直接注入", font=("Microsoft YaHei", 8), bg="#f8fafc", fg="#64748b")
    lbl_tip.pack(pady=(0, 4))

    # 预览展示区域
    frame_preview = tk.Frame(root, bg="#e2e8f0", padx=8, pady=5)
    frame_preview.pack(fill="x", padx=12, pady=(0, 6))

    lbl_sync_info = tk.Label(frame_preview, text="Mac 剪贴板: 监听中...", font=("Microsoft YaHei", 8, "bold"), bg="#e2e8f0", fg="#334155", anchor="w")
    lbl_sync_info.pack(fill="x")

    lbl_preview = tk.Label(frame_preview, text="(等待复制...)", font=("Microsoft YaHei", 8), bg="#e2e8f0", fg="#64748b", anchor="w", wraplength=290, justify="left", height=2)
    lbl_preview.pack(fill="x")

    btn_frame = tk.Frame(root, bg="#f8fafc")
    btn_frame.pack(fill="x", padx=12)

    lbl_status = tk.Label(root, text="就绪：Mac 复制后点下方按钮", font=("Microsoft YaHei", 8), bg="#f8fafc", fg="#64748b")

    btn_abs = tk.Button(
        btn_frame, text="📋 粘贴到【论文摘要框】", font=("Microsoft YaHei", 9, "bold"),
        bg="#2563eb", fg="white", activebackground="#1d4ed8", activeforeground="white",
        relief="flat", padx=10, pady=5, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('abstract', False, root, lbl_status)).start()
    )
    btn_abs.pack(fill="x", pady=2)

    btn_body = tk.Button(
        btn_frame, text="📋 粘贴到【论文正文框】(追加)", font=("Microsoft YaHei", 9, "bold"),
        bg="#059669", fg="white", activebackground="#047857", activeforeground="white",
        relief="flat", padx=10, pady=5, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('body', False, root, lbl_status)).start()
    )
    btn_body.pack(fill="x", pady=2)

    btn_clear_body = tk.Button(
        btn_frame, text="🧹 清空并覆盖粘贴到【正文框】", font=("Microsoft YaHei", 8),
        bg="#d97706", fg="white", activebackground="#b45309", activeforeground="white",
        relief="flat", padx=6, pady=3, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('body', True, root, lbl_status)).start()
    )
    btn_clear_body.pack(fill="x", pady=2)

    btn_delay = tk.Button(
        btn_frame, text="⏱️ 2秒后粘贴到当前光标处 (案例/通用题型)", font=("Microsoft YaHei", 8),
        bg="#64748b", fg="white", activebackground="#475569", activeforeground="white",
        relief="flat", padx=6, pady=3, cursor="hand2",
        command=lambda: threading.Thread(target=paste_after_delay, args=(2, root, lbl_status)).start()
    )
    btn_delay.pack(fill="x", pady=2)

    lbl_status.pack(pady=(4, 2))

    lbl_kb_tip = tk.Label(root, text="💡 提示：在机考框按键盘左下角 [Control + V] 也可直接粘贴", font=("Microsoft YaHei", 7), bg="#f8fafc", fg="#94a3b8")
    lbl_kb_tip.pack(pady=(0, 2))

    # 后台实时监听与剪贴板同步（主线程安全更新）
    def update_preview_loop():
        last_t = None
        while True:
            try:
                t = get_freshest_mac_text()
                if t != last_t:
                    last_t = t
                    preview_str = t.replace("\n", " ").strip()[:40] + ("..." if len(t) > 40 else "")
                    def update_ui(cnt=len(t), pstr=preview_str):
                        lbl_sync_info.config(text=f"🟢 Mac 已同步: {cnt} 字")
                        lbl_preview.config(text=pstr if pstr else "(空白)")
                    root.after(0, update_ui)
                    try:
                        auto.SetClipboardText(t)
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(0.25)

    t_sync = threading.Thread(target=update_preview_loop, daemon=True)
    t_sync.start()

    root.mainloop()

if __name__ == '__main__':
    create_gui()
