"""Reopen an owned local instance, or launch one service and its Windows tray."""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from .domain import AppError
from .instance import LaunchDescriptor, acquire_instance
from .runtime import ApplicationRuntime
from .server import create_server


def default_data_dir() -> Path:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else Path.home() / "AppData" / "Local") / "aha"
    local = os.environ.get("XDG_DATA_HOME")
    return (Path(local) if local else Path.home() / ".local" / "share") / "aha"


def startup_error(parser: argparse.ArgumentParser, message: str) -> None:
    if sys.platform == "win32" and sys.stderr is None:
        import ctypes

        getattr(ctypes, "windll").user32.MessageBoxW(None, message, "aha · 无法启动", 0x10)
    parser.exit(1, message + "\n")


def open_browser(address: str, *, tray_available: bool) -> None:
    try:
        if webbrowser.open(address):
            return
    except (webbrowser.Error, OSError):
        pass
    message = (
        "浏览器未能自动打开，请右键托盘图标选择“打开 aha”重试。"
        if tray_available
        else "浏览器未能自动打开，请检查默认浏览器后重新双击 aha；控制台可使用启动地址。"
    )
    if sys.platform == "win32":
        import ctypes

        getattr(ctypes, "windll").user32.MessageBoxW(None, message, "aha · 打开页面", 0x30)
    elif sys.stderr is not None:
        print(message, file=sys.stderr)


def _launch(data_dir: Path, port: int, *, no_browser: bool, no_tray: bool) -> None:
    instance = acquire_instance(data_dir)
    if isinstance(instance, LaunchDescriptor):
        if sys.stdout is not None:
            print(f"AHA_URL={instance.bootstrap_url}", flush=True)
        if not no_browser:
            open_browser(instance.bootstrap_url, tray_available=False)
        return

    try:
        server = create_server(instance.data_dir, port)
    except BaseException:
        instance.close()
        raise
    runtime = ApplicationRuntime(server, instance)
    try:
        if sys.platform == "win32" and not no_tray:
            from .tray_windows import WindowsTray

            runtime.tray = WindowsTray(
                on_open=lambda: open_browser(server.bootstrap_url, tray_available=True),
                on_exit=runtime.request_shutdown,
                tooltip=f"aha · {instance.data_dir.name}"[:120],
            )
        runtime.start()
        if server.stopping.is_set():
            return
        if sys.stdout is not None:
            print(f"AHA_URL={server.bootstrap_url}", flush=True)
        if not no_browser:
            open_browser(server.bootstrap_url, tray_available=runtime.tray is not None)
        runtime.run()
    except KeyboardInterrupt:
        runtime.request_shutdown()
    finally:
        runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="aha · 本机 Codex 用量与费用证据")
    parser.add_argument("--data-dir", type=Path, default=None, help="应用资料目录（独立于 CCS）")
    parser.add_argument("--port", type=int, default=0, help="本机端口，0 表示自动选择")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument(
        "--no-tray", action="store_true", help="不显示 Windows 托盘（供命令行使用）"
    )
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("端口应在 0 至 65535 之间。")
    data_dir = args.data_dir or default_data_dir()
    try:
        _launch(data_dir, args.port, no_browser=args.no_browser, no_tray=args.no_tray)
    except AppError as error:
        startup_error(parser, error.message)
    except OSError:
        startup_error(parser, "无法启动或关闭本机服务，请检查资料目录、托盘或端口后重试。")


if __name__ == "__main__":
    main()
