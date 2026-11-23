"""Load the schema files into a database."""
from pathlib import Path

from app.db import connect

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def run_sql_file(conn, path):
    """Run every statement in a .sql file (comment lines are skipped)."""
    text = "\n".join(line for line in Path(path).read_text().splitlines()
                     if not line.strip().startswith("--"))
    cur = conn.cursor()
    results = []
    for statement in text.split(";"):
        if statement.strip():
            cur.execute(statement)
            if cur.with_rows:                       # SELECTs in the examples
                results.append(cur.fetchall())
    cur.close()
    return results


def reset(mode):
    """(Re)create all tables of one version and load the board layouts."""
    conn = connect(mode)
    run_sql_file(conn, SQL_DIR / f"{mode}.sql")
    run_sql_file(conn, SQL_DIR / "seed.sql")
    conn.close()
