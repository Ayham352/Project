"""BASELINE version: the same jobs without UUID, INET6 or RETURNING."""
import ipaddress
import uuid
from app.repo_common import CommonRepo


def _parse(text):
    """Turn stored text into an address object (None if the text is not an address)."""
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None                            # invalid text that got stored
    return (addr.ipv4_mapped or addr) if addr.version == 6 else addr


class BaselineRepo(CommonRepo):
    mode = "baseline"
    # Shown on the game page ("How this version saved your move").
    MOVE_SQL = ["INSERT INTO moves (game_id, player_id, move_number, dice_roll, from_square, "
                "to_square, jump_id) VALUES (...)",
                "SELECT move_id, played_at FROM moves WHERE move_id = ?"]
    ID_TYPE = "CHAR(36) (36 bytes, made in Python with uuid.uuid4())"

    def create_game(self, board_id, creator_id):
        # The application has to generate the id itself.
        game_id = str(uuid.uuid4())
        with self.transaction() as cur:
            cur.execute("INSERT INTO games (game_id, board_id) VALUES (%s, %s)",
                        (game_id, board_id))
            cur.execute("INSERT INTO game_players (game_id, player_id, turn_order) "
                        "VALUES (%s, %s, 1)", (game_id, creator_id))
        return game_id

    def leave_game(self, game_id, player_id):
        with self.transaction() as cur:
            # Without RETURNING: read the row first, then delete it.
            cur.execute("SELECT gp.turn_order FROM game_players gp "
                        "JOIN games g ON g.game_id = gp.game_id "
                        "WHERE gp.game_id = %s AND gp.player_id = %s AND g.status = 'waiting' "
                        "FOR UPDATE", (game_id, player_id))
            row = cur.fetchone()
            if row is None:
                return
            cur.execute("DELETE FROM game_players WHERE game_id = %s AND player_id = %s",
                        (game_id, player_id))
            cur.execute("UPDATE game_players SET turn_order = turn_order - 1 "
                        "WHERE game_id = %s AND turn_order > %s ORDER BY turn_order",
                        (game_id, row["turn_order"]))
            cur.execute("DELETE FROM games WHERE game_id = %s AND NOT EXISTS "
                        "(SELECT 1 FROM game_players WHERE game_id = %s)", (game_id, game_id))

    def insert_move(self, cur, game_id, player_id, move_number, roll, from_sq, to_sq, jump_id):
        # Two statements: insert, then read back the server-generated values.
        cur.execute("INSERT INTO moves (game_id, player_id, move_number, dice_roll, "
                    "from_square, to_square, jump_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (game_id, player_id, move_number, roll, from_sq, to_sq, jump_id))
        move_id = cur.lastrowid
        cur.execute("SELECT move_id, played_at FROM moves WHERE move_id = %s", (move_id,))
        return cur.fetchone()

    def log_login(self, player_id, ip):
        # Stored as plain text; the database cannot check it is an address.
        cur = self.conn.cursor()
        cur.execute("INSERT INTO logins (player_id, ip) VALUES (%s, %s)", (player_id, ip))
        cur.close()

    def logins_in_network(self, cidr):
        # Text does not compare like an address ('10.9.0.1' > '10.255.0.1'),
        # so to get a correct answer every row is fetched and filtered in Python.
        net = ipaddress.ip_network(cidr, strict=False)
        result = []
        for row in self._all("SELECT login_id, player_id, ip FROM logins"):
            addr = _parse(row["ip"])
            if addr is not None and addr.version == net.version and addr in net:
                result.append((addr, row))
        result.sort(key=lambda pair: pair[0])
        return [row for _, row in result]

    def count_distinct_ips(self):
        # '2001:db8::1' and '2001:0db8:0000::0001' are the same address but
        # different text, so COUNT(DISTINCT ip) would be wrong. Normalise in Python.
        seen = {_parse(row["ip"]) for row in self._all("SELECT ip FROM logins")}
        seen.discard(None)
        return len(seen)
