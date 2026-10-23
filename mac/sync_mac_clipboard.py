#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manually export one confirmed clipboard snapshot to an authorized environment."""

import argparse
from contextlib import contextmanager
import fcntl
import errno
import json
import math
import os
from pathlib import Path
import secrets
import signal
import stat
import subprocess
import sys
import time

TTL_SECONDS = 120
MAX_TEXT_BYTES = 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024


def get_default_bridge_file():
    return str(Path(__file__).resolve().parent.parent / ".clipboard-bridge.json")


def get_mac_clipboard():
    """Read the clipboard once; callers must obtain interactive consent first."""
    try:
        result = subprocess.run(
            ["pbpaste"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("无法读取 macOS 文本剪贴板。") from exc
    if len(result.stdout) > MAX_TEXT_BYTES:
        raise ValueError("剪贴板文本超过 1 MiB，未导出。")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("剪贴板不是有效的 UTF-8 文本，未导出。") from exc


def validate_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {
        "version", "created_at", "expires_at", "text"
    }:
        raise ValueError("目标文件不是兼容的共享快照；拒绝修改。")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("不支持的快照版本；拒绝修改。")
    start, end = payload["created_at"], payload["expires_at"]
    try:
        valid_times = (all(type(value) in (int, float) and math.isfinite(value)
                           for value in (start, end))
                       and start >= 0 and 0 < end - start <= TTL_SECONDS)
    except (OverflowError, TypeError):
        valid_times = False
    if not valid_times:
        raise ValueError("快照时间字段无效；拒绝修改。")
    text = payload["text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("空白文本不会导出，或目标快照无效。")
    if "\x00" in text:
        raise ValueError("文本包含不支持的 NUL 字符，拒绝处理。")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("文本包含无效 Unicode 字符。") from exc
    if size > MAX_TEXT_BYTES:
        raise ValueError("文本超过 1 MiB，拒绝处理。")


def encode_snapshot(text, now=None):
    created_at = time.time() if now is None else now
    payload = {
        "version": 1, "created_at": created_at,
        "expires_at": created_at + TTL_SECONDS, "text": text,
    }
    validate_payload(payload)
    data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("编码后的快照超过 2 MiB，未导出。")
    return data


@contextmanager
def locked_directory(path):
    """Serialize this program's export/clear/cleanup actions without a lock file."""
    path = Path(path).absolute()
    directory_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        yield directory_fd, path.name
    finally:
        os.close(directory_fd)


def read_snapshot(directory_fd, name):
    """Read a regular file without following a target symlink, with a size bound."""
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("目标不是普通文件（可能为符号链接）；拒绝修改。")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("目标文件已变化，请重试。")
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("目标文件超过 2 MiB；拒绝修改。")
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("目标文件不是兼容的共享快照；拒绝修改。") from exc
    validate_payload(payload)
    return data, opened


def write_snapshot(path, data, ownership=None):
    """Publish a complete private file atomically, never replacing an existing path."""
    with locked_directory(path) as (directory_fd, name):
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("目标路径已存在，未覆盖。兼容的旧快照可用 --clear 清理。")
        temporary_name = ".clipboard-bridge-" + secrets.token_hex(16) + ".tmp"
        fd = os.open(
            temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=directory_fd,
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                info = os.fstat(stream.fileno())
                if ownership is not None:
                    ownership["identity"] = (info.st_dev, info.st_ino)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # link() publishes the complete file and fails if any target already exists.
            try:
                os.link(
                    temporary_name, name, src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd, follow_symlinks=False,
                )
            except OSError as exc:
                if exc.errno in {errno.EXDEV, errno.EPERM, errno.ENOTSUP}:
                    raise ValueError(
                        "无法原子创建快照：目录权限或文件系统可能不支持硬链接；"
                        "请改用支持硬链接的本地共享目录。目标文件未被覆盖。"
                    ) from exc
                raise
        finally:
            os.unlink(temporary_name, dir_fd=directory_fd)


def clear_snapshot(path, expected=None, expected_identity=None):
    """Delete only a compatible snapshot, optionally only this export's exact bytes."""
    with locked_directory(path) as (directory_fd, name):
        current = read_snapshot(directory_fd, name)
        if current is None or (expected is not None and current[0] != expected):
            return False
        if expected_identity is not None and expected_identity != (current[1].st_dev, current[1].st_ino):
            return False
        latest = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (latest.st_dev, latest.st_ino) != (current[1].st_dev, current[1].st_ino):
            return False
        os.unlink(name, dir_fd=directory_fd)
        return True


def confirm_export(path):
    print("请确认：我有权分享此文本，且目标应用允许粘贴。")
    print("请遵守目标应用规则；本工具不支持绕过输入限制。")
    print("快照以明文保存在共享目录；请勿分享密码、密钥或其他敏感资料。")
    print(f"共享文件：{path}")
    print("有效期 120 秒；保持窗口打开以便到期清理，Ctrl+C 可提前清理。")
    print("崩溃可能留下文件；删除不保证消除副本或备份。程序不会显示正文。")
    if not sys.stdin.isatty():
        print("拒绝非交互运行：必须本人在终端确认，未读取剪贴板。", file=sys.stderr)
        return False
    try:
        answer = input("现在复制准备分享的文本；确认用途和内容后输入 SHARE 或 确认：")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip() in {"SHARE", "确认"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="手动单次导出 macOS 剪贴板文本至获授权环境")
    parser.add_argument(
        "-f", "--file", dest="bridge_file",
        default=os.environ.get("CLIPBOARD_BRIDGE_FILE", get_default_bridge_file()),
        help="明确指定共享快照路径；默认项目根目录 .clipboard-bridge.json",
    )
    parser.add_argument("--clear", action="store_true", help="仅删除指定路径的兼容快照，不读取剪贴板")
    args = parser.parse_args(argv)
    path = os.path.abspath(os.path.expanduser(args.bridge_file))
    if args.clear:
        try:
            removed = clear_snapshot(path)
            print("已删除共享快照。" if removed else "没有可清理的共享快照。")
            return 0
        except (OSError, ValueError) as exc:
            print(f"清理失败：{exc}", file=sys.stderr)
            return 1
    if not confirm_export(path):
        print("已取消，未读取剪贴板。")
        return 1

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    data = None
    ownership = {}
    try:
        data = encode_snapshot(get_mac_clipboard())
        # The inode receipt is recorded before publication, including for signal cleanup.
        write_snapshot(path, data, ownership)
        print("已导出一次。等待到期清理；本程序不会继续读取剪贴板。")
        time.sleep(TTL_SECONDS)
        return 0
    except KeyboardInterrupt:
        print("正在结束并清理本次快照。")
        return 0
    except (OSError, ValueError) as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1
    finally:
        # Ignore further termination signals while completing this short cleanup operation.
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        if "identity" in ownership and data is not None:
            try:
                if clear_snapshot(path, expected=data, expected_identity=ownership["identity"]):
                    print("本次共享快照已删除。")
            except (OSError, ValueError):
                print("未能清理本次快照；请检查共享路径并在需要时使用 --clear。", file=sys.stderr)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
