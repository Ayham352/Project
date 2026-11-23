# Snakes & Ladders Platform

A database-backed web application for playing Snakes & Ladders online.
Semester project for the **Databases** course (Constructor University, Prof. Peter Baumann).

**Author:** Ayham Abu Serrieh

## About

Players register, create or join games on different boards, and take turns
rolling the dice. Every move is stored in the database, which allows
leaderboards and game statistics (win rates, most-hit snakes and ladders, etc.).

## Tech stack

- **Database:** MariaDB (MySQL-compatible)
- **Backend:** Python with Flask and `mysql.connector`
- **Frontend:** HTML, CSS
- **Server:** Linux + Apache (course machine `teaching.peter-baumann.org`)

## Database design

| Table | Purpose |
|-------|---------|
| `players` | Registered user accounts (passwords stored as hashes) |
| `boards` | Board layouts (e.g. Classic 100, Quick 30) |
| `board_jumps` | Snakes and ladders on each board |
| `games` | One match on one board, with status and winner |
| `game_players` | Which players are in which game, turn order, current square |
| `moves` | Log of every dice roll and its result |

## Files

- `schema.sql`: creates all tables, constraints and sample data
- `queries.sql`: example queries (leaderboard, move history, open games, a move as a transaction)

## Setup

```bash
mysql -u <user> -p <database> < schema.sql
```

## Status

- [x] Database design and schema
- [ ] Flask app: database connection and leaderboard
- [ ] Registration and login
- [ ] Create and join games
- [ ] Gameplay (dice, moves, snakes and ladders)
- [ ] Statistics pages and final design
