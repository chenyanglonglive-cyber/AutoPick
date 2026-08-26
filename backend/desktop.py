from __future__ import annotations

import threading
import time
import socket
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn

from backend.autopick.api import create_app


def _existing_autopick_url() -> str | None:
    """Reuse the local service when a second desktop window is opened."""
    url = "http://127.0.0.1:8787"
    try:
        with urlopen(f"{url}/api/health", timeout=0.5) as response:
            if response.status == 200:
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
    only introspects the three picker methods.  Without this, pythonnet's
    ``System.Drawing.Rectangle`` leaks into the reflection walk and crashes
    with ``No method matches given arguments for Rectangle.op_Equality``.
    """

    _EXPOSED = ("select_folder", "select_word_template", "select_checklist")

    def __init__(self) -> None:
        self.window = None

    def __dir__(self):
        return list(self._EXPOSED)

    def select_folder(self):
        import webview

        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None

    def select_word_template(self):
        import webview

        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("Word templates (*.docx;*.docm)", "All files (*.*)"),
        )
        return result[0] if result else None

    def select_checklist(self):
        import webview

        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("Word checklist (*.docx)", "All files (*.*)"),
        )
        return result[0] if result else None


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

    bridge = DesktopBridge()
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
