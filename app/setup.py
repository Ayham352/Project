"""One-command setup: databases, application user, tables and board data.

    python -m app.setup                      # asks for the MariaDB root password
    sudo python -m app.setup --socket        # Linux: log in as root without a password
    python -m app.setup --admin-user admin   # use another admin account

It reads DB_USER and DB_PASSWORD from .env. If DB_PASSWORD is empty, a random
password is generated and written into .env, so no password is ever typed
into a file by hand or committed to the repository.
"""
import argparse
import getpass
import os
import secrets
from pathlib import Path

import mysql.connector

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
DATABASES = ("snl_modern", "snl_baseline", "snl_test_modern", "snl_test_baseline")

# GRANT needs the database name as an identifier, which cannot be a %s
# parameter, so each statement is written out in full.
GRANTS = {
    "snl_modern": "GRANT ALL PRIVILEGES ON snl_modern.* TO %s@%s",
    "snl_baseline": "GRANT ALL PRIVILEGES ON snl_baseline.* TO %s@%s",
    "snl_test_modern": "GRANT ALL PRIVILEGES ON snl_test_modern.* TO %s@%s",
    "snl_test_baseline": "GRANT ALL PRIVILEGES ON snl_test_baseline.* TO %s@%s",
}


def ensure_env_file():
    """Create .env from .env.example if needed, and fill in a random password."""
    if not ENV_FILE.exists():
        ENV_FILE.write_text((ROOT / ".env.example").read_text())
        print("created .env from .env.example")
    lines = ENV_FILE.read_text().splitlines()
    changed = False
    for i, line in enumerate(lines):
        for key in ("DB_PASSWORD", "SECRET_KEY"):
            if line.strip() == f"{key}=":
                lines[i] = f"{key}={secrets.token_urlsafe(24)}"
                changed = True
                print(f"generated a random {key} in .env")
    if changed:
        ENV_FILE.write_text("\n".join(lines) + "\n")
    values = {}
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    for key, value in values.items():      # .env wins over stale shell variables
        os.environ[key] = value
    return values


def admin_connection(args):
    settings = {"user": args.admin_user}
    if args.socket:
        settings["unix_socket"] = args.socket_path
    else:
        settings["host"] = args.host
        settings["port"] = args.port
        if "MARIADB_ADMIN_PASSWORD" in os.environ:          # for scripts and CI
            settings["password"] = os.environ["MARIADB_ADMIN_PASSWORD"]
        else:
            settings["password"] = getpass.getpass(f"MariaDB password for {args.admin_user}: ")
    return mysql.connector.connect(**settings)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--admin-user", default="root")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--socket", action="store_true", help="connect through the Unix socket")
    parser.add_argument("--socket-path", default="/run/mysqld/mysqld.sock")
    parser.add_argument("--app-host", default="localhost",
                        help="host part of the app user ('%%' if the app runs in another container)")
    args = parser.parse_args()

    env = ensure_env_file()
    user, password = env.get("DB_USER", "snl"), env["DB_PASSWORD"]

    from app.schema import SQL_DIR, reset, run_sql_file   # after .env is final
    conn = admin_connection(args)
    run_sql_file(conn, SQL_DIR / "setup.sql")
    cur = conn.cursor()
    cur.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (user, args.app_host, password))
    cur.execute("ALTER USER %s@%s IDENTIFIED BY %s", (user, args.app_host, password))
    for database in DATABASES:
        cur.execute(GRANTS[database], (user, args.app_host))
    cur.close()
    conn.close()
    print(f"databases {', '.join(DATABASES)} and user {user}@{args.app_host} are ready")

    for mode in ("modern", "baseline"):
        reset(mode)
        print(f"snl_{mode}: tables and boards created")
    print("done. Start the game with:  python -m app.web")


if __name__ == "__main__":
    main()
