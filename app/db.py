"""Database connection settings, read from environment variables (or a .env file)."""
import os
import mysql.connector

def _load_dotenv(path=".env"):
    """Tiny .env reader so no extra package is needed."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

_load_dotenv()

def connect(mode):
    """Open a connection to snl_modern or snl_baseline."""
    if mode not in ("modern", "baseline"):
        raise ValueError("mode must be 'modern' or 'baseline'")
    settings = dict(
        user=os.environ.get("DB_USER", "snl"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get(f"DB_NAME_{mode.upper()}", f"snl_{mode}"),
        autocommit=True,
    )
    if os.environ.get("DB_SOCKET"):
        settings["unix_socket"] = os.environ["DB_SOCKET"]
    else:
        settings["host"] = os.environ.get("DB_HOST", "localhost")
        settings["port"] = int(os.environ.get("DB_PORT", "3306"))
    return mysql.connector.connect(**settings)

def get_repo(mode):
    """Return the repository class for the chosen version."""
    if mode == "modern":
        from app.repo_modern import ModernRepo
        return ModernRepo(connect(mode))
    from app.repo_baseline import BaselineRepo
    return BaselineRepo(connect(mode))
