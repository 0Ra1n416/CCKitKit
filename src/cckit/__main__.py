"""`python -m cckit` 入口,委托给 cli.main。"""
from __future__ import annotations

from cckit.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
