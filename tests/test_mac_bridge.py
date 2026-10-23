"""Safety checks for manual clipboard export; no real clipboard is read."""
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "mac" / "sync_mac_clipboard.py"
spec = importlib.util.spec_from_file_location("mac_bridge", MODULE_PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class ClipboardBridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "snapshot.json"

    def main(self, arguments, interactive=True, answer="SHARE", clipboard="测试内容"):
        with mock.patch.object(bridge.sys.stdin, "isatty", return_value=interactive), \
             mock.patch("builtins.input", return_value=answer) as prompt, \
             mock.patch.object(bridge, "get_mac_clipboard", return_value=clipboard) as read, \
             mock.patch.object(bridge.time, "sleep"), \
             mock.patch.object(bridge.sys, "stdout", new_callable=io.StringIO) as out, \
             mock.patch.object(bridge.sys, "stderr", new_callable=io.StringIO) as err:
            result = bridge.main(arguments)
        return result, prompt, read, out.getvalue() + err.getvalue()

    def test_noninteractive_cannot_read_clipboard(self):
        result, prompt, read, _ = self.main(["-f", str(self.path)], interactive=False)
        self.assertEqual(result, 1)
        read.assert_not_called()
        prompt.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_declining_cannot_read_clipboard(self):
        result, _, read, _ = self.main(["-f", str(self.path)], answer="no")
        self.assertEqual(result, 1)
        read.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_confirmed_reads_once_and_never_prints_text(self):
        secret = "SENSITIVE_TEXT_DO_NOT_LOG"
        result, _, read, output = self.main(["-f", str(self.path)], clipboard=secret)
        self.assertEqual(result, 0)
        read.assert_called_once_with()
        self.assertNotIn(secret, output)
        self.assertFalse(self.path.exists())

    def test_atomic_private_publish_has_exact_protocol(self):
        data = bridge.encode_snapshot("文本\nsecond line", now=1000)
        real_link = bridge.os.link

        def check_link(source, target, **kwargs):
            self.assertFalse(self.path.exists())
            fd = os.open(source, os.O_RDONLY, dir_fd=kwargs["src_dir_fd"])
            with os.fdopen(fd, "rb") as stream:
                self.assertEqual(stream.read(), data)
                self.assertEqual(stat.S_IMODE(os.fstat(stream.fileno()).st_mode), 0o600)
            return real_link(source, target, **kwargs)

        with mock.patch.object(bridge.os, "link", side_effect=check_link):
            bridge.write_snapshot(self.path, data)
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(data), {
            "version": 1, "created_at": 1000, "expires_at": 1120,
            "text": "文本\nsecond line",
        })
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path])

    def test_publish_failure_leaves_no_partial_file(self):
        with mock.patch.object(bridge.os, "link", side_effect=OSError("unsupported")):
            with self.assertRaises(OSError):
                bridge.write_snapshot(self.path, bridge.encode_snapshot("content"))
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_oversized_utf8_and_encoded_files_are_rejected(self):
        with self.assertRaises(ValueError):
            bridge.encode_snapshot("中" * (bridge.MAX_TEXT_BYTES // 3 + 1))
        with self.assertRaises(ValueError):
            bridge.encode_snapshot("\x01" * (bridge.MAX_FILE_BYTES // 6))
        for value in ("", " \n\t", "a\x00b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bridge.encode_snapshot(value)

    def test_publish_does_not_replace_existing_file_or_symlink(self):
        self.path.write_text("user-owned content")
        data = bridge.encode_snapshot("new")
        with self.assertRaises(ValueError):
            bridge.write_snapshot(self.path, data)
        with self.assertRaises(ValueError):
            bridge.clear_snapshot(self.path)
        self.assertEqual(self.path.read_text(), "user-owned content")
        self.path.unlink()
        target = Path(self.directory.name) / "target.txt"
        target.write_text("keep this")
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            bridge.write_snapshot(self.path, data)
        with self.assertRaises(ValueError):
            bridge.clear_snapshot(self.path)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_text(), "keep this")

    def test_clear_does_not_read_clipboard_or_require_confirmation(self):
        bridge.write_snapshot(self.path, bridge.encode_snapshot("text"))
        result, prompt, read, _ = self.main(["-f", str(self.path), "--clear"], interactive=False)
        self.assertEqual(result, 0)
        prompt.assert_not_called()
        read.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_cleanup_preserves_another_sessions_payload(self):
        old_data = bridge.encode_snapshot("old", now=1000)
        new_data = bridge.encode_snapshot("new", now=1001)
        bridge.write_snapshot(self.path, new_data)
        self.assertFalse(bridge.clear_snapshot(self.path, expected=old_data))
        self.assertEqual(self.path.read_bytes(), new_data)
        self.assertTrue(bridge.clear_snapshot(self.path, expected=new_data))
        self.assertFalse(self.path.exists())

    def test_cleanup_preserves_replacement_with_identical_content(self):
        data = bridge.encode_snapshot("same", now=1000)
        ownership = {}
        bridge.write_snapshot(self.path, data, ownership)
        # Keep old inode allocated so this test cannot accidentally reuse its number.
        fd = os.open(self.path, os.O_RDONLY)
        try:
            bridge.clear_snapshot(self.path)
            bridge.write_snapshot(self.path, data)
            self.assertFalse(bridge.clear_snapshot(
                self.path, expected=data, expected_identity=ownership["identity"],
            ))
            self.assertEqual(self.path.read_bytes(), data)
        finally:
            os.close(fd)

    def test_interruption_cleans_export(self):
        with mock.patch.object(bridge, "confirm_export", return_value=True), \
             mock.patch.object(bridge, "get_mac_clipboard", return_value="content") as read, \
             mock.patch.object(bridge.time, "sleep", side_effect=KeyboardInterrupt), \
             mock.patch.object(bridge.sys, "stdout", new_callable=io.StringIO):
            self.assertEqual(bridge.main(["-f", str(self.path)]), 0)
        read.assert_called_once_with()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
