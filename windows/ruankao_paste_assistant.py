# -*- coding: utf-8 -*-
"""Manually import a short-lived shared text file into the Windows clipboard.

The historical filename is retained for compatibility. This tool does not inspect
other applications, send keystrokes, paste text, or monitor either clipboard.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
from dataclasses import dataclass


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TEXT_BYTES = 1024 * 1024
MAX_TTL_SECONDS = 120
MAX_CLOCK_SKEW_SECONDS = 5
DEFAULT_BRIDGE_FILE = Path(__file__).resolve().parent.parent / ".clipboard-bridge.json"


class BridgeError(ValueError):
    """A user-facing error that never contains the imported text."""


@dataclass(frozen=True)
class LoadedTransfer:
    path: Path
    text: str
    created_at: float
    expires_at: float
    fingerprint: tuple
    digest: str
    loaded_monotonic: float
    expires_monotonic: float


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BridgeError("共享文件含有重复字段，请重新导出。")
        result[key] = value
    return result


def _reject_json_constant(_value):
    raise BridgeError("共享文件含有无效数字，请重新导出。")


def validate_payload(payload, now=None):
    """Validate the v1 protocol; return the text and its two timestamps."""
    now = time.time() if now is None else now
    if not _finite_number(now):
        raise BridgeError("系统时间无效，无法确认文件是否有效。")
    if not isinstance(payload, dict):
        raise BridgeError("共享文件格式无效，请重新导出。")
    if type(payload.get("version")) is not int or payload["version"] != 1:
        raise BridgeError("共享文件协议版本不受支持，请重新导出。")
    created_at = payload.get("created_at")
    expires_at = payload.get("expires_at")
    if not _finite_number(created_at) or not _finite_number(expires_at):
        raise BridgeError("共享文件时间字段无效，请重新导出。")
    if created_at > now + MAX_CLOCK_SKEW_SECONDS:
        raise BridgeError("共享文件来自未来，请校准两端时钟后重新导出。")
    if expires_at <= created_at or expires_at - created_at > MAX_TTL_SECONDS:
        raise BridgeError("共享文件有效期无效，最长允许 120 秒。")
    if expires_at <= now:
        raise BridgeError("共享文件已过期，请在发送端重新导出。")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise BridgeError("共享文件没有可用的非空文本。")
    try:
        encoded_text = text.encode("utf-8")
    except UnicodeEncodeError:
        raise BridgeError("共享文件包含无效文本编码，请重新导出。") from None
    if len(encoded_text) > MAX_TEXT_BYTES:
        raise BridgeError("文本过大：UTF-8 编码后最多允许 1 MiB。")
    if "\x00" in text:
        raise BridgeError("文本含有系统剪贴板不支持的空字符，请移除后重新导出。")
    return text, created_at, expires_at


def _file_fingerprint(file_stat):
    return (
        file_stat.st_dev, file_stat.st_ino, file_stat.st_size,
        file_stat.st_mtime_ns, file_stat.st_ctime_ns,
    )


def _read_file(path):
    try:
        initial_stat = path.stat()
        if not stat.S_ISREG(initial_stat.st_mode):
            raise BridgeError("请选择普通 JSON 文件。")
        if initial_stat.st_size > MAX_FILE_BYTES:
            raise BridgeError("共享文件过大：最多允许 2 MiB。")
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise BridgeError("请选择普通 JSON 文件。")
            raw = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
        current = path.stat()
    except BridgeError:
        raise
    except (OSError, ValueError):
        raise BridgeError("无法读取共享文件，请检查所选路径与访问权限。") from None
    if len(raw) > MAX_FILE_BYTES:
        raise BridgeError("共享文件过大：最多允许 2 MiB。")
    fingerprint = _file_fingerprint(before)
    if any(_file_fingerprint(item) != fingerprint for item in (initial_stat, after, current)):
        raise BridgeError("共享文件读取期间发生变化，请重新加载。")
    return raw, fingerprint


def load_bridge_file(path, now=None, monotonic_now=None):
    """Read only the explicit file; never fall back to a system clipboard."""
    try:
        path = Path(path).expanduser().absolute()
    except (OSError, ValueError, RuntimeError):
        raise BridgeError("共享文件路径无效，请重新选择。") from None
    raw, fingerprint = _read_file(path)
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, ValueError, RecursionError):
        raise BridgeError("共享文件不是有效的 UTF-8 JSON，请重新导出。") from None
    now = time.time() if now is None else now
    text, created_at, expires_at = validate_payload(payload, now=now)
    loaded_monotonic = time.monotonic() if monotonic_now is None else monotonic_now
    return LoadedTransfer(
        path=path, text=text, created_at=created_at, expires_at=expires_at,
        fingerprint=fingerprint, digest=hashlib.sha256(raw).hexdigest(),
        loaded_monotonic=loaded_monotonic,
        expires_monotonic=loaded_monotonic + min(MAX_TTL_SECONDS, expires_at - now),
    )


def ensure_transfer_fresh(transfer, now=None, monotonic_now=None):
    """Recheck expiry, including a monotonic bound if the wall clock changes."""
    now = time.time() if now is None else now
    monotonic_now = time.monotonic() if monotonic_now is None else monotonic_now
    elapsed = monotonic_now - transfer.loaded_monotonic
    if (
        not _finite_number(now) or not _finite_number(monotonic_now)
        or elapsed < 0 or elapsed >= MAX_TTL_SECONDS
        or monotonic_now >= transfer.expires_monotonic
        or now >= transfer.expires_at
        or transfer.created_at > now + MAX_CLOCK_SKEW_SECONDS
    ):
        raise BridgeError("本次加载已失效，请重新导出并加载。")


def ensure_transfer_current(transfer, now=None, monotonic_now=None):
    """On an explicit user action, also reject a changed or removed file."""
    ensure_transfer_fresh(transfer, now=now, monotonic_now=monotonic_now)
    raw, fingerprint = _read_file(transfer.path)
    if fingerprint != transfer.fingerprint or hashlib.sha256(raw).hexdigest() != transfer.digest:
        raise BridgeError("共享文件已发生变化，请重新加载并确认本次用途。")
    # A slow shared drive must not make a once-valid file usable after expiry.
    ensure_transfer_fresh(transfer, now=now, monotonic_now=monotonic_now)


def copy_text_to_windows_clipboard(text, owner_handle):
    """Transfer Unicode text to the OS so it survives this application's exit."""
    if sys.platform != "win32":
        raise BridgeError("复制操作仅支持 Windows。")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    encoded = (text + "\x00").encode("utf-16-le")
    block = kernel32.GlobalAlloc(0x0002, len(encoded))  # GMEM_MOVEABLE
    if not block:
        raise BridgeError("无法准备剪贴板数据，请稍后重试。")
    opened = False
    try:
        pointer = kernel32.GlobalLock(block)
        if not pointer:
            raise BridgeError("无法准备剪贴板数据，请稍后重试。")
        try:
            ctypes.memmove(pointer, encoded, len(encoded))
        finally:
            kernel32.GlobalUnlock(block)
        if not user32.OpenClipboard(owner_handle):
            raise BridgeError("系统剪贴板正被占用，请稍后重试。")
        opened = True
        if not user32.EmptyClipboard() or not user32.SetClipboardData(13, block):
            raise BridgeError("写入系统剪贴板失败，请稍后重试。")
        block = None  # Ownership is now held by Windows (CF_UNICODETEXT).
    finally:
        if opened:
            user32.CloseClipboard()
        if block:
            kernel32.GlobalFree(block)


def create_gui(initial_path):
    # Import GUI modules only when starting the app; validation works headlessly.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("手动文本传递助手")
    root.geometry("760x590")
    root.minsize(660, 520)
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="手动文本传递助手", font=("Microsoft YaHei", 16, "bold")).pack(anchor="w")
    ttk.Label(
        frame, text="选择共享文件 → 手动加载 → 确认用途 → 复制到系统剪贴板", wraplength=700,
    ).pack(anchor="w", pady=(8, 6))
    ttk.Label(
        frame, text="请遵守目标应用规则；本工具不支持绕过输入限制。", wraplength=700,
    ).pack(anchor="w", pady=(0, 14))

    path_var = tk.StringVar(value=str(initial_path))
    consent_var = tk.BooleanVar(value=False)
    status_var = tk.StringVar(value="尚未读取文件。")
    info_var = tk.StringVar(value="正文默认隐藏。共享文件有效期最长 120 秒。")
    state = {"transfer": None, "preview_visible": False}

    ttk.Label(frame, text="共享 JSON 文件").pack(anchor="w")
    path_row = ttk.Frame(frame)
    path_row.pack(fill="x", pady=(5, 8))
    ttk.Entry(path_row, textvariable=path_var).pack(side="left", fill="x", expand=True)
    select_button = ttk.Button(path_row, text="选择文件")
    select_button.pack(side="left", padx=(8, 0))
    load_button = ttk.Button(frame, text="手动加载文件")
    load_button.pack(anchor="w")
    ttk.Label(frame, textvariable=info_var, wraplength=700).pack(anchor="w", pady=(12, 8))
    consent_button = ttk.Checkbutton(
        frame, text="仅向我有权使用且允许粘贴的应用传输文本。",
        variable=consent_var, state="disabled",
    )
    consent_button.pack(anchor="w", pady=(0, 10))

    action_row = ttk.Frame(frame)
    action_row.pack(fill="x")
    copy_button = ttk.Button(action_row, text="复制到 Windows 剪贴板", state="disabled")
    copy_button.pack(side="left")
    preview_button = ttk.Button(action_row, text="显示正文预览", state="disabled")
    preview_button.pack(side="left", padx=8)
    clear_button = ttk.Button(action_row, text="清除本次加载", state="disabled")
    clear_button.pack(side="left")

    preview_frame = ttk.Frame(frame)
    preview = tk.Text(preview_frame, height=9, wrap="word", state="disabled")
    scrollbar = ttk.Scrollbar(preview_frame, orient="vertical", command=preview.yview)
    preview.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    preview.pack(fill="both", expand=True)

    ttk.Label(frame, textvariable=status_var, wraplength=700).pack(anchor="w", pady=(12, 6))
    ttk.Label(
        frame,
        text="复制会替换系统剪贴板中的现有内容，随后请自行在允许粘贴的应用中操作。"
             "系统剪贴板可能被其他应用、剪贴板历史或云同步读取；复制后内容不会随文件过期或退出而自动清除。"
             "“清除本次加载”仅清除本窗口的加载与预览，不删除共享文件或系统剪贴板。",
        wraplength=700,
    ).pack(anchor="w", pady=(6, 0))

    def hide_preview():
        preview.configure(state="normal")
        preview.delete("1.0", "end")
        preview.configure(state="disabled")
        preview_frame.pack_forget()
        state["preview_visible"] = False
        preview_button.configure(text="显示正文预览")

    def clear_loaded(message="已清除本窗口的加载与预览。"):
        hide_preview()
        state["transfer"] = None
        consent_var.set(False)
        consent_button.configure(state="disabled")
        for button in (copy_button, preview_button, clear_button):
            button.configure(state="disabled")
        info_var.set("正文默认隐藏。共享文件有效期最长 120 秒。")
        status_var.set(message)

    def select_file():
        filename = filedialog.askopenfilename(
            parent=root, title="选择发送端明确导出的共享 JSON 文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if filename:
            path_var.set(filename)

    def load_file():
        clear_loaded("正在加载所选文件…")
        try:
            if not path_var.get().strip():
                raise BridgeError("请先选择共享 JSON 文件。")
            transfer = load_bridge_file(path_var.get())
        except BridgeError as error:
            status_var.set(str(error))
            messagebox.showerror("无法加载", str(error), parent=root)
            return
        state["transfer"] = transfer
        info_var.set(
            f"已加载 {len(transfer.text)} 个字符；有效至 "
            f"{time.strftime('%H:%M:%S', time.localtime(transfer.expires_at))}。正文已隐藏。"
        )
        consent_button.configure(state="normal")
        preview_button.configure(state="normal")
        clear_button.configure(state="normal")
        status_var.set("加载成功。请确认本次用途，再主动点击复制。")

    def checked_transfer():
        transfer = state["transfer"]
        if transfer is None:
            return None
        try:
            ensure_transfer_current(transfer)
        except BridgeError as error:
            clear_loaded(str(error))
            messagebox.showerror("本次加载不可用", str(error), parent=root)
            return None
        return transfer

    def toggle_preview():
        if state["preview_visible"]:
            hide_preview()
            return
        transfer = checked_transfer()
        if transfer is not None:
            preview.configure(state="normal")
            preview.insert("1.0", transfer.text)
            preview.configure(state="disabled")
            preview_frame.pack(fill="both", expand=True, pady=(10, 0), after=action_row)
            state["preview_visible"] = True
            preview_button.configure(text="隐藏正文预览")

    def copy_loaded():
        if not consent_var.get():
            status_var.set("请先确认本次用途。")
            return
        transfer = checked_transfer()
        if transfer is None:
            return
        try:
            copy_text_to_windows_clipboard(transfer.text, root.winfo_id())
        except BridgeError as error:
            status_var.set(str(error))
            messagebox.showerror("无法复制", str(error), parent=root)
            return
        status_var.set(f"已将 {len(transfer.text)} 个字符复制到系统剪贴板；未向其他应用输入内容。")

    def refresh_consent(*_args):
        copy_button.configure(state="normal" if state["transfer"] and consent_var.get() else "disabled")

    def expire_loaded():
        # This timer checks only memory timestamps, never files or clipboards.
        transfer = state["transfer"]
        if transfer is not None:
            try:
                ensure_transfer_fresh(transfer)
            except BridgeError as error:
                clear_loaded(str(error))
        root.after(1000, expire_loaded)

    def close_window():
        clear_loaded()
        root.destroy()

    path_var.trace_add("write", lambda *_args: clear_loaded("所选路径已变化，请手动加载。"))
    consent_var.trace_add("write", refresh_consent)
    select_button.configure(command=select_file)
    load_button.configure(command=load_file)
    preview_button.configure(command=toggle_preview)
    clear_button.configure(command=clear_loaded)
    copy_button.configure(command=copy_loaded)
    root.protocol("WM_DELETE_WINDOW", close_window)
    root.after(1000, expire_loaded)
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description="在明确授权的场景中，手动加载共享文本并复制到 Windows 剪贴板。")
    parser.add_argument("-f", "--file", type=Path, default=DEFAULT_BRIDGE_FILE, help="明确指定共享 JSON 文件路径")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("图形助手仅支持 Windows；导入校验函数可在其他平台使用。")
    try:
        create_gui(args.file)
    except ImportError:
        print("无法加载图形界面。请使用包含 Tcl/Tk 支持的 Python 安装。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
