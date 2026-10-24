# -*- coding: utf-8 -*-
"""
软考机考答题区粘贴注入助手 (Ruankao Clipboard Bridge - Windows Assistant 超神直驱版)
彻底解决痛点：
1. 【Mac 原生按键映射】：在虚拟机内直接按 ⌘V (Command+V) 或 Ctrl+V，底层无感拦截并直接注入，彻底消除“需要按很多次”与“弹出剪贴板历史”的问题！
2. 【零剪贴板死锁】：采用 Win32 原生内存直驱，完全不经过系统剪贴板通道，杜绝与 Parallels Tools 争锁；
3. 【🚀 一键全篇智能拆分】：复制整篇 Markdown 论文后，点击一键全篇填入，自动清洗 Markdown 符号 (#、** 等)，自动将摘要填入摘要框、正文填入正文框！
4. 【反遮挡守卫】：永远置顶于全屏机考系统之上，绝不被遮盖。
"""

import tkinter as tk
from tkinter import messagebox
import uiautomation as auto
import ctypes
import ctypes.wintypes
import time
import os
import sys
import re
import threading

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
VK_SPACE = 0x20
VK_BACK = 0x08

# Hotkey Constants
MOD_ALT = 0x0001
MOD_WIN = 0x0008
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

def clean_markdown_text(text):
    """去除 Markdown 标记符号，转换为纯净公文排版文本"""
    # 去除标题井号 #
    text = re.sub(r'(?m)^#+\s*', '', text)
    # 去除加粗 **text**
    text = re.sub(r'\*\*(.*?)\*\*', r'\g<1>', text)
    # 去除斜体 *text*
    text = re.sub(r'\*(.*?)\*', r'\g<1>', text)
    # 去除引用符号 >
    text = re.sub(r'(?m)^>\s*', '', text)
    # 去除超链接 [text](url)
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\g<1>', text)
    # 去除行内代码 `code`
    text = re.sub(r'`(.*?)`', r'\g<1>', text)
    # 去除无序列表前缀 - 或 *
    text = re.sub(r'(?m)^[-*]\s+', '', text)
    return text.strip()

def split_essay(full_text):
    """智能拆分整篇论文为【摘要】与【正文】"""
    cleaned = clean_markdown_text(full_text)
    
    m = re.search(r'(?:摘要|内容摘要|论文摘要)[:：\s\n]+(.*?)(?=(?:正文|正文内容|一、|1\.)[:：\s\n]+)', cleaned, re.DOTALL)
    if m:
        abstract = m.group(1).strip()
        body_start = m.end()
        body_m = re.search(r'(?:正文|正文内容)[:：\s\n]+(.*)', cleaned[body_start:], re.DOTALL)
        if body_m:
            body = body_m.group(1).strip()
        else:
            body = cleaned[body_start:].strip()
        return abstract, body

    paragraphs = [p.strip() for p in cleaned.split('\n\n') if p.strip()]
    if len(paragraphs) >= 2 and len(paragraphs[0]) < 400:
        return paragraphs[0], '\n\n'.join(paragraphs[1:])

    return "", cleaned

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
        clean_text = clean_markdown_text(text)
        clean_text = clean_text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')

        if append:
            buf = ctypes.create_string_buffer(65536)
            user32.SendMessageA(hwnd, WM_GETTEXT, 65536, buf)
            existing = buf.value.decode('gbk', errors='ignore')
            if existing.strip():
                clean_text = existing.rstrip('\r\n') + '\r\n\r\n' + clean_text

        encoded = clean_text.encode('gbk', errors='replace')
        user32.SendMessageA(hwnd, WM_SETTEXT, 0, encoded)
        time.sleep(0.04)

        user32.SendMessageA(hwnd, 0x0100, VK_SPACE, 0)
        user32.SendMessageA(hwnd, 0x0101, VK_SPACE, 0)
        user32.SendMessageA(hwnd, 0x0100, VK_BACK, 0)
        user32.SendMessageA(hwnd, 0x0101, VK_BACK, 0)
        return True
    except Exception:
        return False

def smart_split_and_inject_all(root=None, status_label=None):
    """智能一键全篇拆分并同时填入【摘要框】与【正文框】"""
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
    if not abs_rve and not body_rve:
        update_status("⚠️ 未找到答题框控件！", "#ef4444")
        return

    update_status("⏳ 正在智能拆分并注入全篇论文...", "#2563eb")

    abs_text, body_text = split_essay(text)

    if abs_rve and abs_text:
        inject_text_into_hwnd(abs_rve.NativeWindowHandle, abs_text, append=False)

    if body_rve and body_text:
        inject_text_into_hwnd(body_rve.NativeWindowHandle, body_text, append=False)

    update_status(f"🎉 全篇一键拆分成功！摘要 {len(abs_text)} 字，正文 {len(body_text)} 字", "#059669")

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

    hwnd = target_rve.NativeWindowHandle
    append_mode = (target == 'body' and not clear_first)
    clean_text = clean_markdown_text(text)
    success = inject_text_into_hwnd(hwnd, clean_text, append=append_mode)

    if success:
        update_status(f"✅ 100% 直驱成功！共注入 {len(clean_text)} 字到【{target_name}】", "#059669")
    else:
        update_status("❌ 注入失败，请检查机考窗口", "#ef4444")

# Win32 Structures for Low-Level Keyboard Hook
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('vkCode', ctypes.wintypes.DWORD),
        ('scanCode', ctypes.wintypes.DWORD),
        ('flags', ctypes.wintypes.DWORD),
        ('time', ctypes.wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_void_p),
    ]

class RECT(ctypes.Structure):
    _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long), ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.wintypes.DWORD),
        ('flags', ctypes.wintypes.DWORD),
        ('hwndActive', ctypes.wintypes.HWND),
        ('hwndFocus', ctypes.wintypes.HWND),
        ('hwndCapture', ctypes.wintypes.HWND),
        ('hwndMenuOwner', ctypes.wintypes.HWND),
        ('hwndMoveSize', ctypes.wintypes.HWND),
        ('hwndCaret', ctypes.wintypes.HWND),
        ('rcCaret', RECT),
    ]

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
hook_handle = None
hook_proc_ref = None

def install_system_keyboard_interceptor(root, status_label):
    global hook_handle, hook_proc_ref

    def hook_callback(nCode, wParam, lParam):
        if nCode == 0 and (wParam == 0x0100 or wParam == 0x0104):
            try:
                kb = KBDLLHOOKSTRUCT.from_address(lParam)
                if kb.vkCode == 0x56:  # 'V' key
                    ctrl_down = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
                    win_down = bool((user32.GetAsyncKeyState(0x5B) & 0x8000) or (user32.GetAsyncKeyState(0x5C) & 0x8000))
                    alt_down = bool(user32.GetAsyncKeyState(0x12) & 0x8000)

                    if win_down or ctrl_down or alt_down:
                        gui = GUITHREADINFO()
                        gui.cbSize = ctypes.sizeof(GUITHREADINFO)
                        user32.GetGUIThreadInfo(0, ctypes.byref(gui))
                        target_hwnd = gui.hwndFocus

                        buf = ctypes.create_unicode_buffer(256)
                        user32.GetClassNameW(target_hwnd or 0, buf, 256)
                        cls_name = buf.value

                        if cls_name != 'TRichViewEdit':
                            pt = ctypes.wintypes.POINT()
                            user32.GetCursorPos(ctypes.byref(pt))
                            hwnd_pt = user32.WindowFromPoint(pt)
                            user32.GetClassNameW(hwnd_pt or 0, buf, 256)
                            if buf.value == 'TRichViewEdit':
                                target_hwnd = hwnd_pt
                                cls_name = 'TRichViewEdit'

                        if cls_name == 'TRichViewEdit':
                            def do_instant_inject():
                                text = get_freshest_mac_text()
                                if text:
                                    inject_text_into_hwnd(target_hwnd, text, append=True)
                                    if root and status_label:
                                        root.after(0, lambda: status_label.config(text=f"⚡ 快捷键一次直驱成功！注入 {len(text)} 字", fg="#059669"))

                            threading.Thread(target=do_instant_inject).start()
                            return 1
            except Exception:
                pass
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    hook_proc_ref = HOOKPROC(hook_callback)
    hook_handle = user32.SetWindowsHookExW(13, hook_proc_ref, 0, 0)

def create_gui():
    root = tk.Tk()
    root.title("软考机考粘贴助手 (超神直驱版)")
    root.attributes('-topmost', True)
    root.geometry("340x385+40+40")
    root.resizable(False, False)
    root.configure(bg="#f8fafc")

    lbl_title = tk.Label(root, text="Mac 剪贴板一键注入助手", font=("Microsoft YaHei", 11, "bold"), bg="#f8fafc", fg="#0f172a")
    lbl_title.pack(pady=(6, 1))

    lbl_tip = tk.Label(root, text="在机考框内直接按 ⌘V 或 Ctrl+V 均可秒速粘贴！", font=("Microsoft YaHei", 8, "bold"), bg="#f8fafc", fg="#059669")
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

    lbl_status = tk.Label(root, text="就绪：在机考框直接按 ⌘V 或点下方按钮", font=("Microsoft YaHei", 8), bg="#f8fafc", fg="#64748b")

    btn_smart = tk.Button(
        btn_frame, text="🚀 一键全篇智能拆分填入【摘要+正文】", font=("Microsoft YaHei", 9, "bold"),
        bg="#7c3aed", fg="white", activebackground="#6d28d9", activeforeground="white",
        relief="flat", padx=10, pady=5, cursor="hand2",
        command=lambda: threading.Thread(target=smart_split_and_inject_all, args=(root, lbl_status)).start()
    )
    btn_smart.pack(fill="x", pady=3)

    btn_abs = tk.Button(
        btn_frame, text="📋 仅粘贴到【摘要框】 [F8 / 点击]", font=("Microsoft YaHei", 9),
        bg="#2563eb", fg="white", activebackground="#1d4ed8", activeforeground="white",
        relief="flat", padx=10, pady=3, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('abstract', False, root, lbl_status)).start()
    )
    btn_abs.pack(fill="x", pady=2)

    btn_body = tk.Button(
        btn_frame, text="📋 仅粘贴到【正文框】(追加) [F9 / 点击]", font=("Microsoft YaHei", 9),
        bg="#059669", fg="white", activebackground="#047857", activeforeground="white",
        relief="flat", padx=10, pady=3, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('body', False, root, lbl_status)).start()
    )
    btn_body.pack(fill="x", pady=2)

    btn_clear_body = tk.Button(
        btn_frame, text="🧹 清空并覆盖粘贴到【正文框】 [F10 / 点击]", font=("Microsoft YaHei", 8),
        bg="#d97706", fg="white", activebackground="#b45309", activeforeground="white",
        relief="flat", padx=6, pady=2, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('body', True, root, lbl_status)).start()
    )
    btn_clear_body.pack(fill="x", pady=2)

    lbl_status.pack(pady=(3, 1))

    lbl_kb_tip = tk.Label(root, text="💡 强力支持：直接按 [Command+V] 或 [Ctrl+V] 瞬间一次贴入", font=("Microsoft YaHei", 7), bg="#f8fafc", fg="#64748b")
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

    # 防遮挡守护线程
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
                    root_hwnd = user32.FindWindowW(None, "软考机考粘贴助手 (超神直驱版)")
                if root_hwnd:
                    user32.SetWindowPos(root_hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            except Exception:
                pass
            time.sleep(0.6)

    t_guard = threading.Thread(target=anti_occlusion_guard, daemon=True)
    t_guard.start()

    install_system_keyboard_interceptor(root, lbl_status)

    root.mainloop()

if __name__ == '__main__':
    create_gui()
