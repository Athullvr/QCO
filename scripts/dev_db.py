"""Sandbox-only Postgres+pgvector without Docker (uses the `pgserver` dev dependency).
Prints a DATABASE_URL; the server keeps running after this script exits. Use docker compose in normal setups."""
import sys
from pathlib import Path

import pgserver

pgdata = Path.home() / ".cache" / "qco_watch_pgdata"
srv = pgserver.get_server(pgdata, cleanup_mode=None)
uri = srv.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
print(uri)
sys.exit(0)
