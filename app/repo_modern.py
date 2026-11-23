"""MODERN version: uses UUID, INET6 and RETURNING."""
import ipaddress
from app.repo_common import CommonRepo


def to_inet6(ip):
    """INET6 accepts IPv6 text; IPv4 is stored in IPv4-mapped form (::ffff:a.b.c.d)."""
    addr = ipaddress.ip_address(ip)
    return f"::ffff:{addr}" if addr.version == 4 else str(addr)


class ModernRepo(CommonRepo):
    mode = "modern"

    def create_game(self, board_id, creator_id):
        with self.transaction() as cur:
            # The server generates the UUID and RETURNING hands it back.
            cur.execute("INSERT INTO games (board_id) VALUES (%s) RETURNING game_id",
                        (board_id,))
            game_id = cur.fetchone()["game_id"]
            cur.execute("INSERT INTO game_players (game_id, player_id, turn_order) "
                        "VALUES (%s, %s, 1)", (game_id, creator_id))
        return game_id

    def leave_game(self, game_id, player_id):
        with self.transaction() as cur:
            # DELETE ... RETURNING: remove the seat and learn which turn it had.
            cur.execute("DELETE FROM game_players WHERE game_id = %s AND player_id = %s "
                        "AND game_id IN (SELECT game_id FROM games WHERE status = 'waiting') "
                        "RETURNING turn_order", (game_id, player_id))
            row = cur.fetchone()
            if row is None:
                return
            cur.execute("UPDATE game_players SET turn_order = turn_order - 1 "
                        "WHERE game_id = %s AND turn_order > %s ORDER BY turn_order",
                        (game_id, row["turn_order"]))
            cur.execute("DELETE FROM games WHERE game_id = %s AND NOT EXISTS "
                        "(SELECT 1 FROM game_players WHERE game_id = %s)", (game_id, game_id))

    def insert_move(self, cur, game_id, player_id, move_number, roll, from_sq, to_sq, jump_id):
        # One statement: insert the move and get its id and server timestamp back.
        cur.execute("INSERT INTO moves (game_id, player_id, move_number, dice_roll, "
                    "from_square, to_square, jump_id) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "RETURNING move_id, played_at",
                    (game_id, player_id, move_number, roll, from_sq, to_sq, jump_id))
        return cur.fetchone()

    def log_login(self, player_id, ip):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO logins (player_id, ip) VALUES (%s, %s)",
                    (player_id, to_inet6(ip)))
        cur.close()

    def logins_in_network(self, cidr):
        # INET6 compares numerically, so a network is a simple indexed range.
        net = ipaddress.ip_network(cidr, strict=False)
        lo, hi = to_inet6(str(net.network_address)), to_inet6(str(net.broadcast_address))
        return self._all("SELECT login_id, player_id, ip FROM logins "
                         "WHERE ip BETWEEN %s AND %s ORDER BY ip", (lo, hi))

    def count_distinct_ips(self):
        return self._one("SELECT COUNT(DISTINCT ip) AS n FROM logins")["n"]
