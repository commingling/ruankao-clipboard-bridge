# -*- coding: utf-8 -*-
"""
Windows 虚拟机端机考答题区粘贴注入助手 (Ruankao Clipboard Bridge - Windows Assistant)
功能：
1. 实时读取来自 Mac 端共享的剪贴板内容，自动同步至 Windows 系统剪贴板；
2. 置顶悬浮 UI，一键自动识别软考机考系统（TfrmMainCenter），精准定位 Delphi TRichViewEdit 答题框；
3. 支持一键注入【论文摘要框】、【论文正文框】(追加/清空覆盖) 及通用【倒计时注入当前光标处】。
"""

import tkinter as tk
from tkinter import messagebox
import uiautomation as auto
import time
import os
import sys
import threading

def resolve_bridge_file():
    """多路径自动发现跨系统共享剪贴板文件"""
    candidates = [
        r"\\Mac\Home\Desktop\学习作战台\.mac_clipboard.txt",
        r"C:\Mac\Home\Desktop\学习作战台\.mac_clipboard.txt",
        r"\\Mac\Home\Desktop\.mac_clipboard.txt",
        r"C:\Mac\Home\Desktop\.mac_clipboard.txt",
        r"\\Mac\Home\.mac_clipboard.txt",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".mac_clipboard.txt")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".mac_clipboard.txt"))
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    # 默认返回第一候选
    return candidates[0]

MAC_CLIP_FILE = resolve_bridge_file()

def get_freshest_mac_text():
    """读取最新的 Mac 剪贴板文本，若文件不存在则回退至 Windows 剪贴板"""
    global MAC_CLIP_FILE
    if not os.path.exists(MAC_CLIP_FILE):
        MAC_CLIP_FILE = resolve_bridge_file()

    if os.path.exists(MAC_CLIP_FILE):
        try:
            with open(MAC_CLIP_FILE, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            pass
    try:
        return auto.GetClipboardText()
    except Exception:
        return ""

def find_exam_window():
    """查找软考模拟系统主作答窗口 (TfrmMainCenter)"""
    for w in auto.GetRootControl().GetChildren():
        if w.ClassName == 'TfrmMainCenter':
            return w
    return None

def find_rves(win):
    """
    精准查找软考机考作答区 Delphi TRichViewEdit 输入控件：
    - 摘要框：位于右侧作答区上方，高度约 111px
    - 正文框：位于右侧作答区下方，高度约 1036px
    - 兼容模式：若仅有单一文本框（如案例分析），自动回退适配
    """
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

    # 兜底：若只有单个输入框（如案例分析主答题框）
    if not abs_rve and not body_rve:
        large_edits = [r for r in rves if (r.BoundingRectangle.right - r.BoundingRectangle.left) > 400]
        if large_edits:
            body_rve = large_edits[-1]
            abs_rve = large_edits[0]

    return abs_rve, body_rve

def paste_into(target='abstract', clear_first=False, status_label=None):
    """将文本一键注入到机考答题框"""
    text = get_freshest_mac_text()
    if not text:
        if status_label:
            status_label.config(text="⚠️ 剪贴板为空，请先在 Mac 复制内容！", fg="#ef4444")
        return

    win = find_exam_window()
    if not win:
        if status_label:
            status_label.config(text="⚠️ 未找到作答窗口！请先进入试卷作答界面", fg="#ef4444")
        return

    abs_rve, body_rve = find_rves(win)
    target_rve = abs_rve if target == 'abstract' else body_rve
    target_name = "论文摘要框" if target == 'abstract' else "论文正文框"

    if not target_rve:
        if status_label:
            status_label.config(text=f"⚠️ 未找到【{target_name}】控件！", fg="#ef4444")
        return

    if status_label:
        status_label.config(text="⏳ 正在注入文本...", fg="#2563eb")

    # 强制同步 Windows 系统剪贴板
    auto.SetClipboardText(text)
    time.sleep(0.08)

    # 激活并聚焦机考窗口
    try:
        win.SetActive()
    except Exception:
        pass
    time.sleep(0.12)

    # 计算点击位置（输入框内部靠左上方位置）
    rect = target_rve.BoundingRectangle
    click_x = rect.left + 60
    click_y = rect.top + 35

    auto.Click(click_x, click_y)
    time.sleep(0.15)

    if clear_first:
        # 快捷清空
        auto.SendKeys('{Ctrl}a{Back}')
        time.sleep(0.1)
        # 兼容性清空兜底
        auto.SendKeys('{End}{Back 1500}')
        time.sleep(0.1)

    # 触发标准粘贴
    auto.SendKeys('{Ctrl}v')
    time.sleep(0.15)

    if status_label:
        status_label.config(text=f"✅ 成功注入 {len(text)} 字到【{target_name}】！", fg="#059669")

def paste_after_delay(seconds=2, status_label=None):
    """通用延时粘贴：支持案例分析或任意第三方输入框"""
    text = get_freshest_mac_text()
    if not text:
        if status_label:
            status_label.config(text="⚠️ 剪贴板为空，请先在 Mac 复制内容！", fg="#ef4444")
        return

    auto.SetClipboardText(text)

    for s in range(seconds, 0, -1):
        if status_label:
            status_label.config(text=f"⏳ 请在 {s} 秒内点进目标答题框...", fg="#2563eb")
        time.sleep(1)

    if status_label:
        status_label.config(text="⏳ 正在粘贴...", fg="#2563eb")

    auto.SendKeys('{Ctrl}v')
    time.sleep(0.2)

    if status_label:
        status_label.config(text=f"✅ 成功粘贴 {len(text)} 字到当前光标处！", fg="#059669")

def create_gui():
    root = tk.Tk()
    root.title("软考机考粘贴助手")
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

    # 按钮操作区域
    btn_frame = tk.Frame(root, bg="#f8fafc")
    btn_frame.pack(fill="x", padx=12)

    lbl_status = tk.Label(root, text="就绪：Mac 复制后点下方按钮", font=("Microsoft YaHei", 8), bg="#f8fafc", fg="#64748b")

    btn_abs = tk.Button(
        btn_frame, text="📋 粘贴到【论文摘要框】", font=("Microsoft YaHei", 9, "bold"),
        bg="#2563eb", fg="white", activebackground="#1d4ed8", activeforeground="white",
        relief="flat", padx=10, pady=5, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('abstract', False, lbl_status)).start()
    )
    btn_abs.pack(fill="x", pady=2)

    btn_body = tk.Button(
        btn_frame, text="📋 粘贴到【论文正文框】(追加)", font=("Microsoft YaHei", 9, "bold"),
        bg="#059669", fg="white", activebackground="#047857", activeforeground="white",
        relief="flat", padx=10, pady=5, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('body', False, lbl_status)).start()
    )
    btn_body.pack(fill="x", pady=2)

    btn_clear_body = tk.Button(
        btn_frame, text="🧹 清空并覆盖粘贴到【论文正文框】", font=("Microsoft YaHei", 8),
        bg="#d97706", fg="white", activebackground="#b45309", activeforeground="white",
        relief="flat", padx=6, pady=3, cursor="hand2",
        command=lambda: threading.Thread(target=paste_into, args=('body', True, lbl_status)).start()
    )
    btn_clear_body.pack(fill="x", pady=2)

    btn_delay = tk.Button(
        btn_frame, text="⏱️ 2秒后粘贴到当前光标处 (案例/通用题型)", font=("Microsoft YaHei", 8),
        bg="#64748b", fg="white", activebackground="#475569", activeforeground="white",
        relief="flat", padx=6, pady=3, cursor="hand2",
        command=lambda: threading.Thread(target=paste_after_delay, args=(2, lbl_status)).start()
    )
    btn_delay.pack(fill="x", pady=2)

    lbl_status.pack(pady=(4, 2))

    lbl_kb_tip = tk.Label(root, text="💡 提示：在机考框按键盘左下角 [Control + V] 也可直接粘贴", font=("Microsoft YaHei", 7), bg="#f8fafc", fg="#94a3b8")
    lbl_kb_tip.pack(pady=(0, 2))

    # 后台实时监听与剪贴板同步
    def update_preview_loop():
        last_t = None
        while True:
            try:
                t = get_freshest_mac_text()
                if t != last_t:
                    last_t = t
                    preview_str = t.replace("\n", " ").strip()[:40] + ("..." if len(t) > 40 else "")
                    lbl_sync_info.config(text=f"🟢 Mac 已同步: {len(t)} 字")
                    lbl_preview.config(text=preview_str if preview_str else "(空白)")
                    # 自动同步至 Windows 系统剪贴板
                    auto.SetClipboardText(t)
            except Exception:
                pass
            time.sleep(0.3)

    t_sync = threading.Thread(target=update_preview_loop, daemon=True)
    t_sync.start()

    root.mainloop()

if __name__ == '__main__':
    create_gui()
