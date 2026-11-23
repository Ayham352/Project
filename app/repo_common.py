"""Queries that are identical in both versions.

The modern and baseline repositories inherit from this class and only
implement the parts where the newer MariaDB features make a difference.
That keeps the comparison honest: everything in this file is shared.
"""
from contextlib import contextmanager


class CommonRepo:
    def __init__(self, conn):
        self.conn = conn

    # ---------- helpers -------------------------------------------------
    def _all(self, sql, params=()):
        cur = self.conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def _one(self, sql, params=()):
        rows = self._all(sql, params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self):
        """Run several statements as one unit: all succeed, or none do."""
        self.conn.start_transaction()
        cur = self.conn.cursor(dictionary=True)
        try:
            yield cur
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    # ---------- players ---------------------------------------------------
    def create_player(self, username, password_hash):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO players (username, password_hash) VALUES (%s, %s)",
                    (username, password_hash))
        player_id = cur.lastrowid
        cur.close()
        return player_id

    def player_by_username(self, username):
        return self._one("SELECT player_id, username, password_hash FROM players "
                         "WHERE username = %s", (username,))

    # ---------- boards ----------------------------------------------------
    def boards(self):
        return self._all("SELECT board_id, name, size FROM boards ORDER BY board_id")

    def jumps(self, board_id):
        return self._all("SELECT jump_id, jump_type, start_square, end_square "
                         "FROM board_jumps WHERE board_id = %s ORDER BY start_square",
                         (board_id,))

    # ---------- games -----------------------------------------------------
    def game(self, game_id):
        return self._one(
            "SELECT g.game_id, g.board_id, b.name AS board_name, b.size, g.status, "
            "       g.current_turn, g.winner_id, w.username AS winner, g.created_at "
            "FROM games g JOIN boards b ON b.board_id = g.board_id "
            "LEFT JOIN players w ON w.player_id = g.winner_id "
            "WHERE g.game_id = %s", (game_id,))

    def game_players(self, game_id):
        return self._all(
            "SELECT gp.player_id, p.username, gp.turn_order, gp.position "
            "FROM game_players gp JOIN players p ON p.player_id = gp.player_id "
            "WHERE gp.game_id = %s ORDER BY gp.turn_order", (game_id,))

    def join_game(self, game_id, player_id):
        """Add a player with the next free turn number (max 4 players)."""
        with self.transaction() as cur:
            cur.execute("SELECT status FROM games WHERE game_id = %s FOR UPDATE", (game_id,))
            game = cur.fetchone()
            if game is None:
                raise ValueError("No game with that code.")
            if game["status"] != "waiting":
                raise ValueError("This game has already started.")
            cur.execute("SELECT player_id, turn_order FROM game_players WHERE game_id = %s",
                        (game_id,))
            seats = cur.fetchall()
            if any(s["player_id"] == player_id for s in seats):
                return
            if len(seats) >= 4:
                raise ValueError("This game is full (4 players).")
            cur.execute("INSERT INTO game_players (game_id, player_id, turn_order) "
                        "VALUES (%s, %s, %s)", (game_id, player_id, len(seats) + 1))

    def start_game(self, game_id):
        with self.transaction() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM game_players WHERE game_id = %s", (game_id,))
            if cur.fetchone()["n"] < 2:
                raise ValueError("You need at least 2 players to start.")
            cur.execute("UPDATE games SET status = 'active', current_turn = 1 "
                        "WHERE game_id = %s AND status = 'waiting'", (game_id,))

    def moves(self, game_id):
        return self._all(
            "SELECT m.move_number, p.username, m.dice_roll, m.from_square, m.to_square, "
            "       j.jump_type, m.played_at "
            "FROM moves m JOIN players p ON p.player_id = m.player_id "
            "LEFT JOIN board_jumps j ON j.jump_id = m.jump_id "
            "WHERE m.game_id = %s ORDER BY m.move_number DESC", (game_id,))

    def open_games(self):
        return self._all(
            "SELECT g.game_id, b.name AS board_name, COUNT(gp.player_id) AS players "
            "FROM games g JOIN boards b ON b.board_id = g.board_id "
            "LEFT JOIN game_players gp ON gp.game_id = g.game_id "
            "WHERE g.status = 'waiting' GROUP BY g.game_id, b.name "
            "HAVING players < 4 ORDER BY g.created_at DESC")

    def my_games(self, player_id):
        return self._all(
            "SELECT g.game_id, b.name AS board_name, g.status, g.created_at "
            "FROM games g JOIN boards b ON b.board_id = g.board_id "
            "JOIN game_players gp ON gp.game_id = g.game_id "
            "WHERE gp.player_id = %s ORDER BY g.created_at DESC LIMIT 20", (player_id,))

    def leaderboard(self):
        return self._all(
            "SELECT p.username, COUNT(g.game_id) AS played, "
            "       COALESCE(SUM(g.winner_id = p.player_id), 0) AS won "
            "FROM players p "
            "LEFT JOIN (game_players gp JOIN games g "
            "           ON g.game_id = gp.game_id AND g.status = 'finished') "
            "       ON gp.player_id = p.player_id "
            "GROUP BY p.player_id, p.username "
            "ORDER BY won DESC, played DESC, p.username LIMIT 20")

    # ---------- implemented differently in each version -------------------
    def create_game(self, board_id, creator_id):
        raise NotImplementedError

    def leave_game(self, game_id, player_id):
        raise NotImplementedError

    def insert_move(self, cur, game_id, player_id, move_number, roll, from_sq, to_sq, jump_id):
        raise NotImplementedError

    def log_login(self, player_id, ip):
        raise NotImplementedError

    def logins_in_network(self, cidr):
        raise NotImplementedError

    def count_distinct_ips(self):
        raise NotImplementedError
