from __future__ import annotations

import threading
from pathlib import Path


class LocalOcrError(RuntimeError):
    """Raised when the optional local OCR runtime is unavailable."""


class LocalOcrClient:
    """Small, process-wide wrapper around RapidOCR's local ONNX models."""

    _engine: object | None = None
    _engine_lock = threading.Lock()

    @classmethod
    def _get_engine(cls) -> object:
        if cls._engine is None:
            with cls._engine_lock:
                if cls._engine is None:
                    try:
                        from rapidocr import RapidOCR
                    except ImportError as exc:  # pragma: no cover - installation error
                        raise LocalOcrError(
                            "本地 OCR 组件未安装。请执行：python -m pip install -r requirements.txt"
                        ) from exc
                    cls._engine = RapidOCR()
        return cls._engine

    def extract_text(self, image_path: Path) -> str:
        """Return normalized text recognised entirely on the local machine."""
        try:
            output = self._get_engine()(str(image_path))
            texts = getattr(output, "txts", ()) or ()
            return " ".join(" ".join(str(text).split()) for text in texts if text).strip()
        except LocalOcrError:
            raise
        except Exception as exc:
            raise LocalOcrError(f"本地 OCR 识别失败：{exc}") from exc
