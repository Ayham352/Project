"""Recreate the tables and board data in both databases (keeps the user).

Run from the repository root:   python -m app.init_db
WARNING: drops existing tables in snl_modern and snl_baseline.
"""
from app.schema import reset

if __name__ == "__main__":
    for mode in ("modern", "baseline"):
        reset(mode)
        print(f"snl_{mode}: tables and boards created")
