"""Tests for both versions. Run from the repository root:

    python -m unittest -v

They use the databases snl_test_modern and snl_test_baseline (created by
sql/setup.sql) and recreate their tables, so real data is never touched.
"""
import os
import unittest

os.environ["DB_NAME_MODERN"] = os.environ.get("TEST_DB_MODERN", "snl_test_modern")
os.environ["DB_NAME_BASELINE"] = os.environ.get("TEST_DB_BASELINE", "snl_test_baseline")

from bench.benchmark import reset                     # noqa: E402
from app.db import get_repo                           # noqa: E402
from app.game import play_turn                        # noqa: E402
import app.web as web                                 # noqa: E402

MODES = ("modern", "baseline")


class Base(unittest.TestCase):
    def setUp(self):
        reset(self.mode)
        self.repo = get_repo(self.mode)
        self.a = self.repo.create_player("alice", "x")
        self.b = self.repo.create_player("bob", "x")

    def tearDown(self):
        self.repo.conn.close()

    def new_game(self, board=2, start=True):
        game_id = self.repo.create_game(board, self.a)
        self.repo.join_game(game_id, self.b)
        if start:
            self.repo.start_game(game_id)
        return game_id

    def sql(self, statement, params=()):
        cur = self.repo.conn.cursor()
        cur.execute(statement, params)
        rows = cur.fetchall() if cur.with_rows else None
        cur.close()
        return rows


class SharedBehaviour:
    """Every test here runs once against each version."""

    # ----- schema constraints --------------------------------------------
    def test_dice_must_be_1_to_6(self):
        game_id = self.new_game()
        with self.assertRaises(Exception):
            self.sql("INSERT INTO moves (game_id, player_id, move_number, dice_roll, "
                     "from_square, to_square) VALUES (%s, %s, 1, 7, 0, 7)", (game_id, self.a))

    def test_ladder_cannot_go_down(self):
        with self.assertRaises(Exception):
            self.sql("INSERT INTO board_jumps (board_id, jump_type, start_square, end_square) "
                     "VALUES (1, 'ladder', 50, 20)")

    def test_move_needs_a_seated_player(self):
        game_id = self.new_game()
        outsider = self.repo.create_player("carol", "x")
        with self.assertRaises(Exception):
            self.sql("INSERT INTO moves (game_id, player_id, move_number, dice_roll, "
                     "from_square, to_square) VALUES (%s, %s, 1, 2, 0, 2)", (game_id, outsider))

    # ----- lobby ---------------------------------------------------------
    def test_create_join_and_leave_renumbers_turns(self):
        game_id = self.repo.create_game(1, self.a)
        c = self.repo.create_player("carol", "x")
        self.repo.join_game(game_id, self.b)
        self.repo.join_game(game_id, c)
        self.repo.leave_game(game_id, self.b)
        seats = [(p["username"], p["turn_order"]) for p in self.repo.game_players(game_id)]
        self.assertEqual(seats, [("alice", 1), ("carol", 2)])

    def test_last_player_leaving_deletes_the_game(self):
        game_id = self.repo.create_game(1, self.a)
        self.repo.leave_game(game_id, self.a)
        self.assertIsNone(self.repo.game(game_id))

    def test_cannot_start_alone_or_join_a_full_game(self):
        game_id = self.repo.create_game(1, self.a)
        with self.assertRaises(ValueError):
            self.repo.start_game(game_id)
        for name in ("p2", "p3", "p4"):
            self.repo.join_game(game_id, self.repo.create_player(name, "x"))
        with self.assertRaises(ValueError):
            self.repo.join_game(game_id, self.repo.create_player("p5", "x"))

    # ----- game rules ----------------------------------------------------
    def test_ladder_is_followed_and_turn_passes(self):
        game_id = self.new_game()                    # Quick 30: ladder 3 -> 22
        result = play_turn(self.repo, game_id, self.a, roll=3)
        self.assertEqual((result["to"], result["jump"]), (22, "ladder"))
        self.assertEqual(self.repo.game(game_id)["current_turn"], 2)
        self.assertIsNotNone(result["played_at"])    # server value came back

    def test_not_your_turn(self):
        game_id = self.new_game()
        with self.assertRaises(ValueError):
            play_turn(self.repo, game_id, self.b, roll=1)

    def test_must_land_exactly_and_winning_finishes_the_game(self):
        game_id = self.new_game()
        self.sql("UPDATE game_players SET position = 28 WHERE game_id = %s AND player_id = %s",
                 (game_id, self.a))
        self.assertEqual(play_turn(self.repo, game_id, self.a, roll=5)["to"], 28)  # overshoot
        play_turn(self.repo, game_id, self.b, roll=1)
        self.assertTrue(play_turn(self.repo, game_id, self.a, roll=2)["won"])
        game = self.repo.game(game_id)
        self.assertEqual((game["status"], game["winner"]), ("finished", "alice"))

    def test_failed_move_rolls_back_everything(self):
        game_id = self.new_game()
        original = self.repo.insert_move

        def broken(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("simulated crash after the move was written")
        self.repo.insert_move = broken
        with self.assertRaises(RuntimeError):
            play_turn(self.repo, game_id, self.a, roll=2)
        self.repo.insert_move = original
        self.assertEqual(self.repo.moves(game_id), [])
        self.assertEqual(self.repo.game_players(game_id)[0]["position"], 0)

    # ----- login addresses ----------------------------------------------
    def test_network_search_and_distinct_count_are_correct(self):
        for ip in ("10.0.0.9", "10.0.0.10", "10.9.0.1", "10.255.0.1", "192.168.1.5",
                   "2001:db8::1", "2001:0db8:0000:0000:0000:0000:0000:0001"):
            self.repo.log_login(self.a, ip)
        found = self.repo.logins_in_network("10.0.0.0/8")
        self.assertEqual(len(found), 4)
        self.assertEqual(len(self.repo.logins_in_network("2001:db8::/32")), 2)
        self.assertEqual(self.repo.count_distinct_ips(), 6)

    # ----- the web app ---------------------------------------------------
    def test_web_app_plays_a_full_game(self):
        web.MODE = self.mode
        c1, c2 = web.app.test_client(), web.app.test_client()
        c1.post("/register", data={"username": "ayham", "password": "secret1"},
                environ_base={"REMOTE_ADDR": "10.0.0.9"})
        c2.post("/register", data={"username": "tester", "password": "secret2"},
                environ_base={"REMOTE_ADDR": "2001:db8::1"})
        game_id = c1.post("/games", data={"board_id": "2"}).headers["Location"].rsplit("/", 1)[1]
        c2.post("/join", data={"code": game_id})
        c1.post(f"/games/{game_id}/start")
        for _ in range(500):
            page = c1.get(f"/games/{game_id}").get_data(as_text=True)
            if "won!" in page:
                break
            (c1 if "Roll the dice" in page else c2).post(f"/games/{game_id}/roll")
        self.assertIn("won!", page)
        self.assertIn("ayham", c1.get("/leaderboard").get_data(as_text=True))
        self.assertIn("1 login(s)", c1.get("/logins?network=10.0.0.0/8").get_data(as_text=True))


class ModernTests(SharedBehaviour, Base):
    mode = "modern"

    def test_inet6_column_refuses_garbage(self):
        with self.assertRaises(Exception):
            self.sql("INSERT INTO logins (player_id, ip) VALUES (%s, 'not-an-ip')", (self.a,))

    def test_server_generates_the_game_uuid(self):
        game_id = self.repo.create_game(1, self.a)
        self.assertRegex(game_id, r"^[0-9a-f]{8}-[0-9a-f]{4}-1[0-9a-f]{3}-")  # version 1


class BaselineTests(SharedBehaviour, Base):
    mode = "baseline"

    def test_text_column_accepts_garbage(self):
        # This is the weakness the modern version fixes: nothing stops bad data.
        self.sql("INSERT INTO logins (player_id, ip) VALUES (%s, 'not-an-ip')", (self.a,))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM logins")[0][0], 1)


if __name__ == "__main__":
    unittest.main()
