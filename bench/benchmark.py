"""Measure what UUID, INET6 and RETURNING save, modern vs baseline.

Run from the repository root:   python -m bench.benchmark
WARNING: this drops and recreates all tables in snl_modern and snl_baseline.

Writes results/results.json and results/results.md.
"""
import ipaddress
import json
import os
import platform
import random
import statistics
import time
import uuid
from pathlib import Path

from app.db import connect, get_repo
from app.game import play_turn

N_PLAYERS = int(os.environ.get("BENCH_PLAYERS", 1000))
N_GAMES = int(os.environ.get("BENCH_GAMES", 100_000))
N_LOGINS = int(os.environ.get("BENCH_LOGINS", 200_000))
N_PLAYED = int(os.environ.get("BENCH_PLAYED", 300))      # full games played move by move
SEED = 42
ROOT = Path(__file__).resolve().parent.parent
MODES = ("modern", "baseline")


# ---------- helpers ---------------------------------------------------------
def run_sql_file(conn, path):
    cur = conn.cursor()
    text = "\n".join(l for l in Path(path).read_text().splitlines()
                     if not l.strip().startswith("--"))
    for statement in text.split(";"):
        if statement.strip():
            cur.execute(statement)
    cur.close()


def reset(mode):
    conn = connect(mode)
    run_sql_file(conn, ROOT / "sql" / f"{mode}.sql")
    run_sql_file(conn, ROOT / "sql" / "seed.sql")
    conn.close()


def questions(conn):
    """Number of statements this connection has sent to the server so far."""
    cur = conn.cursor()
    cur.execute("SHOW SESSION STATUS LIKE 'Questions'")
    n = int(cur.fetchone()[1])
    cur.close()
    return n


KNOWN_TABLES = {"games", "game_players", "logins", "char36_python_v4", "uuid_python_v4",
                "uuid_server"}


def table_sizes(conn, tables):
    assert set(tables) <= KNOWN_TABLES          # table names cannot be %s parameters
    cur = conn.cursor()
    for t in tables:
        cur.execute(f"ANALYZE TABLE {t} PERSISTENT FOR ALL")
        cur.fetchall()
    cur.execute("SELECT table_name, data_length, index_length FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name IN (%s)" %
                ",".join(["%s"] * len(tables)), tables)
    sizes = {name: {"data": d, "index": i} for name, d, i in cur.fetchall()}
    cur.close()
    return sizes


def random_ips(n, rng):
    out = []
    for _ in range(n):
        r = rng.random()
        if r < 0.4:
            out.append(f"10.{rng.randrange(256)}.{rng.randrange(256)}.{rng.randrange(1, 255)}")
        elif r < 0.6:
            out.append(f"192.168.{rng.randrange(256)}.{rng.randrange(1, 255)}")
        elif r < 0.8:
            out.append(str(ipaddress.IPv4Address(rng.randrange(1 << 24, 223 << 24))))
        else:
            out.append(str(ipaddress.IPv6Address((0x20010db8 << 96) | rng.getrandbits(96))))
    return out


def batched(rows, size=5000):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


# ---------- 1. storage and insert speed ------------------------------------
def bench_storage(mode):
    rng = random.Random(SEED)
    conn = connect(mode)
    cur = conn.cursor()
    cur.executemany("INSERT INTO players (username, password_hash) VALUES (%s, 'x')",
                    [(f"user{i}",) for i in range(N_PLAYERS)])

    # Games: the modern version lets the server generate the UUID.
    boards = [(rng.choice((1, 2)),) for _ in range(N_GAMES)]
    t0 = time.perf_counter()
    if mode == "modern":
        for chunk in batched(boards):
            cur.executemany("INSERT INTO games (board_id) VALUES (%s)", chunk)
    else:
        rows = [(str(uuid.uuid4()), b) for (b,) in boards]
        for chunk in batched(rows):
            cur.executemany("INSERT INTO games (game_id, board_id) VALUES (%s, %s)", chunk)
    games_s = time.perf_counter() - t0

    # Two seats per game (same SQL in both versions).
    t0 = time.perf_counter()
    cur.execute("INSERT INTO game_players (game_id, player_id, turn_order) "
                "SELECT game_id, 1 + FLOOR(RAND(%s) * %s), 1 FROM games", (SEED, N_PLAYERS))
    cur.execute("INSERT INTO game_players (game_id, player_id, turn_order) "
                "SELECT gp.game_id, 1 + (gp.player_id % %s), 2 FROM game_players gp",
                (N_PLAYERS,))
    seats_s = time.perf_counter() - t0

    # Logins: INET6 needs IPv4 in mapped form; the baseline stores the text as-is.
    ips = random_ips(N_LOGINS, rng)
    if mode == "modern":
        from app.repo_modern import to_inet6
        values = [to_inet6(ip) for ip in ips]
    else:
        values = ips
    rows = [(rng.randrange(1, N_PLAYERS + 1), ip) for ip in values]
    t0 = time.perf_counter()
    for chunk in batched(rows):
        cur.executemany("INSERT INTO logins (player_id, ip) VALUES (%s, %s)", chunk)
    logins_s = time.perf_counter() - t0
    cur.close()

    sizes = table_sizes(conn, ["games", "game_players", "logins"])
    conn.close()
    return {"insert_seconds": {"games": round(games_s, 2), "game_players": round(seats_s, 2),
                               "logins": round(logins_s, 2)},
            "bytes": sizes}


# ---------- 1b. controlled UUID comparison --------------------------------
UUID_VARIANTS = {
    # name: (column type, where the value comes from)
    "char36_python_v4": ("CHAR(36) CHARACTER SET ascii", "python"),
    "uuid_python_v4":   ("UUID", "python"),
    "uuid_server":      ("UUID", "server"),
}


def bench_uuid_control():
    """Same two columns, same row count; only the id type and its source change.

    This separates the two effects behind the games-table result:
    16 bytes instead of 36, and server UUID() values arriving in index order.
    """
    rng = random.Random(SEED)
    boards = [(rng.choice((1, 2)),) for _ in range(N_GAMES)]
    conn = connect("modern")
    cur = conn.cursor()
    out = {}
    for name, (col_type, source) in UUID_VARIANTS.items():
        cur.execute(f"CREATE OR REPLACE TABLE {name} (id {col_type} NOT NULL PRIMARY KEY"
                    f"{' DEFAULT UUID()' if source == 'server' else ''}, "
                    "board_id INT UNSIGNED NOT NULL) ENGINE = InnoDB")
        t0 = time.perf_counter()
        if source == "server":
            for chunk in batched(boards):
                cur.executemany(f"INSERT INTO {name} (board_id) VALUES (%s)", chunk)
        else:
            rows = [(str(uuid.uuid4()), b) for (b,) in boards]
            for chunk in batched(rows):
                cur.executemany(f"INSERT INTO {name} (id, board_id) VALUES (%s, %s)", chunk)
        seconds = time.perf_counter() - t0
        size = table_sizes(conn, [name])[name]
        out[name] = {"type": col_type, "source": source, "insert_seconds": round(seconds, 2),
                     "bytes": size["data"] + size["index"]}
        cur.execute(f"DROP TABLE {name}")
    cur.close()
    conn.close()
    return out


# ---------- 2. statements and time per move --------------------------------
def bench_moves(mode):
    rng = random.Random(SEED)
    repo = get_repo(mode)
    cur = repo.conn.cursor()
    cur.execute("SELECT player_id FROM players ORDER BY player_id LIMIT 2")
    a, b = [r[0] for r in cur.fetchall()]
    cur.close()

    timings, moves = [], 0
    for _ in range(N_PLAYED):
        game_id = repo.create_game(2, a)
        repo.join_game(game_id, b)
        repo.start_game(game_id)
        turn = 0
        while True:
            player = (a, b)[turn % 2]
            t0 = time.perf_counter()
            result = play_turn(repo, game_id, player, roll=rng.randint(1, 6))
            timings.append(time.perf_counter() - t0)
            moves += 1
            turn += 1
            if result["won"]:
                break
    # Count statements of one move precisely on a fresh game.
    game_id = repo.create_game(2, a)
    repo.join_game(game_id, b)
    repo.start_game(game_id)
    q0 = questions(repo.conn)
    play_turn(repo, game_id, a, roll=1)
    per_move = questions(repo.conn) - q0 - 1   # -1: the SHOW STATUS itself
    repo.conn.close()
    return {"moves": moves, "statements_per_move": per_move,
            "ms_per_move_median": round(statistics.median(timings) * 1000, 3),
            "ms_per_move_mean": round(statistics.mean(timings) * 1000, 3)}


# ---------- 3. what the IP column gets right or wrong -----------------------
SAMPLE_IPS = ["10.0.0.9", "10.0.0.10", "10.9.0.1", "10.255.0.1", "192.168.1.5",
              "2001:db8::1", "2001:0db8:0000:0000:0000:0000:0000:0001", "not-an-ip"]


def bench_ip_correctness():
    truth = sorted({ipaddress.ip_address(x) for x in SAMPLE_IPS if x != "not-an-ip"},
                   key=lambda a: (a.version, a))
    in_10 = [x for x in SAMPLE_IPS if x != "not-an-ip"
             and ipaddress.ip_address(x).version == 4
             and ipaddress.ip_address(x) in ipaddress.ip_network("10.0.0.0/8")]
    out = {"sample": SAMPLE_IPS,
           "true": {"distinct": len(truth), "in_10_0_0_0_8": len(in_10),
                    "ipv4_sorted": [str(a) for a in truth if a.version == 4]}}

    # Modern: INET6 column.
    from app.repo_modern import to_inet6
    conn = connect("modern")
    cur = conn.cursor()
    cur.execute("CREATE TEMPORARY TABLE t (ip INET6)")
    rejected = []
    for x in SAMPLE_IPS:
        try:
            cur.execute("INSERT INTO t VALUES (%s)", (to_inet6(x),))
        except ValueError:                  # Python could not even parse it
            rejected.append(x)
        except Exception:                   # MariaDB refused the value
            rejected.append(x)
    try:                                    # what if the app forgets to validate?
        cur.execute("INSERT INTO t VALUES ('not-an-ip')")
        db_rejects_garbage = False
    except Exception:
        db_rejects_garbage = True
    cur.execute("SELECT COUNT(DISTINCT ip) FROM t"); distinct = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM t WHERE ip BETWEEN '::ffff:10.0.0.0' AND '::ffff:10.255.255.255'")
    in_net = cur.fetchone()[0]
    cur.execute("SELECT ip FROM t WHERE ip < '::ffff:255.255.255.255' AND ip > '::ffff:0.0.0.0' ORDER BY ip")
    order = [r[0].replace("::ffff:", "") for r in cur.fetchall()]
    conn.close()
    out["modern"] = {"rejected": rejected, "db_rejects_garbage": db_rejects_garbage,
                     "distinct": distinct, "in_10_0_0_0_8": in_net, "ipv4_sorted": order}

    # Baseline: VARCHAR column, the SQL a developer would naturally write.
    conn = connect("baseline")
    cur = conn.cursor()
    cur.execute("CREATE TEMPORARY TABLE t (ip VARCHAR(45) CHARACTER SET ascii)")
    for x in SAMPLE_IPS:
        cur.execute("INSERT INTO t VALUES (%s)", (x,))
    cur.execute("SELECT COUNT(DISTINCT ip) FROM t"); distinct = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM t WHERE ip BETWEEN '10.0.0.0' AND '10.255.255.255'")
    in_net = cur.fetchone()[0]
    cur.execute("SELECT ip FROM t WHERE ip NOT LIKE '%:%' AND ip REGEXP '^[0-9.]+$' ORDER BY ip")
    order = [r[0] for r in cur.fetchall()]
    conn.close()
    out["baseline_naive_sql"] = {"rejected": [], "db_rejects_garbage": False,
                                 "distinct": distinct, "in_10_0_0_0_8": in_net,
                                 "ipv4_sorted": order}
    return out


# ---------- 4. network search on the big table ------------------------------
def bench_network_search(mode, cidr="10.0.0.0/8", repeats=5):
    repo = get_repo(mode)
    times, count = [], None
    for _ in range(repeats):
        t0 = time.perf_counter()
        count = len(repo.logins_in_network(cidr))
        times.append(time.perf_counter() - t0)
    distinct_t0 = time.perf_counter()
    distinct = repo.count_distinct_ips()
    distinct_s = time.perf_counter() - distinct_t0
    repo.conn.close()
    return {"cidr": cidr, "rows_found": count,
            "ms_median": round(statistics.median(times) * 1000, 1),
            "distinct_ips": distinct, "distinct_ms": round(distinct_s * 1000, 1)}


# ---------- 5. code size ----------------------------------------------------
def code_lines(path):
    """Non-blank lines that are not comments or docstrings."""
    count, in_doc = 0, False
    for line in Path(path).read_text().splitlines():
        s = line.strip()
        if s.startswith('"""'):
            if not (len(s) > 3 and s.endswith('"""')):
                in_doc = not in_doc
            continue
        if in_doc or not s or s.startswith("#"):
            continue
        count += 1
    return count


# ---------- main ------------------------------------------------------------
def server_version():
    conn = connect("modern")
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    v = cur.fetchone()[0]
    conn.close()
    return v


def main():
    results = {"mariadb_version": server_version(), "python": platform.python_version(),
               "machine": platform.platform(),
               "sizes": {"players": N_PLAYERS, "games": N_GAMES, "logins": N_LOGINS,
                         "games_played": N_PLAYED}}
    for mode in MODES:
        print(f"[{mode}] resetting and loading data ...", flush=True)
        reset(mode)
        results.setdefault("storage", {})[mode] = bench_storage(mode)
        print(f"[{mode}] network search ...", flush=True)
        results.setdefault("network_search", {})[mode] = bench_network_search(mode)
        print(f"[{mode}] playing {N_PLAYED} games ...", flush=True)
        results.setdefault("moves", {})[mode] = bench_moves(mode)
    print("[uuid] controlled comparison ...", flush=True)
    results["uuid_control"] = bench_uuid_control()
    results["ip_correctness"] = bench_ip_correctness()
    results["code_lines"] = {m: code_lines(ROOT / "app" / f"repo_{m}.py") for m in MODES}
    results["code_lines"]["shared"] = code_lines(ROOT / "app" / "repo_common.py")

    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))
    (out_dir / "results.md").write_text(to_markdown(results))
    print((out_dir / "results.md").read_text())


def mb(n):
    return f"{n / 1024 / 1024:.1f} MB"


def pct(new, old):
    return f"{(new - old) / old * 100:+.0f}%" if old else "n/a"


def to_markdown(r):
    s, m, b = r["storage"], "modern", "baseline"
    lines = [f"Measured on MariaDB {r['mariadb_version']}, Python {r['python']}, {r['machine']}.",
             f"Data: {r['sizes']['games']:,} games (2 players each), {r['sizes']['logins']:,} logins, "
             f"{r['sizes']['games_played']} games played move by move.", "",
             "### Storage (InnoDB data + indexes)", "",
             "| Table | Modern | Baseline | Modern vs baseline |", "|---|---|---|---|"]
    for t in ("games", "game_players", "logins"):
        mt = s[m]["bytes"][t]["data"] + s[m]["bytes"][t]["index"]
        bt = s[b]["bytes"][t]["data"] + s[b]["bytes"][t]["index"]
        lines.append(f"| `{t}` | {mb(mt)} | {mb(bt)} | {pct(mt, bt)} |")
    u = r["uuid_control"]
    base = u["char36_python_v4"]["bytes"]
    lines += ["", "### UUID: controlled comparison (same 2 columns, only the id changes)", "",
              "| id column | Value comes from | Size | vs CHAR(36) | Insert time |",
              "|---|---|---|---|---|"]
    for name, v in u.items():
        src = "server `UUID()`" if v["source"] == "server" else "Python `uuid4()`"
        lines.append(f"| `{v['type']}` | {src} | {mb(v['bytes'])} | {pct(v['bytes'], base)} "
                     f"| {v['insert_seconds']} s |")
    lines += [
              "", "### Insert time", "", "| Step | Modern | Baseline |", "|---|---|---|"]
    for k in ("games", "game_players", "logins"):
        lines.append(f"| {k} | {s[m]['insert_seconds'][k]} s | {s[b]['insert_seconds'][k]} s |")
    mv = r["moves"]
    lines += ["", "### One move of the game (a full transaction)", "",
              "| | Modern | Baseline |", "|---|---|---|",
              f"| Statements sent to the server per move | {mv[m]['statements_per_move']} | {mv[b]['statements_per_move']} |",
              f"| Median time per move | {mv[m]['ms_per_move_median']} ms | {mv[b]['ms_per_move_median']} ms |",
              f"| Moves measured | {mv[m]['moves']:,} | {mv[b]['moves']:,} |"]
    ns = r["network_search"]
    lines += ["", f"### Search logins in `{ns[m]['cidr']}` and count distinct addresses", "",
              "| | Modern | Baseline |", "|---|---|---|",
              f"| Rows found | {ns[m]['rows_found']:,} | {ns[b]['rows_found']:,} |",
              f"| Median search time | {ns[m]['ms_median']} ms | {ns[b]['ms_median']} ms |",
              f"| Distinct addresses | {ns[m]['distinct_ips']:,} | {ns[b]['distinct_ips']:,} |",
              f"| Time to count them | {ns[m]['distinct_ms']} ms | {ns[b]['distinct_ms']} ms |"]
    ip = r["ip_correctness"]
    t, mo, bn = ip["true"], ip["modern"], ip["baseline_naive_sql"]
    lines += ["", "### Correctness on 8 sample values (`" + "`, `".join(ip["sample"]) + "`)", "",
              "| Check | Correct answer | Modern (`INET6`) | Baseline, plain SQL on text |",
              "|---|---|---|---|",
              f"| Database refuses `not-an-ip` | yes | {'yes' if mo['db_rejects_garbage'] else 'no'} | {'yes' if bn['db_rejects_garbage'] else 'no'} |",
              f"| `COUNT(DISTINCT ip)` | {t['distinct']} | {mo['distinct']} | {bn['distinct']} |",
              f"| Rows in 10.0.0.0/8 with `BETWEEN` | {t['in_10_0_0_0_8']} | {mo['in_10_0_0_0_8']} | {bn['in_10_0_0_0_8']} |",
              f"| IPv4 `ORDER BY ip` | {', '.join(t['ipv4_sorted'])} | {', '.join(mo['ipv4_sorted'])} | {', '.join(bn['ipv4_sorted'])} |"]
    c = r["code_lines"]
    lines += ["", "### Code", "", "| | Modern | Baseline |", "|---|---|---|",
              f"| Lines in the version-specific repository file | {c[m]} | {c[b]} |",
              f"| Shared code (`repo_common.py`, `game.py`, web app) | same | same |"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
