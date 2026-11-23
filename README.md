A project for area 1, "SQL that saves you work" for the [MariaDB student database projects, 2026-09](https://mariadb.org/bachelor_hackathon_2026-09/).

# Snakes & Ladders: what UUID, INET6 and RETURNING save

**Team 15:** Ayham Abu Serrieh, Constructor University (Databases, bachelor's).
**Developed against:** MariaDB 10.11.14 on Linux, Python 3.13, Flask 3.1, `mysql-connector-python` 26.10. Needs MariaDB **10.10 or later**.

An online Snakes & Ladders game (accounts, a lobby, games for 2 to 4 players, a leaderboard) built **twice on the same data model**:

- **modern** uses three newer MariaDB features: the `UUID` type, the `INET6` type, and `RETURNING`;
- **baseline** does the same jobs the usual way: `CHAR(36)` ids made in Python, IP addresses as `VARCHAR`, and a `SELECT` after each `INSERT`.

The game, the web pages and all shared queries are one code base. Only one small file differs between the versions (`app/repo_modern.py` vs `app/repo_baseline.py`), so every difference in the results comes from the three features.

## What we found

| Feature | What it saved here | Where it saved nothing |
|---|---|---|
| `UUID` | `games` table **62% smaller** (10.5 vs 27.6 MB), the table that refers to it 36% smaller, game inserts 2.5× faster. No id code in the app. | Server `UUID()` values are predictable, so they are not secret invite codes (see [limits](#limits-and-failure-modes)). |
| `INET6` | Correct answers in plain SQL: sorting, network ranges and `COUNT(DISTINCT)` are all wrong on text. Network search **4.5× faster**, counting distinct addresses **27× faster**, because the baseline must do it in Python to be correct. Garbage values are refused. | Space: only 7% smaller, because most of our addresses are IPv4, which is short as text. |
| `RETURNING` | One statement fewer per move (9 vs 10), and `DELETE ... RETURNING` replaces a `SELECT ... FOR UPDATE` + `DELETE`. | Time on one machine: 1.19 vs 1.27 ms per move. A round trip costs little on `localhost`; the saving grows with network distance (not measured). |

All numbers are from one run of `python -m bench.benchmark` on one uncontrolled machine (details [below](#results)).

## The data model

```
players ──< logins            (every login, with its IP address)
players ──< game_players >── games >── boards ──< board_jumps   (snakes and ladders)
            game_players ──< moves >── board_jumps              (which jump a move hit)
```

| Table | What it holds | Modern | Baseline |
|---|---|---|---|
| `players` | accounts, hashed passwords | same | same |
| `logins` | one row per login | `ip INET6` | `ip VARCHAR(45)` |
| `boards`, `board_jumps` | board layouts; snakes and ladders in one table, a `CHECK` makes ladders go up and snakes go down | same | same |
| `games` | one match; the id is also the join code | `game_id UUID DEFAULT UUID()` | `game_id CHAR(36)`, made in Python |
| `game_players` | who is in a game, turn order, square (many-to-many) | `UUID` foreign key | `CHAR(36)` foreign key |
| `moves` | every dice roll; the basis of all statistics | inserted with `RETURNING` | `INSERT`, then `SELECT` |

Why it is built this way:

- **Board layouts are data**, not code, so a new board is a few `INSERT`s.
- **`game_players` has a composite key** `(game_id, player_id)` and `moves` points to it, so the database itself refuses a move by a player who is not in that game.
- **A move is one transaction** (`app/game.py`): lock the game row with `SELECT ... FOR UPDATE`, check the turn, apply the jump, log the move, update the square, pass the turn. Two quick clicks cannot play the same turn twice, and a crash halfway changes nothing (there is a test for this).
- **The baseline is a fair baseline:** its `CHAR(36)` and `VARCHAR(45)` columns use the 1-byte `ascii` character set, not the 4-byte `utf8mb4`, and its correct IP queries are written properly in Python rather than left wrong.

Full schemas: [`sql/modern.sql`](sql/modern.sql) and [`sql/baseline.sql`](sql/baseline.sql). Board data: [`sql/seed.sql`](sql/seed.sql).

## Run it

You need MariaDB 10.10+ and Python 3.10+.

```bash
git clone https://github.com/Ayham352/Project.git && cd Project
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # then set DB_PASSWORD and SECRET_KEY
```

1. **Create the databases and the user** (once, as an admin). First change `change-me` in `sql/setup.sql` to your own password and put the same password in `.env`:
   ```bash
   sudo mariadb < sql/setup.sql
   ```
2. **Create the tables and boards** in both databases:
   ```bash
   python -m app.init_db
   ```
3. **Play.** Start the app on either version:
   ```bash
   DB_MODE=modern   python -m app.web        # http://127.0.0.1:5000
   DB_MODE=baseline python -m app.web        # same game, baseline database
   ```
   Open it in two browsers (or one normal and one private window), sign up twice, create a game in one, join it with the code in the other, and press **Start game**. The header shows which database version is running. The **Logins** page runs the network search and the distinct-address count.

### Just the features: paste-ready examples

Each file is self-contained, shows the job **without** and **with** the feature, and cleans up after itself. Run it in any scratch database:

```bash
mariadb test < examples/01_uuid.sql
mariadb test < examples/02_inet6.sql
mariadb test < examples/03_returning.sql
```

### Tests

27 tests check the rules, the constraints, rollback after a failed move and a full game through the web app, **against both versions**:

```bash
python -m unittest -v
```

They use their own databases (`snl_test_modern`, `snl_test_baseline`, created by `setup.sql`).

### Reproduce the measurements

```bash
python -m bench.benchmark          # about 30 seconds; recreates the tables in both databases
```

It writes [`results/results.md`](results/results.md) and `results/results.json`. Sizes can be changed with `BENCH_GAMES`, `BENCH_LOGINS` and `BENCH_PLAYED`.

## How it was measured

`bench/benchmark.py` does the same work on both databases:

1. **Storage and insert time:** 1,000 players, 100,000 games with 2 seats each, 200,000 logins (seeded random addresses: 80% IPv4 from private and public ranges, 20% IPv6 in `2001:db8::/32`). Sizes are InnoDB `data_length + index_length` after `ANALYZE TABLE`.
2. **A controlled UUID test:** three tables with the *same two columns*, where only the id changes: `CHAR(36)` with Python `uuid4()`, `UUID` with Python `uuid4()`, and `UUID` with server `UUID()`. This separates the two reasons the `games` table shrinks.
3. **Moves:** 300 full games (5,687 moves) through the real game code (`app/game.py`), timed per move. Statements per move are counted with the server's own `Questions` counter.
4. **IP correctness:** 8 sample values, queried with the SQL a developer would naturally write on each column type.
5. **Network search:** logins in `10.0.0.0/8` (80,073 rows) and a count of distinct addresses on the full table, median of 5 runs. Both versions return the same rows, so the times compare equal work.

## Results

Measured on MariaDB 10.11.14, Python 3.13, Linux x86-64, one run.

**Storage (InnoDB data + indexes)**

| Table | Modern | Baseline | Modern vs baseline |
|---|---|---|---|
| `games` | 10.5 MB | 27.6 MB | −62% |
| `game_players` | 39.6 MB | 61.8 MB | −36% |
| `logins` | 26.6 MB | 28.6 MB | −7% |

**UUID, controlled (same 2 columns, 100,000 rows; only the id changes)**

| id column | Value comes from | Size | vs `CHAR(36)` | Insert time |
|---|---|---|---|---|
| `CHAR(36) ascii` | Python `uuid4()` | 9.5 MB | – | 0.86 s |
| `UUID` | Python `uuid4()` | 6.5 MB | −32% | 0.81 s |
| `UUID` | server `UUID()` | 4.5 MB | −53% | 0.29 s |

There are two separate effects. The **type** saves about a third (16 bytes instead of 36). The **source** saves the rest: server `UUID()` values are time-based, and MariaDB stores them with the time part first, so new rows go to the end of the primary-key index. Random `uuid4()` values land all over the index, which splits pages and leaves them half full. Inserts are about 3× faster for the same reason.

**One move of the game (a full transaction)**

| | Modern | Baseline |
|---|---|---|
| Statements sent to the server per move | 9 | 10 |
| Median time per move | 1.19 ms | 1.27 ms |
| Moves measured | 5,687 | 5,687 |

**Network search and distinct addresses (200,000 logins)**

| | Modern | Baseline |
|---|---|---|
| Logins in `10.0.0.0/8` | 80,073 | 80,073 |
| Median search time | 192 ms | 876 ms |
| Distinct addresses | 189,557 | 189,557 |
| Time to count them | 23 ms | 616 ms |

**Correctness on 8 sample values** (`10.0.0.9`, `10.0.0.10`, `10.9.0.1`, `10.255.0.1`, `192.168.1.5`, `2001:db8::1`, `2001:0db8:0000:0000:0000:0000:0000:0001`, `not-an-ip`)

| Check | Correct | Modern (`INET6`) | Baseline, plain SQL on text |
|---|---|---|---|
| Database refuses `not-an-ip` | yes | yes | **no** |
| `COUNT(DISTINCT ip)` | 6 | 6 | **8** |
| Rows in 10.0.0.0/8 with `BETWEEN` | 4 | 4 | **3** |
| IPv4 `ORDER BY ip` | 10.0.0.9, 10.0.0.10, 10.9.0.1, 10.255.0.1 | same as correct | **10.0.0.10, 10.0.0.9, 10.255.0.1, 10.9.0.1** |

The baseline *application* still gives correct answers, but only by reading every row into Python and checking each address there (`app/repo_baseline.py`). That extra code is the "validation pushed into application code" the feature removes.

**Code:** the version-specific file is 46 lines (modern) against 59 (baseline); all other code is shared.

## When each feature is worth it, and when not

**`UUID`: use it** for any UUID you store, since it is the same value in less than half the space. Let the server generate it with `DEFAULT UUID()` when you want inserts in index order. **Do not** rely on `UUID()` alone for anything secret: it is version 1 (timestamp plus MAC address), so ids made close together look alike and can be guessed. In this game that is acceptable, because open games are listed in the lobby anyway. For secret links, generate random ids (Python `uuid4()` into the same `UUID` column, which still saves 32%), or use `UUID_v4()` / `UUID_v7()` on MariaDB 11.7 and later. If you never need ids that are unique across systems, plain `AUTO_INCREMENT` integers are smaller still.

**`INET6`: use it** whenever you search, sort, group or count by address. That is where text is silently wrong. **It saves little space** when most addresses are IPv4: our text addresses average 18 bytes (IPv4 alone about 12) against a fixed 16. For IPv4-only data, `INET4` (4 bytes, MariaDB 10.10+) is the better choice.

**`RETURNING`: use it** whenever you need values the server fills in (an id, a default timestamp, a generated UUID), or need to know what a `DELETE` removed. It saves one round trip each time, and it works for many rows at once, where `LAST_INSERT_ID()` only gives the first id. **It matters little** when the database runs on the same machine as the app: here it saved about 7% per move.

## Limits and failure modes

Things we ran into on MariaDB 10.11:

- **`INET6` refuses plain IPv4 text** like `'10.0.0.9'` (`Incorrect inet6 value`). The app converts IPv4 to the mapped form `::ffff:10.0.0.9` first (`to_inet6()` in `app/repo_modern.py`), and network searches must use the same form.
- **There is no `UPDATE ... RETURNING`** on 10.11. Only `INSERT`, `INSERT ... SELECT`, `REPLACE` and `DELETE` support it, so the move still needs a separate `UPDATE` for the player's square.
- **`UUID()` is predictable**, as explained above.
- **Not measured:** the effect over a real network, behaviour at millions of rows, and repeated benchmark runs with variance. All numbers are from a single run.

## How it was built

```
app/
  repo_common.py     queries identical in both versions (the large majority)
  repo_modern.py     UUID, INET6, RETURNING                   <- the comparison
  repo_baseline.py   the same jobs without them               <-
  game.py            game rules, one transaction per move (shared)
  web.py, templates/ Flask web app (shared); DB_MODE picks the version
  db.py, init_db.py  connection settings from .env, table creation
sql/                 setup.sql, modern.sql, baseline.sql, seed.sql
examples/            three paste-ready feature examples
bench/benchmark.py   all measurements
tests/test_all.py    27 tests, run against both versions
results/             benchmark output
```

All SQL uses parameters (`%s`), never string formatting with user input. Passwords are stored as salted hashes (Werkzeug), credentials come from `.env` (not committed), and debug mode is off unless `FLASK_DEBUG=1`.
