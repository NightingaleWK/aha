"""Launch the loopback application and open its one-launch bootstrap URL."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import webbrowser
from pathlib import Path
from uuid import uuid4

from .domain import AppError
from .server import create_server


def default_data_dir() -> Path:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else Path.home() / "AppData" / "Local") / "aha"
    local = os.environ.get("XDG_DATA_HOME")
    return (Path(local) if local else Path.home() / ".local" / "share") / "aha"


def write_launch_descriptor(data_dir: Path, bootstrap_url: str) -> tuple[Path, str]:
    """Keep a private credential for windowed launches; never put it in an evidence package."""
    run_id = uuid4().hex
    data = {"pid": os.getpid(), "run_id": run_id, "bootstrap_url": bootstrap_url}
    descriptor = data_dir / "runtime.json"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".runtime-",
            suffix=".tmp",
            dir=data_dir,
            delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump(data, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return descriptor, run_id


def remove_launch_descriptor(descriptor: Path, run_id: str) -> None:
    try:
        data = json.loads(descriptor.read_text(encoding="utf-8"))
        if data.get("run_id") == run_id:
            descriptor.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def startup_error(parser: argparse.ArgumentParser, message: str) -> None:
    if sys.platform == "win32" and sys.stderr is None:
        import ctypes

        getattr(ctypes, "windll").user32.MessageBoxW(None, message, "aha · 无法启动", 0x10)
    parser.exit(1, message + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="aha · 本机 Codex 用量与费用证据")
    parser.add_argument("--data-dir", type=Path, default=None, help="应用资料目录（独立于 CCS）")
    parser.add_argument("--port", type=int, default=0, help="本机端口，0 表示自动选择")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("端口应在 0 至 65535 之间。")
    data_dir = args.data_dir or default_data_dir()
    try:
        server = create_server(data_dir, args.port)
    except AppError as error:
        startup_error(parser, error.message)
    except OSError:
        startup_error(parser, "无法启动本机服务，请检查资料目录权限或改用其他端口。")
    try:
        descriptor, run_id = write_launch_descriptor(data_dir, server.bootstrap_url)
    except OSError:
        server.server_close()
        server.app.close()
        startup_error(parser, "无法写入本次启动信息，请检查资料目录权限。")
    if sys.stdout is not None:
        print(f"AHA_URL={server.bootstrap_url}", flush=True)
    if not args.no_browser:
        try:
            webbrowser.open(server.bootstrap_url)
        except webbrowser.Error:
            if sys.stderr is not None:
                print("浏览器未能自动打开，请打开上面的本机地址。", file=sys.stderr)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.app.close()
        remove_launch_descriptor(descriptor, run_id)


if __name__ == "__main__":
    main()
