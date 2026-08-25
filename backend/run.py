from __future__ import annotations

import uvicorn

from backend.autopick.api import create_app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8787, log_level="info")
