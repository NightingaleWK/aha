"""A small native Windows notification-area adapter; the runtime owns the service."""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

_UINT = ctypes.c_uint32
_INT = ctypes.c_int32
_HANDLE = ctypes.c_void_p
_WPARAM = ctypes.c_size_t
_LPARAM = ctypes.c_ssize_t
_LRESULT = ctypes.c_ssize_t
_WNDPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    _LRESULT, _HANDLE, _UINT, _WPARAM, _LPARAM
)

_WM_NULL = 0x0000
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_CONTEXTMENU = 0x007B
_WM_COMMAND = 0x0111
_WM_LBUTTONDBLCLK = 0x0203
_WM_RBUTTONUP = 0x0205
_NIN_KEYSELECT = 0x0401
_TRAY_MESSAGE = 0x8001
_STOP_MESSAGE = 0x8002
_OPEN_COMMAND = 1
_EXIT_COMMAND = 2
_NIM_ADD = 0
_NIM_DELETE = 2
_NIM_SETVERSION = 4
_NOTIFYICON_VERSION_4 = 4


class _Point(ctypes.Structure):
    _fields_ = [("x", _INT), ("y", _INT)]


class _Message(ctypes.Structure):
    _fields_ = [
        ("hwnd", _HANDLE),
        ("message", _UINT),
        ("wParam", _WPARAM),
        ("lParam", _LPARAM),
        ("time", _UINT),
        ("pt", _Point),
        ("lPrivate", _UINT),
    ]


class _WindowClass(ctypes.Structure):
    _fields_ = [
        ("style", _UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", _INT),
        ("cbWndExtra", _INT),
        ("hInstance", _HANDLE),
        ("hIcon", _HANDLE),
        ("hCursor", _HANDLE),
        ("hbrBackground", _HANDLE),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", _UINT),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _NotifyIconData(ctypes.Structure):
    _fields_ = [
        ("cbSize", _UINT),
        ("hWnd", _HANDLE),
        ("uID", _UINT),
        ("uFlags", _UINT),
        ("uCallbackMessage", _UINT),
        ("hIcon", _HANDLE),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", _UINT),
        ("dwStateMask", _UINT),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", _UINT),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", _UINT),
        ("guidItem", _Guid),
        ("hBalloonIcon", _HANDLE),
    ]


class _Win32:
    """Keep untyped foreign-function declarations at the native boundary."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("系统托盘仅支持 Windows。")
        loader = getattr(ctypes, "WinDLL")
        self.user32: Any = loader("user32", use_last_error=True)
        self.shell32: Any = loader("shell32", use_last_error=True)
        self.kernel32: Any = loader("kernel32", use_last_error=True)
        wide = ctypes.c_wchar_p
        signatures: list[tuple[Any, list[Any], Any]] = [
            (self.kernel32.GetModuleHandleW, [wide], _HANDLE),
            (self.user32.RegisterClassW, [ctypes.POINTER(_WindowClass)], ctypes.c_uint16),
            (self.user32.UnregisterClassW, [wide, _HANDLE], _INT),
            (
                self.user32.CreateWindowExW,
                [_UINT, wide, wide, _UINT, _INT, _INT, _INT, _INT,
                 _HANDLE, _HANDLE, _HANDLE, _HANDLE],
                _HANDLE,
            ),
            (self.user32.DefWindowProcW, [_HANDLE, _UINT, _WPARAM, _LPARAM], _LRESULT),
            (self.user32.DestroyWindow, [_HANDLE], _INT),
            (self.user32.LoadImageW, [_HANDLE, wide, _UINT, _INT, _INT, _UINT], _HANDLE),
            (self.user32.DestroyIcon, [_HANDLE], _INT),
            (self.user32.CreatePopupMenu, [], _HANDLE),
            (self.user32.AppendMenuW, [_HANDLE, _UINT, _WPARAM, wide], _INT),
            (self.user32.SetMenuDefaultItem, [_HANDLE, _UINT, _UINT], _INT),
            (self.user32.DestroyMenu, [_HANDLE], _INT),
            (self.user32.GetCursorPos, [ctypes.POINTER(_Point)], _INT),
            (self.user32.SetForegroundWindow, [_HANDLE], _INT),
            (
                self.user32.TrackPopupMenu,
                [_HANDLE, _UINT, _INT, _INT, _INT, _HANDLE, _HANDLE],
                _UINT,
            ),
            (self.user32.RegisterWindowMessageW, [wide], _UINT),
            (self.user32.PostMessageW, [_HANDLE, _UINT, _WPARAM, _LPARAM], _INT),
            (self.user32.PostQuitMessage, [_INT], None),
            (self.user32.GetMessageW, [ctypes.POINTER(_Message), _HANDLE, _UINT, _UINT], _INT),
            (
                self.user32.PeekMessageW,
                [ctypes.POINTER(_Message), _HANDLE, _UINT, _UINT, _UINT],
                _INT,
            ),
            (self.user32.TranslateMessage, [ctypes.POINTER(_Message)], _INT),
            (self.user32.DispatchMessageW, [ctypes.POINTER(_Message)], _LRESULT),
            (self.shell32.Shell_NotifyIconW, [_UINT, ctypes.POINTER(_NotifyIconData)], _INT),
        ]
        for function, arguments, result in signatures:
            function.argtypes = arguments
            function.restype = result

    @staticmethod
    def error() -> OSError:
        return OSError(int(getattr(ctypes, "get_last_error")()), "无法创建或更新 Windows 托盘。")


class WindowsTray:
    """Create/run/close on one thread; stop and callbacks never block that thread."""

    def __init__(
        self,
        on_open: Callable[[], None],
        on_exit: Callable[[], None],
        tooltip: str = "aha",
        icon_path: Path | None = None,
    ) -> None:
        self._on_open = on_open
        self._on_exit = on_exit
        self._tooltip = tooltip.encode("utf-16-le", errors="replace")[:254].decode(
            "utf-16-le", errors="ignore"
        )
        self._icon_path = icon_path or Path(__file__).with_name("web") / "mark.ico"
        self._api: _Win32 | None = None
        self._owner: int | None = None
        self._hwnd: int | None = None
        self._icon: int | None = None
        self._menu: int | None = None
        self._module: int | None = None
        self._registered = False
        self._icon_added = False
        self._closed = False
        self._running = False
        self._quit_posted = False
        self._stopping = threading.Event()
        self._failure: OSError | None = None
        self._class_name = f"aha.tray.{os.getpid()}.{id(self):x}"
        self._taskbar_created = 0
        # The callback must survive every invocation from user32, including destruction.
        self._procedure: Any = _WNDPROC(self._window_proc)

    def start(self) -> None:
        self._check_owner()
        if self._closed:
            raise OSError("系统托盘已经关闭。")
        if self._hwnd is not None or self._stopping.is_set():
            return
        self._owner = threading.get_ident()
        try:
            self._api = api = _Win32()
            module = api.kernel32.GetModuleHandleW(None)
            if not module:
                raise api.error()
            self._module = int(module)
            window_class = _WindowClass()
            window_class.lpfnWndProc = self._procedure
            window_class.hInstance = self._module
            window_class.lpszClassName = self._class_name
            if not api.user32.RegisterClassW(ctypes.byref(window_class)):
                raise api.error()
            self._registered = True
            self._taskbar_created = int(api.user32.RegisterWindowMessageW("TaskbarCreated"))
            if not self._taskbar_created:
                raise api.error()
            # A hidden top-level tool window receives TaskbarCreated broadcasts.
            hwnd = api.user32.CreateWindowExW(
                0x80, self._class_name, self._tooltip, 0, 0, 0, 0, 0,
                None, None, self._module, None,
            )
            if not hwnd:
                raise api.error()
            self._hwnd = int(hwnd)
            icon = api.user32.LoadImageW(None, str(self._icon_path), 1, 0, 0, 0x10 | 0x40)
            if not icon:
                raise api.error()
            self._icon = int(icon)
            menu = api.user32.CreatePopupMenu()
            if not menu:
                raise api.error()
            self._menu = int(menu)
            for identifier, label in ((_OPEN_COMMAND, "打开 aha"), (_EXIT_COMMAND, "退出程序")):
                if not api.user32.AppendMenuW(self._menu, 0, identifier, label):
                    raise api.error()
            if not api.user32.SetMenuDefaultItem(self._menu, _OPEN_COMMAND, False):
                raise api.error()
            self._add_icon()
        except Exception:
            self.close()
            raise

    def run(self) -> None:
        self.start()
        api = self._api
        try:
            if api is not None:
                self._running = True
                message = _Message()
                while not self._stopping.is_set():
                    result = api.user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                    if result == -1:
                        raise api.error()
                    if result == 0:
                        break
                    api.user32.TranslateMessage(ctypes.byref(message))
                    api.user32.DispatchMessageW(ctypes.byref(message))
        finally:
            self._running = False
            self.close()
            if api is not None and self._quit_posted:
                api.user32.PeekMessageW(ctypes.byref(_Message()), None, 0x12, 0x12, 1)
                self._quit_posted = False
        if self._failure is not None:
            raise self._failure

    def stop(self) -> None:
        self._stopping.set()
        api, hwnd = self._api, self._hwnd
        if api is not None and hwnd is not None:
            api.user32.PostMessageW(hwnd, _STOP_MESSAGE, 0, 0)

    def close(self) -> None:
        if self._closed:
            return
        self._check_owner()
        self._stopping.set()
        api = self._api
        if api is not None:
            self._remove_icon()
            if self._hwnd is not None:
                api.user32.DestroyWindow(self._hwnd)
                self._hwnd = None
            if self._menu is not None:
                api.user32.DestroyMenu(self._menu)
                self._menu = None
            if self._icon is not None:
                api.user32.DestroyIcon(self._icon)
                self._icon = None
            if self._registered:
                api.user32.UnregisterClassW(self._class_name, self._module)
                self._registered = False
        self._closed = True

    def _check_owner(self) -> None:
        if self._owner is not None and self._owner != threading.get_ident():
            raise RuntimeError("托盘窗口必须由创建它的线程管理。")

    def _data(self) -> _NotifyIconData:
        data = _NotifyIconData()
        data.cbSize = ctypes.sizeof(data)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = 0x01 | 0x02 | 0x04 | 0x80  # MESSAGE, ICON, TIP, SHOWTIP (v4).
        data.uCallbackMessage = _TRAY_MESSAGE
        data.hIcon = self._icon
        data.szTip = self._tooltip
        return data

    def _add_icon(self) -> None:
        api = self._api
        if api is None:
            return
        data = self._data()
        if not api.shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(data)):
            raise api.error()
        self._icon_added = True
        data.uVersion = _NOTIFYICON_VERSION_4
        if not api.shell32.Shell_NotifyIconW(_NIM_SETVERSION, ctypes.byref(data)):
            raise api.error()

    def _remove_icon(self) -> None:
        if self._api is not None and self._icon_added:
            self._api.shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(self._data()))
            self._icon_added = False

    def _dispatch(self, callback: Callable[[], None], name: str) -> None:
        if self._stopping.is_set():
            return

        def invoke() -> None:
            try:
                callback()
            except Exception:
                self._failure = OSError("托盘操作未完成，请重新启动程序。")
                self.stop()

        threading.Thread(target=invoke, name=name, daemon=True).start()

    def _command(self, identifier: int) -> None:
        if identifier == _OPEN_COMMAND:
            self._dispatch(self._on_open, "aha-tray-open")
        elif identifier == _EXIT_COMMAND:
            self._dispatch(self._on_exit, "aha-tray-exit")

    def _show_menu(self) -> None:
        api, hwnd, menu = self._api, self._hwnd, self._menu
        if api is None or hwnd is None or menu is None or self._stopping.is_set():
            return
        point = _Point()
        if not api.user32.GetCursorPos(ctypes.byref(point)):
            raise api.error()
        api.user32.SetForegroundWindow(hwnd)
        command = api.user32.TrackPopupMenu(menu, 0x100 | 0x80 | 0x02, point.x, point.y,
                                           0, hwnd, None)
        # Ensures the menu dismisses correctly when the user cancels outside it.
        api.user32.PostMessageW(hwnd, _WM_NULL, 0, 0)
        self._command(int(command))

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        api = self._api
        if api is None:
            return 0
        try:
            if message == _WM_DESTROY:
                self._remove_icon()
                self._hwnd = None
                self._stopping.set()
                if self._running:
                    api.user32.PostQuitMessage(0)
                    self._quit_posted = True
                return 0
            if message in (_WM_CLOSE, _STOP_MESSAGE):
                self._remove_icon()
                api.user32.DestroyWindow(hwnd)
                return 0
            if message == self._taskbar_created and not self._stopping.is_set():
                self._remove_icon()
                self._add_icon()
                return 0
            if message == _WM_COMMAND:
                self._command(wparam & 0xFFFF)
                return 0
            if message == _TRAY_MESSAGE:
                event = lparam & 0xFFFF
                if event in (_WM_LBUTTONDBLCLK, _NIN_KEYSELECT):
                    self._command(_OPEN_COMMAND)
                elif event in (_WM_CONTEXTMENU, _WM_RBUTTONUP):
                    self._show_menu()
                return 0
            return int(api.user32.DefWindowProcW(hwnd, message, wparam, lparam))
        except Exception:
            # Exceptions must never escape a native callback or print a traceback.
            self._failure = OSError("Windows 托盘无法继续运行，请重新启动程序。")
            self.stop()
            return 0
