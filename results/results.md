Measured on MariaDB 10.11.14-MariaDB-0ubuntu0.24.04.1, Python 3.13.18, Linux-6.18.44-fc-v726-x86_64-with-glibc2.39.
Data: 100,000 games (2 players each), 200,000 logins, 300 games played move by move.

### Storage (InnoDB data + indexes)

| Table | Modern | Baseline | Modern vs baseline |
|---|---|---|---|
| `games` | 10.5 MB | 27.6 MB | -62% |
| `game_players` | 39.6 MB | 61.8 MB | -36% |
| `logins` | 26.6 MB | 28.6 MB | -7% |

### UUID: controlled comparison (same 2 columns, only the id changes)

| id column | Value comes from | Size | vs CHAR(36) | Insert time |
|---|---|---|---|---|
| `CHAR(36) CHARACTER SET ascii` | Python `uuid4()` | 9.5 MB | +0% | 0.86 s |
| `UUID` | Python `uuid4()` | 6.5 MB | -32% | 0.81 s |
| `UUID` | server `UUID()` | 4.5 MB | -53% | 0.29 s |

### Insert time

| Step | Modern | Baseline |
|---|---|---|
| games | 0.6 s | 1.49 s |
| game_players | 1.24 s | 1.82 s |
| logins | 1.98 s | 2.16 s |

### One move of the game (a full transaction)

| | Modern | Baseline |
|---|---|---|
| Statements sent to the server per move | 9 | 10 |
| Median time per move | 1.185 ms | 1.27 ms |
| Moves measured | 5,687 | 5,687 |

### Search logins in `10.0.0.0/8` and count distinct addresses

| | Modern | Baseline |
|---|---|---|
| Rows found | 80,073 | 80,073 |
| Median search time | 192.4 ms | 876.4 ms |
| Distinct addresses | 189,557 | 189,557 |
| Time to count them | 22.9 ms | 616.3 ms |

### Correctness on 8 sample values (`10.0.0.9`, `10.0.0.10`, `10.9.0.1`, `10.255.0.1`, `192.168.1.5`, `2001:db8::1`, `2001:0db8:0000:0000:0000:0000:0000:0001`, `not-an-ip`)

| Check | Correct answer | Modern (`INET6`) | Baseline, plain SQL on text |
|---|---|---|---|
| Database refuses `not-an-ip` | yes | yes | no |
| `COUNT(DISTINCT ip)` | 6 | 6 | 8 |
| Rows in 10.0.0.0/8 with `BETWEEN` | 4 | 4 | 3 |
| IPv4 `ORDER BY ip` | 10.0.0.9, 10.0.0.10, 10.9.0.1, 10.255.0.1, 192.168.1.5 | 10.0.0.9, 10.0.0.10, 10.9.0.1, 10.255.0.1, 192.168.1.5 | 10.0.0.10, 10.0.0.9, 10.255.0.1, 10.9.0.1, 192.168.1.5 |

### Code

| | Modern | Baseline |
|---|---|---|
| Lines in the version-specific repository file | 46 | 59 |
| Shared code (`repo_common.py`, `game.py`, web app) | same | same |
