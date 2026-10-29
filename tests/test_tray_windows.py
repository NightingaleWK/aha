"""Tray ownership, initialization rollback, event routing and native Windows smoke."""

from __future__ import annotations

import ctypes
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from aha import tray_windows as tray


class TrayAdapterTests(unittest.TestCase):
    def api(self) -> MagicMock:
        api = MagicMock()
        api.error.side_effect = lambda: OSError("托盘检查错误")
        api.kernel32.GetModuleHandleW.return_value = 100
        api.user32.RegisterClassW.return_value = 1
        api.user32.RegisterWindowMessageW.return_value = 0xC001
        api.user32.CreateWindowExW.return_value = 200
        api.user32.LoadImageW.return_value = 300
        api.user32.CreatePopupMenu.return_value = 400
        api.user32.AppendMenuW.return_value = 1
        api.user32.SetMenuDefaultItem.return_value = 1
        api.shell32.Shell_NotifyIconW.return_value = 1
        return api

    def test_initialization_failure_closes_every_acquired_resource(self) -> None:
        api = self.api()
        api.shell32.Shell_NotifyIconW.side_effect = [1, 0, 1]
        adapter = tray.WindowsTray(lambda: None, lambda: None)
        with patch.object(tray, "_Win32", return_value=api), self.assertRaises(OSError):
            adapter.start()
        self.assertTrue(adapter._closed)
        api.user32.DestroyWindow.assert_called_once_with(200)
        api.user32.DestroyMenu.assert_called_once_with(400)
        api.user32.DestroyIcon.assert_called_once_with(300)
        api.user32.UnregisterClassW.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in api.shell32.Shell_NotifyIconW.call_args_list], [0, 4, 2]
        )
        adapter.close()
        api.user32.DestroyIcon.assert_called_once()

    def test_stop_from_worker_only_posts_until_owner_cleans_up(self) -> None:
        api = self.api()
        adapter = tray.WindowsTray(lambda: None, lambda: None)
        with patch.object(tray, "_Win32", return_value=api):
            adapter.start()
        worker = threading.Thread(target=adapter.stop)
        worker.start()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        api.user32.PostMessageW.assert_called_once_with(200, tray._STOP_MESSAGE, 0, 0)
        api.user32.DestroyWindow.assert_not_called()
        adapter.close()
        api.user32.DestroyWindow.assert_called_once()

    def test_open_and_exit_commands_run_off_window_thread(self) -> None:
        api = self.api()
        opened, exited = threading.Event(), threading.Event()
        callback_threads: list[int] = []

        def record(event: threading.Event) -> None:
            callback_threads.append(threading.get_ident())
            event.set()

        adapter = tray.WindowsTray(lambda: record(opened), lambda: record(exited))
        with patch.object(tray, "_Win32", return_value=api):
            adapter.start()
        try:
            adapter._window_proc(200, tray._TRAY_MESSAGE, 0, tray._WM_LBUTTONDBLCLK)
            self.assertTrue(opened.wait(2))
            adapter._window_proc(200, tray._WM_COMMAND, tray._EXIT_COMMAND, 0)
            self.assertTrue(exited.wait(2))
            self.assertTrue(all(item != threading.get_ident() for item in callback_threads))
        finally:
            adapter.close()

    def test_taskbar_recreation_removes_then_readds_owned_icon(self) -> None:
        api = self.api()
        adapter = tray.WindowsTray(lambda: None, lambda: None)
        with patch.object(tray, "_Win32", return_value=api):
            adapter.start()
        try:
            api.shell32.Shell_NotifyIconW.reset_mock()
            adapter._window_proc(200, 0xC001, 0, 0)
            self.assertEqual(
                [call.args[0] for call in api.shell32.Shell_NotifyIconW.call_args_list],
                [2, 0, 4],
            )
        finally:
            adapter.close()

    def test_message_loop_error_closes_resources(self) -> None:
        api = self.api()
        api.user32.GetMessageW.return_value = -1
        adapter = tray.WindowsTray(lambda: None, lambda: None)
        with patch.object(tray, "_Win32", return_value=api), self.assertRaises(OSError):
            adapter.run()
        self.assertTrue(adapter._closed)
        api.user32.DestroyWindow.assert_called_once()
        api.user32.DestroyIcon.assert_called_once()

    def test_utf16_tooltip_does_not_split_astral_characters(self) -> None:
        adapter = tray.WindowsTray(lambda: None, lambda: None, "😀" * 100)
        self.assertLessEqual(len(adapter._tooltip.encode("utf-16-le")), 254)
        self.assertEqual(adapter._tooltip, "😀" * 63)


@unittest.skipUnless(sys.platform == "win32", "requires the real Windows notification area")
class NativeTrayTests(unittest.TestCase):
    def test_native_structure_layout_and_failed_start_cleanup(self) -> None:
        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 8)
        self.assertEqual(ctypes.sizeof(tray._WindowClass), 72)
        self.assertEqual(ctypes.sizeof(tray._Message), 48)
        self.assertEqual(ctypes.sizeof(tray._NotifyIconData), 976)
        with tempfile.TemporaryDirectory() as temporary:
            adapter = tray.WindowsTray(
                lambda: None, lambda: None, icon_path=Path(temporary) / "missing.ico"
            )
            with self.assertRaises(OSError):
                adapter.start()
            self.assertTrue(adapter._closed)
            self.assertIsNone(adapter._hwnd)
            self.assertFalse(adapter._registered)

    def test_native_keyboard_recreation_and_shutdown(self) -> None:
        opened, exited = threading.Event(), threading.Event()
        failures: list[str] = []
        callback_threads: list[int] = []

        def on_open() -> None:
            callback_threads.append(threading.get_ident())
            opened.set()

        def on_exit() -> None:
            callback_threads.append(threading.get_ident())
            exited.set()
            adapter.stop()

        adapter = tray.WindowsTray(on_open, on_exit, "aha · 原生托盘检查")
        adapter.start()
        api = adapter._api
        self.assertIsNotNone(api)
        assert api is not None

        def drive() -> None:
            try:
                api.user32.PostMessageW(adapter._hwnd, tray._TRAY_MESSAGE, 0, tray._NIN_KEYSELECT)
                if not opened.wait(3):
                    failures.append("keyboard activation did not reach callback")
                    return
                api.user32.PostMessageW(adapter._hwnd, adapter._taskbar_created, 0, 0)
                api.user32.PostMessageW(adapter._hwnd, tray._WM_COMMAND, tray._EXIT_COMMAND, 0)
                if not exited.wait(3):
                    failures.append("exit command did not reach callback")
            finally:
                adapter.stop()

        worker = threading.Thread(target=drive)
        worker.start()
        try:
            adapter.run()
        finally:
            adapter.close()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(callback_threads), 2)
        self.assertTrue(all(item != threading.get_ident() for item in callback_threads))
        self.assertIsNone(adapter._hwnd)
        self.assertIsNone(adapter._menu)
        self.assertIsNone(adapter._icon)
        self.assertFalse(adapter._icon_added)


if __name__ == "__main__":
    unittest.main()
