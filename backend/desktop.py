from __future__ import annotations

import json
import threading
import time
import socket
import os
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn

from backend.autopick.api import API_VERSION, create_app
from backend.autopick.config import load_settings


def _existing_autopick_url() -> str | None:
    """Reuse only a local service that exposes the same UI API contract."""
    url = "http://127.0.0.1:8787"
    try:
        with urlopen(f"{url}/api/health", timeout=0.5) as response:
            payload = json.load(response)
            if response.status == 200 and payload.get("api_version") == API_VERSION:
                return url
    except (URLError, OSError):
        return None
    return None


def _available_port() -> int:
    """Use another loopback port only when 8787 belongs to another program."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class DesktopBridge:
    """Local Windows file pickers exposed only to the embedded Vue UI.

    ``__dir__`` is overridden so that pywebview's ``generate_js_object``
    only introspects the folder picker.  Without this, pythonnet's
    ``System.Drawing.Rectangle`` leaks into the reflection walk and crashes
    with ``No method matches given arguments for Rectangle.op_Equality``.
    """

    _EXPOSED = ("select_folder", "select_feedback_file", "open_data_folder")

    def __init__(self, data_root=None) -> None:
        self.window = None
        self.data_root = data_root

    def __dir__(self):
        return list(self._EXPOSED)

    def select_folder(self):
        import webview

        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None

    def select_feedback_file(self):
        import webview

        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("Excel files (*.xlsx)",),
        )
        return result[0] if result else None

    def open_data_folder(self, project_id: str):
        if not self.data_root or not project_id or any(value in project_id for value in ("/", "\\", "..")):
            return False
        path = (self.data_root / "projects" / project_id).resolve()
        if not path.is_dir() or self.data_root.resolve() not in path.parents:
            return False
        os.startfile(path)  # type: ignore[attr-defined]
        return True

def main() -> None:
    """Launch the local API and an Edge WebView2 window when pywebview is available."""
    base_url = _existing_autopick_url()
    server: uvicorn.Server | None = None
    if base_url is None:
        port = 8787
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))
        except OSError:
            port = _available_port()
        app = create_app()
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        time.sleep(0.6)
        base_url = f"http://127.0.0.1:{port}"

    try:
        import webview
    except ImportError as exc:
        raise SystemExit("pywebview is not installed. Run: python -m pip install pywebview") from exc

    bridge = DesktopBridge(load_settings().data_root)
    window = webview.create_window(
        "AutoPick", base_url, js_api=bridge,
        width=1500, height=980, min_size=(1100, 700),
    )
    bridge.window = window
    webview.start()
    if server is not None:
        server.should_exit = True


if __name__ == "__main__":
    main()
