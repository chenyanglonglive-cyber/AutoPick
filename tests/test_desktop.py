from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

from backend.autopick.api import API_VERSION
from backend.desktop import _existing_autopick_url


class _Response(BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_reuses_matching_local_api_version():
    response = _Response(f'{{"status":"ok","api_version":"{API_VERSION}"}}'.encode())

    with patch("backend.desktop.urlopen", return_value=response):
        assert _existing_autopick_url() == "http://127.0.0.1:8787"


def test_does_not_reuse_stale_local_api_version():
    response = _Response(b'{"status":"ok"}')

    with patch("backend.desktop.urlopen", return_value=response):
        assert _existing_autopick_url() is None


def test_desktop_bridge_exposes_select_photos():
    from backend.desktop import DesktopBridge
    bridge = DesktopBridge()
    assert "select_photos" in DesktopBridge._EXPOSED
    assert "select_photos" in dir(bridge)

    class FakeWindow:
        def create_file_dialog(self, dialog_type, allow_multiple=False, file_types=()):
            assert allow_multiple is True
            return ("D:\\photos\\a.jpg", "D:\\photos\\b.jpg")

    bridge.window = FakeWindow()
    selected = bridge.select_photos()
    assert selected == ["D:\\photos\\a.jpg", "D:\\photos\\b.jpg"]
