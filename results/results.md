MariaDB 10.11.14-MariaDB-0ubuntu0.24.04.1 · Python 3.13.18 · Linux-6.18.44-fc-v726-x86_64-with-glibc2.39 · 2 CPUs. Every time is the **median ± standard deviation of 5 runs**; sizes are the median.
Data: 100,000 games (2 seats each), 200,000 logins, 300 games played move by move, 300,000 rows for the schema-change test.

### 1. Storage (InnoDB data + indexes)

| Table | Modern | Baseline | Modern vs baseline |
|---|---|---|---|
| `games` | 10.5 MB | 27.6 MB | -62% |
| `game_players` | 39.6 MB | 60.8 MB | -35% |
| `logins` | 26.6 MB | 28.6 MB | -7% |

### 2. Insert time (seconds)

| Step | Modern | Baseline |
|---|---|---|
| games | 0.59 ± 0.05 | 1.49 ± 0.19 |
| game_players | 1.44 ± 0.09 | 1.82 ± 0.09 |
| logins | 2.16 ± 0.09 | 2.23 ± 0.16 |

### 3. UUID, controlled: same 2 columns, only the id changes

| id column | Value made by | Size | vs `CHAR(36)` | Insert time (s) |
|---|---|---|---|---|
| `CHAR(36) ascii` | Python uuid4() | 10.5 MB | +0% | 0.66 ± 0.05 |
| `UUID` | Python uuid4() | 6.5 MB | -38% | 0.60 ± 0.03 |
| `UUID` | server UUID() | 4.5 MB | -57% | 0.31 ± 0.03 |

### 4. Statements sent to the server

| Action | Modern | Baseline |
|---|---|---|
| One move (full transaction) | 9 | 10 |
| Create a game | 4 | 4 |
| Leave a game | 5 | 6 |
| Time per move (ms, 5,687 moves) | 1.689 ± 0.055 | 1.796 ± 0.095 |

### 5. Network search and distinct addresses (200,000 logins)

| | Modern | Baseline |
|---|---|---|
| Logins in `10.0.0.0/8`: rows found | 80,221 | 80,221 |
| Logins in `10.0.0.0/8`: time (ms) | 187.4 ± 17.9 | 1181.1 ± 126.4 |
| Logins in `10.0.0.0/8`: `EXPLAIN` type, key, est. rows | `ALL`, `None`, 200,000 | `ALL`, `None`, 200,000 (then Python) |
| Logins in `10.1.0.0/16`: rows found | 342 | 342 |
| Logins in `10.1.0.0/16`: time (ms) | 2.3 ± 0.6 | 843.5 ± 89.3 |
| Logins in `10.1.0.0/16`: `EXPLAIN` type, key, est. rows | `range`, `idx_login_ip`, 342 | `ALL`, `None`, 200,000 (then Python) |
| Distinct addresses | 189,768 | 189,768 |
| Time to count them (ms) | 24.6 ± 2.1 | 794.7 ± 21.6 |

### 6. Correctness on 8 sample values

Values: `10.0.0.9`, `10.0.0.10`, `10.9.0.1`, `10.255.0.1`, `192.168.1.5`, `2001:db8::1`, `2001:0db8:0000:0000:0000:0000:0000:0001`, `not-an-ip`

| Check | Correct | Modern (`INET6`) | Baseline (text, plain SQL) |
|---|---|---|---|
| Refuses `not-an-ip` | yes | yes | no |
| `COUNT(DISTINCT ip)` | 6 | 6 | 8 |
| Rows in 10.0.0.0/8 by `BETWEEN` | 4 | 4 | 3 |
| IPv4 `ORDER BY ip` | 10.0.0.9, 10.0.0.10, 10.9.0.1, 10.255.0.1, 192.168.1.5 | 10.0.0.9, 10.0.0.10, 10.9.0.1, 10.255.0.1, 192.168.1.5 | 10.0.0.10, 10.0.0.9, 10.255.0.1, 10.9.0.1, 192.168.1.5 |

### 7. IPv4-only addresses (200,000 rows, column + its index)

| Column | Size | vs `VARCHAR(15)` |
|---|---|---|
| `VARCHAR(15) ascii` | 18.0 MB | +0% |
| `INET6 (IPv4-mapped)` | 18.0 MB | +0% |
| `INET4` | 11.0 MB | -39% |

### 8. Schema change on 300,000 rows while the game keeps writing

Median of 5 runs, with the slowest run in brackets.

| Change | `ALGORITHM` | Time (s) | Longest wait of a live write (ms) | Writes during the change |
|---|---|---|---|---|
| `ADD COLUMN user_agent` | INSTANT | 0.006 (worst 0.077) | 3.5 (worst 72.0) | 9 |
| `ADD COLUMN user_agent` | INPLACE | 0.005 (worst 0.129) | 3.4 (worst 98.1) | 6 |
| `ADD COLUMN user_agent` | INPLACE+FORCE | 0.340 (worst 0.404) | 48.3 (worst 65.2) | 240 |
| `ADD COLUMN user_agent` | COPY | 0.913 (worst 0.976) | 913.4 (worst 973.8) | 4 |
| `DROP COLUMN note` | INSTANT | 0.005 (worst 0.007) | 3.0 (worst 4.8) | 7 |
| `DROP COLUMN note` | INPLACE | 0.005 (worst 0.007) | 3.3 (worst 4.4) | 6 |
| `DROP COLUMN note` | INPLACE+FORCE | 0.206 (worst 0.233) | 53.4 (worst 55.6) | 321 |
| `DROP COLUMN note` | COPY | 0.404 (worst 0.521) | 404.1 (worst 520.6) | 5 |

| `ALGORITHM` | Data size before | After `DROP COLUMN note` |
|---|---|---|
| INSTANT | 46.6 MB | 46.6 MB |
| INPLACE | 46.6 MB | 46.6 MB |
| INPLACE+FORCE | 46.6 MB | 17.5 MB |
| COPY | 46.6 MB | 17.5 MB |

A change that cannot be instant (`MODIFY ip VARCHAR(45) ..., ALGORITHM=INSTANT`): `1846 (0A000): ALGORITHM=INSTANT is not supported. Reason: Cannot change column type. Try ALGORITHM=COPY`

### 9. Schema scripts

| | Modern | Baseline |
|---|---|---|
| `CREATE OR REPLACE TABLE` statements | 7 | 0 |
| `DROP TABLE IF EXISTS` lists to keep in sync | 0 | 1 |
| Re-run time (s) | 0.08 | 0.12 |

### 10. Code

| | Modern | Baseline |
|---|---|---|
| Lines in the version-specific file (`app/repo_*.py`) | 49 | 63 |
| Shared lines (`app/repo_common.py`) | 119 | 119 |
