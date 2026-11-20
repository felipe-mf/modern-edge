"""Connectivity check: `python -m northgate.smoke` reads one thing from each client system.

Read-only. Useful to confirm the containers can reach the systems and the credentials work.
"""

import logging
import sys

from northgate.clients import build_clients
from northgate.config import load_settings


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    payroll, dispatch, finance = build_clients(settings)
    checks = {
        "payroll employees": lambda: len(payroll.employees()),
        "dispatch sites": lambda: len(dispatch.sites()),
        "finance entities": lambda: len(finance.entities()),
    }
    ok = True
    for name, check in checks.items():
        try:
            print(f"OK   {name}: {check()}")
        except Exception as exc:  # noqa: BLE001 - report every failure, not just the first
            ok = False
            print(f"FAIL {name}: {exc}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
