"""Generate a worker token and the SQL needed to register its hash."""

from __future__ import annotations

import hashlib
import secrets
import sys


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].replace("-", "").replace("_", "").isalnum():
        raise SystemExit("usage: python -m worker.issue_token WORKER_ID")
    worker_id = sys.argv[1]
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode()).hexdigest()
    prefix = token[:8]
    print(f"HGS_WORKER_ID={worker_id}")
    print(f"HGS_WORKER_TOKEN={token}")
    print("\nRegister on the database server:")
    print(
        "INSERT INTO maintenance.worker_clients"
        "(worker_id,display_name,token_hash,token_prefix) VALUES "
        f"('{worker_id}','{worker_id}',decode('{digest}','hex'),'{prefix}');"
    )


if __name__ == "__main__":
    main()
