# -*- coding: utf-8 -*-
"""
软考机考答题区粘贴注入助手 (Ruankao Clipboard Bridge - Windows Assistant 全域直驱版)
核心架构突破：
1. 【反遮挡装甲】：自动降级全屏机考系统的 WS_EX_TOPMOST 霸权属性，确保浮窗永远置顶在机考窗口之上，绝不被遮盖！
2. 【全域全局快捷键】：
   - F8: 一键注入【论文摘要框】
   - F9: 一键追加注入【论文正文框】
   - F10: 一键清空并覆盖注入【论文正文框】
   - Option+V (Alt+V): 一键注入当前光标处
3. 【底座内存直驱】：采用原生 Win32 WM_SETTEXT 消息，零剪贴板中转，彻底终结 Parallels 剪贴板死锁冲突！
4. 【即时字数联动】：注入后发送微脉冲，驱动机考系统右上角【共X字】字数统计即时刷新！
"""

import tkinter as tk
from tkinter import messagebox
import uiautomation as auto
import ctypes
import ctypes.wintypes
import time
import os
import sys
import threading

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
VK_SPACE = 0x20
VK_BACK = 0x08

# Hotkey Constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
VK_F8 = 0x77
VK_F9 = 0x78
VK_F10 = 0x79
VK_V = 0x56

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

    if not abs_rve and not body_rve:
        large_edits = [r for r in rves if (r.BoundingRectangle.right - r.BoundingRectangle.left) > 400]
        if large_edits:
            body_rve = large_edits[-1]
            abs_rve = large_edits[0]

    return abs_rve, body_rve

def inject_text_into_hwnd(hwnd, text, append=False):
    """底层核心：直接通过 Win32 WM_SETTEXT 写入 Delphi 控件"""
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

def paste_current_focus(root=None, status_label=None):
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

    auto.SendKeys('{Ctrl}v')
    update_status(f"✅ 成功粘贴 {len(text)} 字到当前光标处！", "#059669")

def create_gui():
    root = tk.Tk()
    root.title("软考机考粘贴助手 (全域直驱版)")
    root.attributes('-topmost', True)
    root.geometry("340x365+40+40")
    root.resizable(False, False)
    root.configure(bg="#f8fafc")

    lbl_title = tk.Label(root, text="Mac 剪贴板一键注入助手", font=("Microsoft YaHei", 11, "bold"), bg="#f8fafc", fg="#0f172a")
    lbl_title.pack(pady=(6, 1))

    lbl_tip = tk.Label(root, text="Mac 复制 (⌘C) ➔ 点击下方按钮或按快捷键", font=("Microsoft YaHei", 8), bg="#f8fafc", fg="#64748b")
    lbl_tip.pack(pady=(0, 3))

    # 预览卡片
    frame_preview = tk.Frame(root, bg="#e2e8f0", padx=8, pady=4)
    frame_preview.pack(fill="x", padx=12, pady=(0, 5))

    lbl_sync_info = tk.Label(frame_preview, text="Mac 剪贴板: 监听中...", font=("Microsoft YaHei", 8, "bold"), bg="#e2e8f0", fg="#334155", anchor="w")
    lbl_sync_info.pack(fill="x")

    lbl_preview = tk.Label(frame_preview, text="(等待复制...)", font=("Microsoft YaHei", 8), bg="#e2e8f0", fg="#64748b", anchor="w", wraplength=290, justify="left", height=2)
    lbl_preview.pack(fill="x")

    btn_frame = tk.Frame(root, bg="#f8fafc")
    btn_frame.pack(fill="x", padx=12)

    lbl_status = tk.Label(root, text="就绪：Mac 复制后点下方按钮 (或按 F8/F9)", font=("Microsoft YaHei", 8), bg="#f8fafc", fg="#64748b")

    btn_abs = tk.Button(
        btn_frame, text="📋 粘贴到【摘要框】 [快捷键: F8]", font=("Microsoft YaHei", 9, "bold"),
        bg="#2563eb", fg="white", activebackground="#1d4ed8", activeforeground="white",
        relief="flat", padx=10, pady=4, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('abstract', False, root, lbl_status)).start()
    )
    btn_abs.pack(fill="x", pady=2)

    btn_body = tk.Button(
        btn_frame, text="📋 粘贴到【正文框】(追加) [快捷键: F9]", font=("Microsoft YaHei", 9, "bold"),
        bg="#059669", fg="white", activebackground="#047857", activeforeground="white",
        relief="flat", padx=10, pady=4, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('body', False, root, lbl_status)).start()
    )
    btn_body.pack(fill="x", pady=2)

    btn_clear_body = tk.Button(
        btn_frame, text="🧹 清空并覆盖粘贴到【正文框】 [快捷键: F10]", font=("Microsoft YaHei", 8),
        bg="#d97706", fg="white", activebackground="#b45309", activeforeground="white",
        relief="flat", padx=6, pady=3, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('body', True, root, lbl_status)).start()
    )
    btn_clear_body.pack(fill="x", pady=2)

    btn_cur = tk.Button(
        btn_frame, text="⚡ 粘贴到当前光标处 [快捷键: Option+V / Alt+V]", font=("Microsoft YaHei", 8),
        bg="#64748b", fg="white", activebackground="#475569", activeforeground="white",
        relief="flat", padx=6, pady=3, cursor="hand2",
        command=lambda: threading.Thread(target=paste_current_focus, args=(root, lbl_status)).start()
    )
    btn_cur.pack(fill="x", pady=2)

    lbl_status.pack(pady=(3, 1))

    lbl_kb_tip = tk.Label(root, text="💡 提示：按键盘 F8 注入摘要，F9 注入正文，Option+V 直贴", font=("Microsoft YaHei", 7), bg="#f8fafc", fg="#94a3b8")
    lbl_kb_tip.pack(pady=(0, 2))

    # 后台剪贴板监听
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

    # 核心装甲：防遮挡守卫线程 (将机考全屏窗口降级，确保本浮窗永远置顶最前)
    def anti_occlusion_guard():
        while True:
            try:
                for w in auto.GetRootControl().GetChildren():
                    if w.ClassName == 'TfrmMainCenter':
                        exam_hwnd = w.NativeWindowHandle
                        ex_style = user32.GetWindowLongA(exam_hwnd, -20)
                        if ex_style & 0x00000008:
                            user32.SetWindowPos(exam_hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
                        break

                root_hwnd = int(root.wm_frame(), 16) if hasattr(root, 'wm_frame') else None
                if not root_hwnd:
                    root_hwnd = user32.FindWindowW(None, "软考机考粘贴助手 (全域直驱版)")
                if root_hwnd:
                    user32.SetWindowPos(root_hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            except Exception:
                pass
            time.sleep(0.6)

    t_guard = threading.Thread(target=anti_occlusion_guard, daemon=True)
    t_guard.start()

    # 全局快捷键守护线程
    def global_hotkey_loop():
        user32.RegisterHotKey(None, 101, 0, VK_F8)
        user32.RegisterHotKey(None, 102, 0, VK_F9)
        user32.RegisterHotKey(None, 103, 0, VK_F10)
        user32.RegisterHotKey(None, 104, MOD_ALT, VK_V)

        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
            if msg.message == 0x0312:  # WM_HOTKEY
                hk_id = msg.wParam
                if hk_id == 101:
                    paste_into('abstract', False, root, lbl_status)
                elif hk_id == 102:
                    paste_into('body', False, root, lbl_status)
                elif hk_id == 103:
                    paste_into('body', True, root, lbl_status)
                elif hk_id == 104:
                    paste_current_focus(root, lbl_status)
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    t_hk = threading.Thread(target=global_hotkey_loop, daemon=True)
    t_hk.start()

    root.mainloop()

if __name__ == '__main__':
    create_gui()
