"""Launch the Hermes WebUI: python -m aishelf.webui"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("HERMES_WEBUI_HOST", "127.0.0.1")
    port = int(os.environ.get("HERMES_WEBUI_PORT", "8000"))
    uvicorn.run("aishelf.webui.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
