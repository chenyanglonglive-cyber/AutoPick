from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_root: Path
    dashscope_api_key: str | None
    demo_embeddings: bool
    session_token: str
    embedding_dimension: int = 1024
    embedding_model: str = "qwen3-vl-embedding"
    ocr_model: str = "qwen-vl-ocr"
    token_budget: int = 500_000
    qwen_max_retries: int = 8

    @property
    def global_db(self) -> Path:
        return self.data_root / "global.sqlite"

    @property
    def projects_root(self) -> Path:
        return self.data_root / "projects"


def load_settings() -> Settings:
    env_file = Path(".env")
    if env_file.is_file():
        for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    configured_root = os.getenv("AUTOPICK_DATA_ROOT")
    if configured_root:
        root = Path(configured_root).expanduser().resolve()
    elif getattr(sys, "frozen", False):
        root = Path(os.getenv("LOCALAPPDATA", Path.home())) / "AutoPickData"
    else:
        root = Path("AutoPickData").resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "projects").mkdir(exist_ok=True)
    return Settings(
        data_root=root,
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY") or None,
        demo_embeddings=os.getenv("AUTOPICK_DEMO_EMBEDDINGS", "0") == "1",
        session_token=secrets.token_urlsafe(32),
        qwen_max_retries=max(1, int(os.getenv("AUTOPICK_QWEN_MAX_RETRIES", "8"))),
    )
