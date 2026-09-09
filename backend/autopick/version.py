from __future__ import annotations

import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FALLBACK_VERSION = "Development"


def current_version() -> str:
    """Return the Git tag on the running commit, without failing packaged builds."""
    try:
        result = subprocess.run(
            ["git", "tag", "--points-at", "HEAD"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return FALLBACK_VERSION
    tags = [tag.strip() for tag in result.stdout.splitlines() if tag.strip()]
    return tags[-1] if tags else FALLBACK_VERSION
