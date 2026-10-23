"""Headless checks for explicit imports, expiry and change detection."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "windows"))
import ruankao_paste_assistant as bridge


class WindowsBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "transfer.json"
        self.now = 1000.0
        self.payload = {
            "version": 1, "created_at": self.now, "expires_at": self.now + 120,
            "text": "已授权的文本\nUnicode: 😀",
        }

    def write(self, payload=None):
        self.path.write_text(json.dumps(self.payload if payload is None else payload), encoding="utf-8")

    def load(self):
        return bridge.load_bridge_file(self.path, now=self.now, monotonic_now=10)

    def test_valid_unicode_file_loads_without_gui_or_clipboard(self):
        self.write()
        transfer = self.load()
        self.assertEqual(transfer.text, self.payload["text"])
        bridge.ensure_transfer_current(transfer, now=self.now + 10, monotonic_now=20)

    def test_missing_file_is_rejected_without_fallback(self):
        with self.assertRaises(bridge.BridgeError):
            self.load()

    def test_invalid_path_is_reported_without_an_unhandled_exception(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.load_bridge_file("bad\x00path.json", now=self.now)

    def test_invalid_protocol_fields_are_rejected(self):
        invalid_fields = [
            ("version", True), ("version", 1.0), ("version", 2),
            ("created_at", True), ("created_at", "1000"),
            ("created_at", float("nan")), ("created_at", float("inf")),
            ("created_at", self.now + 6),
            ("expires_at", self.now), ("expires_at", self.now - 1),
            ("expires_at", self.now + 121), ("expires_at", float("inf")),
            ("text", ""), ("text", " \n\t"), ("text", 1),
            ("text", "secret\x00tail"), ("text", "\ud800"),
        ]
        for field, value in invalid_fields:
            with self.subTest(field=field, value=repr(value)):
                self.write({**self.payload, field: value})
                with self.assertRaises(bridge.BridgeError):
                    self.load()

    def test_extreme_integer_time_is_rejected(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.validate_payload({**self.payload, "created_at": 10 ** 1000}, now=self.now)

    def test_file_byte_limit(self):
        self.path.write_bytes(b" " * (bridge.MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(bridge.BridgeError, "2 MiB"):
            self.load()

    def test_text_byte_limit_is_utf8_not_character_count(self):
        self.path.write_text(
            json.dumps({**self.payload, "text": "汉" * (bridge.MAX_TEXT_BYTES // 3 + 1)}, ensure_ascii=False),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(bridge.BridgeError, "1 MiB"):
            self.load()

    def test_text_exact_byte_limit_is_accepted(self):
        self.write({**self.payload, "text": "x" * bridge.MAX_TEXT_BYTES})
        self.assertEqual(len(self.load().text), bridge.MAX_TEXT_BYTES)

    def test_expired_loaded_text_is_rejected_at_copy_time(self):
        self.write()
        transfer = self.load()
        with self.assertRaises(bridge.BridgeError):
            bridge.ensure_transfer_current(transfer, now=self.now + 120, monotonic_now=20)

    def test_monotonic_limit_rejects_text_when_wall_clock_is_adjusted(self):
        self.write()
        transfer = self.load()
        with self.assertRaises(bridge.BridgeError):
            bridge.ensure_transfer_current(transfer, now=self.now + 10, monotonic_now=130)

    def test_remaining_lifetime_is_preserved_after_a_backward_clock_adjustment(self):
        self.write()
        transfer = bridge.load_bridge_file(self.path, now=self.now + 119, monotonic_now=10)
        with self.assertRaises(bridge.BridgeError):
            bridge.ensure_transfer_current(transfer, now=self.now + 118, monotonic_now=12)

    def test_changed_file_requires_explicit_reload(self):
        self.write()
        transfer = self.load()
        self.write({**self.payload, "text": "另一次导出"})
        with self.assertRaises(bridge.BridgeError):
            bridge.ensure_transfer_current(transfer, now=self.now + 1, monotonic_now=11)

    def test_replaced_file_with_identical_content_requires_reload(self):
        self.write()
        transfer = self.load()
        replacement = self.path.with_suffix(".new")
        replacement.write_bytes(self.path.read_bytes())
        replacement.replace(self.path)
        with self.assertRaises(bridge.BridgeError):
            bridge.ensure_transfer_current(transfer, now=self.now + 1, monotonic_now=11)

    def test_deleted_file_is_rejected_at_copy_time(self):
        self.write()
        transfer = self.load()
        self.path.unlink()
        with self.assertRaises(bridge.BridgeError):
            bridge.ensure_transfer_current(transfer, now=self.now + 1, monotonic_now=11)

    def test_duplicate_fields_and_bad_json_do_not_leak_text_in_errors(self):
        marker = "PRIVATE_CONTENT_NOT_FOR_LOGS"
        documents = [
            '{"version": 1, "version": 1, "text": "' + marker + '"}',
            '{"text": "' + marker + '"', marker,
            '{"created_at": NaN, "text": "' + marker + '"}',
            '[' * 2000 + '"' + marker + '"' + ']' * 2000,
        ]
        for document in documents:
            with self.subTest(document=document[:30]):
                self.path.write_text(document, encoding="utf-8")
                with self.assertRaises(bridge.BridgeError) as raised:
                    self.load()
                self.assertNotIn(marker, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
