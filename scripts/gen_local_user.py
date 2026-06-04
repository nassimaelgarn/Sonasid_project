#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from backend.security.auth import hash_password


def main() -> int:
    if len(sys.argv) < 4:
        print("Usage: python scripts/gen_local_user.py <username> <display_name> <password> [email]", file=sys.stderr)
        return 2
    username = sys.argv[1].strip()
    display_name = sys.argv[2].strip()
    password = sys.argv[3]
    email = (sys.argv[4].strip() if len(sys.argv) >= 5 else "")

    spec = hash_password(password)
    payload = {
        "users": {
            username: {
                "display_name": display_name,
                "email": email,
                "password": spec,
            }
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

