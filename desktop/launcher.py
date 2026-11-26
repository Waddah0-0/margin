"""Desktop entry point for margin on Windows (pywebview + Edge WebView2).

Starts ``margin-api`` on a free local port in a background thread, serves the bundled web UI,
opens a native window, and shuts the server down cleanly when the window closes.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
from margin_api.app import create_app
from margin_api.settings import ApiSettings

APP_USER_MODEL_ID = "Waddah0-0.Margin.Desktop"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001
        pass


def _show_error(title: str, message: str) -> None:
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        try:
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
            return
        except Exception:  # noqa: BLE001
            pass
    print(f"{title}: {message}", file=sys.stderr)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _resolve_ui_dir() -> Path:
    explicit = os.environ.get("MARGIN_API_UI_DIR")
    if explicit:
        return Path(explicit)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "margin_ui"
        if (bundled / "index.html").is_file():
            return bundled
    dev_dist = REPO_ROOT / "ui" / "dist"
    if (dev_dist / "index.html").is_file():
        return dev_dist
    raise RuntimeError(
        "Built web UI not found. Run `npm run build` in ui/ or use desktop/build_windows.py."
    )


def _desktop_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "margin" if base else Path.home() / ".margin"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _desktop_files_dir() -> Path:
    files = _desktop_root() / "files"
    files.mkdir(parents=True, exist_ok=True)
    return files


def _ensure_stdio() -> None:
    """In PyInstaller ``console=False`` builds on Windows, stdout/stderr are None.

    Redirect them to a local log file so logging and uvicorn never fail on ``isatty()``.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_file = (_desktop_root() / "desktop.log").open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = log_file
    if sys.stderr is None:
        sys.stderr = log_file


def _wait_for_server(base_url: str, thread: threading.Thread, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    health_url = f"{base_url}/health"
    while time.monotonic() < deadline:
        if not thread.is_alive():
            raise RuntimeError("The local margin-api server stopped before becoming ready.")
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for margin-api at {health_url}.")


def _run_smoke_test(base_url: str) -> str:
    health = json.loads(urllib.request.urlopen(f"{base_url}/health", timeout=5).read())
    assert health.get("status") == "ok", f"unexpected /health payload: {health}"

    page_req = urllib.request.Request(f"{base_url}/", headers={"Accept": "text/html"})
    html = urllib.request.urlopen(page_req, timeout=5).read()
    assert b"<title>margin</title>" in html, "bundled UI index.html was not served"

    agents_payload = json.loads(urllib.request.urlopen(f"{base_url}/agents", timeout=5).read())
    ids = sorted(a["id"] for a in agents_payload.get("agents", []))
    errors = agents_payload.get("load_errors", {})
    assert not errors, f"agent load errors: {errors}"
    for expected in ("data-storyteller", "ai-code-detector", "commit-graph", "secret-leaks"):
        assert expected in ids, f"missing bundled agent {expected!r}; found {ids}"

    return (
        f"smoke-test ok: version={health.get('version')} "
        f"git_available={health.get('git_available')} agents={ids}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the margin desktop app.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Start margin-api, verify UI and bundled agents, then exit without a window.",
    )
    parser.add_argument(
        "--smoke-test-out",
        type=Path,
        default=None,
        help="Optional path to write smoke-test output (useful for windowed console=False builds).",
    )
    args = parser.parse_args(argv)

    _ensure_stdio()
    _set_windows_app_id()
    ui_dir = _resolve_ui_dir()
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    settings = ApiSettings(
        host="127.0.0.1",
        port=port,
        ui_dir=str(ui_dir),
        files_dir=str(_desktop_files_dir()),
    )
    app = create_app(settings=settings)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(config)
    # uvicorn installs signal handlers only on the main thread; disable them in our worker thread.
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

    server_error: list[BaseException] = []

    def serve() -> None:
        try:
            server.run()
        except BaseException as exc:  # noqa: BLE001
            server_error.append(exc)

    thread = threading.Thread(target=serve, name="margin-api", daemon=True)
    thread.start()

    try:
        _wait_for_server(base_url, thread)
        if server_error:
            raise server_error[0]

        if args.smoke_test:
            summary = _run_smoke_test(base_url)
            if args.smoke_test_out is not None:
                args.smoke_test_out.write_text(summary + "\n", encoding="utf-8")
            else:
                print(summary)
            return 0

        import webview

        webview.create_window(
            "margin",
            base_url,
            width=1280,
            height=840,
            min_size=(840, 600),
            background_color="#000000",
        )
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)
        return 0
    except Exception as exc:  # noqa: BLE001
        if args.smoke_test:
            if args.smoke_test_out is not None:
                args.smoke_test_out.write_text(f"ERROR: {exc}\n", encoding="utf-8")
            print(f"smoke-test failed: {exc}", file=sys.stderr)
        else:
            _show_error("margin failed to start", str(exc))
        return 1
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


if __name__ == "__main__":
    raise SystemExit(main())
