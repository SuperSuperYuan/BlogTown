"""Launch the display site: python -m aishelf.site"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("AISHELF_SITE_HOST", "127.0.0.1")
    port = int(os.environ.get("AISHELF_SITE_PORT", "8001"))
    # Run the timed-collection scheduler alongside the site unless disabled.
    os.environ.setdefault("AISHELF_SCHEDULER_ENABLED", "1")
    uvicorn.run("aishelf.site.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
