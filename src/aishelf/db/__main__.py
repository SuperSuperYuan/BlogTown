"""CLI for the derived DB: `python -m aishelf.db sync [--rebuild]`.

Reads AISHELF_DATA_DIR / AISHELF_DB_PATH from the environment so the db
package stays free of any aishelf.site import.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from aishelf.db import schema
from aishelf.db import sync as sync_mod
from aishelf.db.config import default_db_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aishelf.db")
    sub = parser.add_subparsers(dest="command", required=True)
    p_sync = sub.add_parser("sync", help="Sync data files into the SQLite DB")
    p_sync.add_argument("--rebuild", action="store_true", help="Drop and recreate tables first")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    data_dir = Path(os.environ.get("AISHELF_DATA_DIR", "data"))
    db_path = default_db_path(data_dir)

    if args.command == "sync":
        if args.rebuild:
            con = schema.connect(db_path)
            con.executescript(
                "DROP TABLE IF EXISTS items; "
                "DROP TABLE IF EXISTS items_fts; "
                "DROP TABLE IF EXISTS edges;"
            )
            con.commit()
            con.close()
        s = sync_mod.sync(data_dir, db_path)
        print(f"synced: +{s.added} ~{s.updated} -{s.removed} ={s.unchanged}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
