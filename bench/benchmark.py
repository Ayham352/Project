"""Measure what the Area 1 features save: modern vs baseline.

Run from the repository root:   python -m bench.benchmark
WARNING: drops and recreates all tables in snl_modern and snl_baseline.

Every timed part is repeated BENCH_REPEATS times (default 3); the report
gives the median and the standard deviation. Results go to
results/results.json (all raw numbers) and results/results.md (tables).

Sizes can be changed with environment variables (defaults in brackets):
BENCH_GAMES [100000], BENCH_LOGINS [200000], BENCH_PLAYED [300],
BENCH_MIGRATION_ROWS [300000], BENCH_REPEATS [3].
"""
import ipaddress
import json
import os
import platform
import random
import statistics
import threading
import time
import uuid
from pathlib import Path

from app.db import connect, get_repo
from app.game import play_turn
from app.repo_modern import to_inet6
from app.schema import reset

N_PLAYERS = int(os.environ.get("BENCH_PLAYERS", 1000))
N_GAMES = int(os.environ.get("BENCH_GAMES", 100_000))
N_LOGINS = int(os.environ.get("BENCH_LOGINS", 200_000))
N_PLAYED = int(os.environ.get("BENCH_PLAYED", 300))
N_MIGRATION = int(os.environ.get("BENCH_MIGRATION_ROWS", 300_000))
REPEATS = int(os.environ.get("BENCH_REPEATS", 3))
SEED = 42
ROOT = Path(__file__).resolve().parent.parent
MODES = ("modern", "baseline")

# Table names and column types cannot be %s parameters, so every statement
# that needs one is written out in full here: no SQL is built from strings.
SIZE_QUERY = ("SELECT data_length, index_length FROM information_schema.tables "
              "WHERE table_schema = DATABASE() AND table_name = %s")
ANALYZE = {
    "games": "ANALYZE TABLE games PERSISTENT FOR ALL",
    "game_players": "ANALYZE TABLE game_players PERSISTENT FOR ALL",
    "logins": "ANALYZE TABLE logins PERSISTENT FOR ALL",
    "id_char36_python": "ANALYZE TABLE id_char36_python PERSISTENT FOR ALL",
    "id_uuid_python": "ANALYZE TABLE id_uuid_python PERSISTENT FOR ALL",
    "id_uuid_server": "ANALYZE TABLE id_uuid_server PERSISTENT FOR ALL",
    "ip4_varchar": "ANALYZE TABLE ip4_varchar PERSISTENT FOR ALL",
    "ip4_inet6": "ANALYZE TABLE ip4_inet6 PERSISTENT FOR ALL",
    "ip4_inet4": "ANALYZE TABLE ip4_inet4 PERSISTENT FOR ALL",
    "mig": "ANALYZE TABLE mig PERSISTENT FOR ALL",
}


# ---------- helpers -----------------------------------------------------------
def stats(values):
    values = list(values)
    return {"median": round(statistics.median(values), 4),
            "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
            "runs": [round(v, 4) for v in values]}


def size_of(conn, table):
    cur = conn.cursor()
    cur.execute(ANALYZE[table])
    cur.fetchall()
    cur.execute(SIZE_QUERY, (table,))
    data, index = cur.fetchone()
    cur.close()
    return {"data": data, "index": index, "total": data + index}


def questions(conn):
    """Number of statements this connection has sent to the server so far."""
    cur = conn.cursor()
    cur.execute("SHOW SESSION STATUS LIKE 'Questions'")
    n = int(cur.fetchone()[1])
    cur.close()
    return n


def batched(rows, size=5000):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def random_ips(n, rng, ipv6_share=0.2):
    out = []
    for _ in range(n):
        r = rng.random()
        if r < ipv6_share:
            out.append(str(ipaddress.IPv6Address((0x20010db8 << 96) | rng.getrandbits(96))))
        elif r < 0.6:
            out.append(f"10.{rng.randrange(256)}.{rng.randrange(256)}.{rng.randrange(1, 255)}")
        elif r < 0.8:
            out.append(f"192.168.{rng.randrange(256)}.{rng.randrange(1, 255)}")
        else:
            out.append(str(ipaddress.IPv4Address(rng.randrange(1 << 24, 223 << 24))))
    return out


# ---------- 1. storage and insert time -----------------------------------------
def bench_storage(mode):
    rng = random.Random(SEED)
    conn = connect(mode)
    cur = conn.cursor()
    cur.executemany("INSERT INTO players (username, password_hash) VALUES (%s, 'x')",
                    [(f"user{i}",) for i in range(N_PLAYERS)])

    boards = [(rng.choice((1, 2)),) for _ in range(N_GAMES)]
    t0 = time.perf_counter()
    if mode == "modern":            # the server generates the UUID
        for chunk in batched(boards):
            cur.executemany("INSERT INTO games (board_id) VALUES (%s)", chunk)
    else:                           # the application generates it
        rows = [(str(uuid.uuid4()), b) for (b,) in boards]
        for chunk in batched(rows):
            cur.executemany("INSERT INTO games (game_id, board_id) VALUES (%s, %s)", chunk)
    games_s = time.perf_counter() - t0

    t0 = time.perf_counter()        # two seats per game, same SQL in both versions
    cur.execute("INSERT INTO game_players (game_id, player_id, turn_order) "
                "SELECT game_id, 1 + FLOOR(RAND(%s) * %s), 1 FROM games", (SEED, N_PLAYERS))
    cur.execute("INSERT INTO game_players (game_id, player_id, turn_order) "
                "SELECT game_id, 1 + MOD(player_id, %s), 2 FROM game_players", (N_PLAYERS,))
    seats_s = time.perf_counter() - t0

    ips = random_ips(N_LOGINS, rng)
    values = [to_inet6(ip) for ip in ips] if mode == "modern" else ips
    rows = [(rng.randrange(1, N_PLAYERS + 1), ip) for ip in values]
    t0 = time.perf_counter()
    for chunk in batched(rows):
        cur.executemany("INSERT INTO logins (player_id, ip) VALUES (%s, %s)", chunk)
    logins_s = time.perf_counter() - t0
    cur.close()

    sizes = {t: size_of(conn, t) for t in ("games", "game_players", "logins")}
    conn.close()
    return {"seconds": {"games": games_s, "game_players": seats_s, "logins": logins_s},
            "bytes": sizes}


# ---------- 2. statements and time per move -------------------------------------
def bench_moves(mode):
    rng = random.Random(SEED)
    repo = get_repo(mode)
    cur = repo.conn.cursor()
    cur.execute("SELECT player_id FROM players ORDER BY player_id LIMIT 2")
    a, b = [r[0] for r in cur.fetchall()]
    cur.close()

    timings = []
    for _ in range(N_PLAYED):
        game_id = repo.create_game(2, a)
        repo.join_game(game_id, b)
        repo.start_game(game_id)
        turn = 0
        while True:
            t0 = time.perf_counter()
            result = play_turn(repo, game_id, (a, b)[turn % 2], roll=rng.randint(1, 6))
            timings.append(time.perf_counter() - t0)
            turn += 1
            if result["won"]:
                break

    def count(action):
        q0 = questions(repo.conn)
        action()
        return questions(repo.conn) - q0 - 1        # -1: the SHOW STATUS itself

    game_id = repo.create_game(2, a)
    repo.join_game(game_id, b)
    repo.start_game(game_id)
    per_move = count(lambda: play_turn(repo, game_id, a, roll=1))
    per_create = count(lambda: repo.create_game(1, a))
    waiting = repo.create_game(1, a)
    repo.join_game(waiting, b)
    per_leave = count(lambda: repo.leave_game(waiting, b))
    repo.conn.close()
    return {"moves": len(timings), "statements": {"move": per_move, "create_game": per_create,
                                                  "leave_game": per_leave},
            "ms_per_move_median": statistics.median(timings) * 1000}


# ---------- 3. network search and distinct count on the big table ---------------
NETWORKS = ("10.0.0.0/8", "10.1.0.0/16")      # wide (about 40% of rows) and narrow


def bench_network(mode, tries=5):
    repo = get_repo(mode)
    out = {}
    for cidr in NETWORKS:
        times = []
        for _ in range(tries):
            t0 = time.perf_counter()
            found = len(repo.logins_in_network(cidr))
            times.append(time.perf_counter() - t0)
        out[cidr] = {"rows_found": found, "ms": statistics.median(times) * 1000}
    times = []
    for _ in range(tries):
        t0 = time.perf_counter()
        distinct = repo.count_distinct_ips()
        times.append(time.perf_counter() - t0)
    repo.conn.close()
    out["distinct"] = {"count": distinct, "ms": statistics.median(times) * 1000}
    return out


def explain_network():
    """How the server runs each version's network query, for both networks."""
    out = {}
    for cidr in NETWORKS:
        net = ipaddress.ip_network(cidr)
        lo, hi = to_inet6(str(net.network_address)), to_inet6(str(net.broadcast_address))
        for mode, sql, params in (
                ("modern", "EXPLAIN SELECT login_id, player_id, ip FROM logins "
                           "WHERE ip BETWEEN %s AND %s ORDER BY ip", (lo, hi)),
                ("baseline", "EXPLAIN SELECT login_id, player_id, ip FROM logins", ())):
            conn = connect(mode)
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, params)
            row = cur.fetchone()
            cur.close()
            conn.close()
            out.setdefault(cidr, {})[mode] = {"type": row["type"], "key": row["key"],
                                              "rows": int(row["rows"])}
    return out


# ---------- 4. controlled UUID comparison ------------------------------------------
UUID_VARIANTS = {
    "id_char36_python": {
        "label": ("CHAR(36) ascii", "Python uuid4()"),
        "create": "CREATE OR REPLACE TABLE id_char36_python (id CHAR(36) CHARACTER SET ascii "
                  "NOT NULL PRIMARY KEY, board_id INT UNSIGNED NOT NULL) ENGINE = InnoDB",
        "insert": "INSERT INTO id_char36_python (id, board_id) VALUES (%s, %s)",
        "drop": "DROP TABLE id_char36_python"},
    "id_uuid_python": {
        "label": ("UUID", "Python uuid4()"),
        "create": "CREATE OR REPLACE TABLE id_uuid_python (id UUID NOT NULL PRIMARY KEY, "
                  "board_id INT UNSIGNED NOT NULL) ENGINE = InnoDB",
        "insert": "INSERT INTO id_uuid_python (id, board_id) VALUES (%s, %s)",
        "drop": "DROP TABLE id_uuid_python"},
    "id_uuid_server": {
        "label": ("UUID", "server UUID()"),
        "create": "CREATE OR REPLACE TABLE id_uuid_server (id UUID NOT NULL DEFAULT UUID() "
                  "PRIMARY KEY, board_id INT UNSIGNED NOT NULL) ENGINE = InnoDB",
        "insert": "INSERT INTO id_uuid_server (board_id) VALUES (%s)",
        "drop": "DROP TABLE id_uuid_server"},
}


def bench_uuid_control():
    """Same 2 columns and row count; only the id type and where it comes from change."""
    rng = random.Random(SEED)
    boards = [rng.choice((1, 2)) for _ in range(N_GAMES)]
    conn = connect("modern")
    cur = conn.cursor()
    out = {}
    for name, v in UUID_VARIANTS.items():
        cur.execute(v["create"])
        if v["label"][1].startswith("server"):
            rows = [(b,) for b in boards]
        else:
            rows = [(str(uuid.uuid4()), b) for b in boards]
        t0 = time.perf_counter()
        for chunk in batched(rows):
            cur.executemany(v["insert"], chunk)
        seconds = time.perf_counter() - t0
        out[name] = {"type": v["label"][0], "source": v["label"][1], "seconds": seconds,
                     "bytes": size_of(conn, name)["total"]}
        cur.execute(v["drop"])
    cur.close()
    conn.close()
    return out


# ---------- 5. IPv4-only data: VARCHAR vs INET6 vs INET4 ------------------------------
IP4_VARIANTS = {
    "ip4_varchar": ("VARCHAR(15) ascii",
                    "CREATE OR REPLACE TABLE ip4_varchar (id INT UNSIGNED AUTO_INCREMENT PRIMARY "
                    "KEY, ip VARCHAR(15) CHARACTER SET ascii NOT NULL, INDEX (ip)) ENGINE = InnoDB",
                    "INSERT INTO ip4_varchar (ip) VALUES (%s)", "DROP TABLE ip4_varchar"),
    "ip4_inet6": ("INET6 (IPv4-mapped)",
                  "CREATE OR REPLACE TABLE ip4_inet6 (id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, "
                  "ip INET6 NOT NULL, INDEX (ip)) ENGINE = InnoDB",
                  "INSERT INTO ip4_inet6 (ip) VALUES (%s)", "DROP TABLE ip4_inet6"),
    "ip4_inet4": ("INET4",
                  "CREATE OR REPLACE TABLE ip4_inet4 (id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY, "
                  "ip INET4 NOT NULL, INDEX (ip)) ENGINE = InnoDB",
                  "INSERT INTO ip4_inet4 (ip) VALUES (%s)", "DROP TABLE ip4_inet4"),
}


def bench_ipv4_only():
    rng = random.Random(SEED)
    ips = random_ips(N_LOGINS, rng, ipv6_share=0.0)
    conn = connect("modern")
    cur = conn.cursor()
    out = {}
    for name, (label, create, insert, drop) in IP4_VARIANTS.items():
        cur.execute(create)
        values = [(to_inet6(ip),) for ip in ips] if name == "ip4_inet6" else [(ip,) for ip in ips]
        for chunk in batched(values):
            cur.executemany(insert, chunk)
        out[name] = {"type": label, "bytes": size_of(conn, name)["total"]}
        cur.execute(drop)
    cur.close()
    conn.close()
    return out


# ---------- 6. correctness of IP queries ---------------------------------------------
SAMPLE_IPS = ["10.0.0.9", "10.0.0.10", "10.9.0.1", "10.255.0.1", "192.168.1.5",
              "2001:db8::1", "2001:0db8:0000:0000:0000:0000:0000:0001", "not-an-ip"]


def bench_ip_correctness():
    valid = [ipaddress.ip_address(x) for x in SAMPLE_IPS if x != "not-an-ip"]
    net = ipaddress.ip_network("10.0.0.0/8")
    out = {"sample": SAMPLE_IPS,
           "true": {"distinct": len(set(valid)),
                    "in_10_0_0_0_8": sum(1 for a in valid if a.version == 4 and a in net),
                    "ipv4_sorted": [str(a) for a in sorted(a for a in valid if a.version == 4)]}}

    conn = connect("modern")
    cur = conn.cursor()
    cur.execute("CREATE OR REPLACE TEMPORARY TABLE t (ip INET6)")
    for x in SAMPLE_IPS:
        try:
            cur.execute("INSERT INTO t VALUES (%s)", (to_inet6(x),))
        except ValueError:
            pass                                   # Python refuses to convert it
    try:                                           # and if the application forgets?
        cur.execute("INSERT INTO t VALUES ('not-an-ip')")
        refused, error = False, None
    except Exception as err:                       # noqa: BLE001 - we want the message
        refused, error = True, str(err)
    cur.execute("SELECT COUNT(DISTINCT ip) FROM t")
    distinct = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM t WHERE ip BETWEEN '::ffff:10.0.0.0' AND '::ffff:10.255.255.255'")
    in_net = cur.fetchone()[0]
    cur.execute("SELECT ip FROM t WHERE ip BETWEEN '::ffff:0.0.0.0' AND '::ffff:255.255.255.255' ORDER BY ip")
    order = [r[0].replace("::ffff:", "") for r in cur.fetchall()]
    conn.close()
    out["modern"] = {"refuses_garbage": refused, "error": error, "distinct": distinct,
                     "in_10_0_0_0_8": in_net, "ipv4_sorted": order}

    conn = connect("baseline")
    cur = conn.cursor()
    cur.execute("CREATE OR REPLACE TEMPORARY TABLE t (ip VARCHAR(45) CHARACTER SET ascii)")
    cur.executemany("INSERT INTO t VALUES (%s)", [(x,) for x in SAMPLE_IPS])
    cur.execute("SELECT COUNT(DISTINCT ip) FROM t")
    distinct = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM t WHERE ip BETWEEN '10.0.0.0' AND '10.255.255.255'")
    in_net = cur.fetchone()[0]
    cur.execute("SELECT ip FROM t WHERE ip REGEXP '^[0-9.]+$' ORDER BY ip")
    order = [r[0] for r in cur.fetchall()]
    conn.close()
    out["baseline"] = {"refuses_garbage": False, "distinct": distinct,
                       "in_10_0_0_0_8": in_net, "ipv4_sorted": order}
    return out


# ---------- 7. schema change under live writes ------------------------------------------
MIGRATION = {
    "template": ("CREATE OR REPLACE TABLE mig_template (id BIGINT UNSIGNED AUTO_INCREMENT "
                 "PRIMARY KEY, player_id INT UNSIGNED NOT NULL, ip INET6 NOT NULL, "
                 "note VARCHAR(200) NOT NULL DEFAULT '') ENGINE = InnoDB"),
    "fill": "INSERT INTO mig_template (player_id, ip, note) VALUES (%s, %s, %s)",
    "like": "CREATE OR REPLACE TABLE mig LIKE mig_template",
    "copy": "INSERT INTO mig SELECT * FROM mig_template",
    "write": "INSERT INTO mig (player_id, ip) VALUES (1, '::ffff:10.0.0.1')",
    # INSTANT       : change the table's metadata only
    # INPLACE       : as written; MariaDB may still choose INSTANT (it is "at least" INPLACE)
    # INPLACE+FORCE : a real online rebuild (the pre-10.3 way to add a column without blocking)
    # COPY          : rebuild into a new table, blocking writes (the oldest way)
    "add": {
        "INSTANT": "ALTER TABLE mig ADD COLUMN user_agent VARCHAR(255) NULL, ALGORITHM=INSTANT",
        "INPLACE": "ALTER TABLE mig ADD COLUMN user_agent VARCHAR(255) NULL, ALGORITHM=INPLACE, LOCK=NONE",
        "INPLACE+FORCE": "ALTER TABLE mig ADD COLUMN user_agent VARCHAR(255) NULL, FORCE, "
                         "ALGORITHM=INPLACE, LOCK=NONE",
        "COPY": "ALTER TABLE mig ADD COLUMN user_agent VARCHAR(255) NULL, ALGORITHM=COPY"},
    "drop": {
        "INSTANT": "ALTER TABLE mig DROP COLUMN note, ALGORITHM=INSTANT",
        "INPLACE": "ALTER TABLE mig DROP COLUMN note, ALGORITHM=INPLACE, LOCK=NONE",
        "INPLACE+FORCE": "ALTER TABLE mig DROP COLUMN note, FORCE, ALGORITHM=INPLACE, LOCK=NONE",
        "COPY": "ALTER TABLE mig DROP COLUMN note, ALGORITHM=COPY"},
    "impossible": "ALTER TABLE mig MODIFY ip VARCHAR(45) NOT NULL, ALGORITHM=INSTANT",
    "cleanup": "DROP TABLE IF EXISTS mig, mig_template",
}


class Writer(threading.Thread):
    """Inserts one row at a time, as the live game would, and times each insert."""

    def __init__(self):
        super().__init__(daemon=True)
        self.conn = connect("modern")
        self.samples = []               # (finish time, latency)
        self.stop = threading.Event()

    def run(self):
        cur = self.conn.cursor()
        while not self.stop.is_set():
            t0 = time.perf_counter()
            cur.execute(MIGRATION["write"])
            t1 = time.perf_counter()
            self.samples.append((t1, t1 - t0))
        cur.close()
        self.conn.close()

    def during(self, start, end):
        """Latencies of the writes whose time in flight overlapped [start, end]."""
        return [lat for t, lat in self.samples if t >= start and t - lat <= end]


def build_migration_template(conn):
    rng = random.Random(SEED)
    cur = conn.cursor()
    cur.execute(MIGRATION["template"])
    rows = [(rng.randrange(1, 1000), to_inet6(ip), "x" * 100)
            for ip in random_ips(N_MIGRATION, rng)]
    for chunk in batched(rows):
        cur.executemany(MIGRATION["fill"], chunk)
    cur.close()


def bench_migration(conn, algorithm):
    cur = conn.cursor()
    cur.execute(MIGRATION["like"])
    cur.execute(MIGRATION["copy"])
    before = size_of(conn, "mig")["data"]
    writer = Writer()
    writer.start()
    time.sleep(0.5)
    result = {}
    for step in ("add", "drop"):
        t0 = time.perf_counter()
        cur.execute(MIGRATION[step][algorithm])
        t1 = time.perf_counter()
        time.sleep(0.3)
        waits = writer.during(t0, t1)
        result[step] = {"seconds": t1 - t0, "writes_during": len(waits),
                        "max_write_wait_ms": max(waits) * 1000 if waits else None}
    writer.stop.set()
    writer.join()
    result["data_bytes_before"] = before
    result["data_bytes_after_drop"] = size_of(conn, "mig")["data"]
    cur.close()
    return result


def bench_migrations():
    conn = connect("modern")
    build_migration_template(conn)
    runs = {a: [] for a in ("INSTANT", "INPLACE", "INPLACE+FORCE", "COPY")}
    for _ in range(REPEATS):
        for algorithm in runs:
            runs[algorithm].append(bench_migration(conn, algorithm))
    cur = conn.cursor()
    try:                               # a change that cannot be instant
        cur.execute(MIGRATION["impossible"])
        impossible = "accepted (unexpected)"
    except Exception as err:           # noqa: BLE001 - we report the server's message
        impossible = str(err)
    cur.execute(MIGRATION["cleanup"])
    cur.close()
    conn.close()
    summary = {}
    for algorithm, rs in runs.items():
        summary[algorithm] = {
            step: {"seconds": stats(r[step]["seconds"] for r in rs),
                   "max_write_wait_ms": stats(r[step]["max_write_wait_ms"] or 0 for r in rs),
                   "writes_during": stats(r[step]["writes_during"] for r in rs)}
            for step in ("add", "drop")}
        summary[algorithm]["data_mb_before"] = rs[-1]["data_bytes_before"] / 2**20
        summary[algorithm]["data_mb_after_drop"] = rs[-1]["data_bytes_after_drop"] / 2**20
    return {"rows": N_MIGRATION, "algorithms": summary, "impossible_instant_change": impossible}


# ---------- 8. schema scripts ---------------------------------------------------------------
def schema_script_facts():
    out = {}
    for mode in MODES:
        text = "\n".join(line for line in (ROOT / "sql" / f"{mode}.sql").read_text().splitlines()
                         if not line.strip().startswith("--"))
        out[mode] = {"create_or_replace": text.count("CREATE OR REPLACE TABLE"),
                     "drop_if_exists_lists": text.count("DROP TABLE IF EXISTS")}
    t0 = time.perf_counter()
    reset("modern")
    out["modern"]["rerun_seconds"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    reset("baseline")
    out["baseline"]["rerun_seconds"] = time.perf_counter() - t0
    return out


# ---------- 9. code size --------------------------------------------------------------------
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


# ---------- main ------------------------------------------------------------------------------
def server_version():
    conn = connect("modern")
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    v = cur.fetchone()[0]
    conn.close()
    return v


def main():
    results = {"mariadb_version": server_version(), "python": platform.python_version(),
               "machine": platform.platform(), "cpu_count": os.cpu_count(), "repeats": REPEATS,
               "sizes": {"players": N_PLAYERS, "games": N_GAMES, "logins": N_LOGINS,
                         "games_played": N_PLAYED, "migration_rows": N_MIGRATION}}
    raw = {m: {"storage": [], "moves": [], "network": []} for m in MODES}
    for r in range(REPEATS):
        for mode in MODES:
            print(f"run {r + 1}/{REPEATS} [{mode}] load, search, play ...", flush=True)
            reset(mode)
            raw[mode]["storage"].append(bench_storage(mode))
            raw[mode]["network"].append(bench_network(mode))
            raw[mode]["moves"].append(bench_moves(mode))
        if r == 0:
            results["explain"] = explain_network()
    results["raw"] = raw
    results["summary"] = {}
    for mode in MODES:
        st, mv, nw = raw[mode]["storage"], raw[mode]["moves"], raw[mode]["network"]
        results["summary"][mode] = {
            "bytes": {t: statistics.median(s["bytes"][t]["total"] for s in st)
                      for t in ("games", "game_players", "logins")},
            "seconds": {k: stats(s["seconds"][k] for s in st)
                        for k in ("games", "game_players", "logins")},
            "statements": mv[0]["statements"], "moves": mv[0]["moves"],
            "ms_per_move": stats(m["ms_per_move_median"] for m in mv),
            "network": {c: {"rows_found": nw[0][c]["rows_found"],
                            "ms": stats(n[c]["ms"] for n in nw)} for c in NETWORKS},
            "distinct": nw[0]["distinct"]["count"],
            "distinct_ms": stats(n["distinct"]["ms"] for n in nw)}

    print("UUID control ...", flush=True)
    runs = [bench_uuid_control() for _ in range(REPEATS)]
    results["uuid_control"] = {k: {"type": runs[0][k]["type"], "source": runs[0][k]["source"],
                                   "bytes": statistics.median(r[k]["bytes"] for r in runs),
                                   "seconds": stats(r[k]["seconds"] for r in runs)}
                               for k in UUID_VARIANTS}
    print("IPv4-only storage ...", flush=True)
    results["ipv4_only"] = bench_ipv4_only()
    results["ip_correctness"] = bench_ip_correctness()
    print("schema changes under live writes ...", flush=True)
    results["migration"] = bench_migrations()
    results["schema_scripts"] = schema_script_facts()
    results["code_lines"] = {m: code_lines(ROOT / "app" / f"repo_{m}.py") for m in MODES}
    results["code_lines"]["shared"] = code_lines(ROOT / "app" / "repo_common.py")

    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))
    (out_dir / "results.md").write_text(to_markdown(results))
    for mode in MODES:                 # leave clean, playable databases behind
        reset(mode)
    print((out_dir / "results.md").read_text())


# ---------- report ---------------------------------------------------------------------------
def mb(n):
    return f"{n / 2**20:.1f} MB"


def pct(new, old):
    return f"{(new - old) / old * 100:+.0f}%" if old else "n/a"


def ms(s, scale=1.0, digits=1):
    return f"{s['median'] * scale:.{digits}f} ± {s['stdev'] * scale:.{digits}f}"


def worst(s, digits=1):
    """Median, and the slowest run: better than ± for rare long waits."""
    return f"{s['median']:.{digits}f} (worst {max(s['runs']):.{digits}f})"


def to_markdown(r):
    m, b = r["summary"]["modern"], r["summary"]["baseline"]
    L = [f"MariaDB {r['mariadb_version']} · Python {r['python']} · {r['machine']} · "
         f"{r['cpu_count']} CPUs. Every time is the **median ± standard deviation of "
         f"{r['repeats']} runs**; sizes are the median.",
         f"Data: {r['sizes']['games']:,} games (2 seats each), {r['sizes']['logins']:,} logins, "
         f"{r['sizes']['games_played']} games played move by move, "
         f"{r['sizes']['migration_rows']:,} rows for the schema-change test.", ""]

    L += ["### 1. Storage (InnoDB data + indexes)", "",
          "| Table | Modern | Baseline | Modern vs baseline |", "|---|---|---|---|"]
    for t in ("games", "game_players", "logins"):
        L.append(f"| `{t}` | {mb(m['bytes'][t])} | {mb(b['bytes'][t])} | "
                 f"{pct(m['bytes'][t], b['bytes'][t])} |")
    L += ["", "### 2. Insert time (seconds)", "", "| Step | Modern | Baseline |", "|---|---|---|"]
    for k in ("games", "game_players", "logins"):
        L.append(f"| {k} | {ms(m['seconds'][k], digits=2)} | {ms(b['seconds'][k], digits=2)} |")

    u = r["uuid_control"]
    base = u["id_char36_python"]["bytes"]
    L += ["", "### 3. UUID, controlled: same 2 columns, only the id changes", "",
          "| id column | Value made by | Size | vs `CHAR(36)` | Insert time (s) |",
          "|---|---|---|---|---|"]
    for v in u.values():
        L.append(f"| `{v['type']}` | {v['source']} | {mb(v['bytes'])} | {pct(v['bytes'], base)} "
                 f"| {ms(v['seconds'], digits=2)} |")

    L += ["", "### 4. Statements sent to the server", "",
          "| Action | Modern | Baseline |", "|---|---|---|"]
    for k, label in (("move", "One move (full transaction)"), ("create_game", "Create a game"),
                     ("leave_game", "Leave a game")):
        L.append(f"| {label} | {m['statements'][k]} | {b['statements'][k]} |")
    L.append(f"| Time per move (ms, {m['moves']:,} moves) | {ms(m['ms_per_move'], digits=3)} | "
             f"{ms(b['ms_per_move'], digits=3)} |")

    e = r["explain"]
    L += ["", f"### 5. Network search and distinct addresses ({r['sizes']['logins']:,} logins)", "",
          "| | Modern | Baseline |", "|---|---|---|"]
    for c in NETWORKS:
        mn, bn = m["network"][c], b["network"][c]
        L += [f"| Logins in `{c}`: rows found | {mn['rows_found']:,} | {bn['rows_found']:,} |",
              f"| Logins in `{c}`: time (ms) | {ms(mn['ms'])} | {ms(bn['ms'])} |",
              f"| Logins in `{c}`: `EXPLAIN` type, key, est. rows | `{e[c]['modern']['type']}`, "
              f"`{e[c]['modern']['key']}`, {e[c]['modern']['rows']:,} | `{e[c]['baseline']['type']}`, "
              f"`{e[c]['baseline']['key']}`, {e[c]['baseline']['rows']:,} (then Python) |"]
    L += [f"| Distinct addresses | {m['distinct']:,} | {b['distinct']:,} |",
          f"| Time to count them (ms) | {ms(m['distinct_ms'])} | {ms(b['distinct_ms'])} |"]

    ip = r["ip_correctness"]
    t, mo, bo = ip["true"], ip["modern"], ip["baseline"]
    L += ["", "### 6. Correctness on 8 sample values", "",
          "Values: `" + "`, `".join(ip["sample"]) + "`", "",
          "| Check | Correct | Modern (`INET6`) | Baseline (text, plain SQL) |", "|---|---|---|---|",
          f"| Refuses `not-an-ip` | yes | {'yes' if mo['refuses_garbage'] else 'no'} | no |",
          f"| `COUNT(DISTINCT ip)` | {t['distinct']} | {mo['distinct']} | {bo['distinct']} |",
          f"| Rows in 10.0.0.0/8 by `BETWEEN` | {t['in_10_0_0_0_8']} | {mo['in_10_0_0_0_8']} | "
          f"{bo['in_10_0_0_0_8']} |",
          f"| IPv4 `ORDER BY ip` | {', '.join(t['ipv4_sorted'])} | {', '.join(mo['ipv4_sorted'])} | "
          f"{', '.join(bo['ipv4_sorted'])} |"]

    v4 = r["ipv4_only"]
    L += ["", f"### 7. IPv4-only addresses ({r['sizes']['logins']:,} rows, column + its index)", "",
          "| Column | Size | vs `VARCHAR(15)` |", "|---|---|---|"]
    for v in v4.values():
        L.append(f"| `{v['type']}` | {mb(v['bytes'])} | "
                 f"{pct(v['bytes'], v4['ip4_varchar']['bytes'])} |")

    mg = r["migration"]
    L += ["", f"### 8. Schema change on {mg['rows']:,} rows while the game keeps writing", "",
          f"Median of {r['repeats']} runs, with the slowest run in brackets.", "",
          "| Change | `ALGORITHM` | Time (s) | Longest wait of a live write (ms) | "
          "Writes during the change |", "|---|---|---|---|---|"]
    for step, label in (("add", "`ADD COLUMN user_agent`"), ("drop", "`DROP COLUMN note`")):
        for algo, s in mg["algorithms"].items():
            L.append(f"| {label} | {algo} | {worst(s[step]['seconds'], digits=3)} | "
                     f"{worst(s[step]['max_write_wait_ms'])} | "
                     f"{s[step]['writes_during']['median']:.0f} |")
    L += ["", "| `ALGORITHM` | Data size before | After `DROP COLUMN note` |", "|---|---|---|"]
    for algo, s in mg["algorithms"].items():
        L.append(f"| {algo} | {s['data_mb_before']:.1f} MB | {s['data_mb_after_drop']:.1f} MB |")
    L += ["", f"A change that cannot be instant (`MODIFY ip VARCHAR(45) ..., ALGORITHM=INSTANT`): "
              f"`{mg['impossible_instant_change']}`"]

    sc = r["schema_scripts"]
    L += ["", "### 9. Schema scripts", "", "| | Modern | Baseline |", "|---|---|---|",
          f"| `CREATE OR REPLACE TABLE` statements | {sc['modern']['create_or_replace']} | "
          f"{sc['baseline']['create_or_replace']} |",
          f"| `DROP TABLE IF EXISTS` lists to keep in sync | {sc['modern']['drop_if_exists_lists']} "
          f"| {sc['baseline']['drop_if_exists_lists']} |",
          f"| Re-run time (s) | {sc['modern']['rerun_seconds']:.2f} | "
          f"{sc['baseline']['rerun_seconds']:.2f} |"]

    c = r["code_lines"]
    L += ["", "### 10. Code", "", "| | Modern | Baseline |", "|---|---|---|",
          f"| Lines in the version-specific file (`app/repo_*.py`) | {c['modern']} | {c['baseline']} |",
          f"| Shared lines (`app/repo_common.py`) | {c['shared']} | {c['shared']} |"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--report-only"]:      # rebuild results.md from results.json
        saved = json.loads((ROOT / "results" / "results.json").read_text())
        (ROOT / "results" / "results.md").write_text(to_markdown(saved))
        print((ROOT / "results" / "results.md").read_text())
    else:
        main()
