"""Tests for both versions. Run from the repository root:

    python -m unittest -v

They use the databases snl_test_modern and snl_test_baseline (created by
sql/setup.sql) and recreate their tables, so real data is never touched.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["DB_NAME_MODERN"] = os.environ.get("TEST_DB_MODERN", "snl_test_modern")
os.environ["DB_NAME_BASELINE"] = os.environ.get("TEST_DB_BASELINE", "snl_test_baseline")

from app.schema import reset                          # noqa: E402
from bench.benchmark import questions                 # noqa: E402
from app.db import get_repo                           # noqa: E402
from app.game import play_turn                        # noqa: E402
import app.web as web                                 # noqa: E402
import mysql.connector                                # noqa: E402

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


    # ----- more behaviour, both versions --------------------------------
    def test_schema_script_can_be_run_twice(self):
        reset(self.mode)
        reset(self.mode)
        self.assertEqual(len(self.repo.boards()), 2)

    def test_statements_per_move_match_what_the_page_shows(self):
        game_id = self.new_game()
        before = questions(self.repo.conn)
        play_turn(self.repo, game_id, self.a, roll=1)
        used = questions(self.repo.conn) - before - 1
        # 8 statements are shared; the rest is what MOVE_SQL lists for this version
        self.assertEqual(used, 8 + len(self.repo.MOVE_SQL))

    def test_web_errors_are_handled(self):
        web.MODE = self.mode
        c = web.app.test_client()
        r = c.post("/register", data={"username": "ab", "password": "secret1"})
        self.assertIn("/", r.headers["Location"])                    # too short: back
        c.post("/register", data={"username": "dora", "password": "secret1"})
        c.get("/logout")
        r = c.post("/register", data={"username": "dora", "password": "secret9"},
                   follow_redirects=True)
        self.assertIn("taken", r.get_data(as_text=True))
        r = c.post("/login", data={"username": "dora", "password": "wrong!"},
                   follow_redirects=True)
        self.assertIn("Wrong username or password", r.get_data(as_text=True))
        c.post("/login", data={"username": "dora", "password": "secret1"})
        r = c.post("/join", data={"code": "not-a-code"}, follow_redirects=True)
        self.assertIn("No game with that code", r.get_data(as_text=True))
        self.assertEqual(c.get("/games/not-a-code").status_code, 404)
        r = c.get("/logins?network=banana")
        self.assertIn("Not a valid network", r.get_data(as_text=True))
        self.assertEqual(c.get("/lobby").status_code, 200)

    def test_game_page_shows_how_the_move_was_saved(self):
        web.MODE = self.mode
        c1, c2 = web.app.test_client(), web.app.test_client()
        c1.post("/register", data={"username": "eve", "password": "secret1"})
        c2.post("/register", data={"username": "fay", "password": "secret1"})
        game_id = c1.post("/games", data={"board_id": "1"}).headers["Location"].rsplit("/", 1)[1]
        c2.post(f"/games/{game_id}/join")
        c1.post(f"/games/{game_id}/start")
        c1.post(f"/games/{game_id}/roll")
        page = c1.get(f"/games/{game_id}").get_data(as_text=True)
        self.assertIn("How this version saved your move", page)
        self.assertIn("Your last move: id", page)
        self.assertIn(self.repo.MOVE_SQL[0][:20], page)

    def test_compare_page(self):
        web.MODE = self.mode
        page = web.app.test_client().get("/compare").get_data(as_text=True)
        self.assertIn("Live check", page)


class ModernTests(SharedBehaviour, Base):
    mode = "modern"

    def test_inet6_column_refuses_garbage(self):
        with self.assertRaises(Exception):
            self.sql("INSERT INTO logins (player_id, ip) VALUES (%s, 'not-an-ip')", (self.a,))

    def test_server_generates_the_game_uuid(self):
        game_id = self.repo.create_game(1, self.a)
        self.assertRegex(game_id, r"^[0-9a-f]{8}-[0-9a-f]{4}-1[0-9a-f]{3}-")  # version 1


    def test_returning_gives_back_server_values_in_one_statement(self):
        game_id = self.new_game()
        cur = self.repo.conn.cursor(dictionary=True)
        before = questions(self.repo.conn)
        row = self.repo.insert_move(cur, game_id, self.a, 1, 2, 0, 2, None)
        self.assertEqual(questions(self.repo.conn) - before - 1, 1)
        self.assertIsNotNone(row["played_at"])
        cur.close()

    def test_instant_alter_refuses_what_it_cannot_do(self):
        # ALGORITHM=INSTANT is a promise: the server errors instead of copying the table.
        self.sql("ALTER TABLE logins ADD COLUMN user_agent VARCHAR(255) NULL, ALGORITHM=INSTANT")
        with self.assertRaises(Exception) as ctx:
            self.sql("ALTER TABLE logins MODIFY ip VARCHAR(45) NOT NULL, ALGORITHM=INSTANT")
        self.assertIn("INSTANT is not supported", str(ctx.exception))

    def test_inet6_and_plain_ipv4_text_depends_on_the_version(self):
        # MariaDB 10.11 refuses '10.0.0.9' in an INET6 column; 11.8 accepts it.
        # The app never relies on either: to_inet6() always sends ::ffff:a.b.c.d.
        version = self.sql("SELECT VERSION()")[0][0]
        major = int(version.split(".")[0])
        try:
            self.sql("INSERT INTO logins (player_id, ip) VALUES (%s, '10.0.0.9')", (self.a,))
            stored = self.sql("SELECT ip FROM logins")[0][0]
            print(f"\n  MariaDB {version}: INET6 accepted '10.0.0.9' and stored {stored!r}")
            self.assertGreaterEqual(major, 11, "10.x was expected to refuse plain IPv4")
            self.assertIn(stored, ("::ffff:10.0.0.9", "::10.0.0.9"))
            self.sql("DELETE FROM logins")
        except mysql.connector.Error as err:
            print(f"\n  MariaDB {version}: INET6 refused '10.0.0.9' ({err.errno})")
            self.assertLess(major, 11, "this version refused plain IPv4")
        self.repo.log_login(self.a, "10.0.0.9")     # what the app does, on every version
        self.assertEqual(self.sql("SELECT ip FROM logins")[0][0], "::ffff:10.0.0.9")


    def test_every_paste_ready_example_runs(self):
        from app.schema import run_sql_file
        examples = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*.sql"))
        self.assertEqual(len(examples), 5)
        for path in examples:
            with self.subTest(example=path.name):
                run_sql_file(self.repo.conn, path)


class BaselineTests(SharedBehaviour, Base):
    mode = "baseline"

    def test_text_column_accepts_garbage(self):
        # This is the weakness the modern version fixes: nothing stops bad data.
        self.sql("INSERT INTO logins (player_id, ip) VALUES (%s, 'not-an-ip')", (self.a,))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM logins")[0][0], 1)


class SetupTests(unittest.TestCase):
    def test_setup_fills_in_random_secrets(self):
        import app.setup as setup
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text("DB_USER=snl\nDB_PASSWORD=\nSECRET_KEY=\n")
            saved = {k: os.environ.get(k) for k in ("DB_USER", "DB_PASSWORD", "SECRET_KEY")}
            try:
                with mock.patch.object(setup, "ROOT", root), \
                        mock.patch.object(setup, "ENV_FILE", root / ".env"):
                    values = setup.ensure_env_file()
                    again = setup.ensure_env_file()          # second run keeps them
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            self.assertGreaterEqual(len(values["DB_PASSWORD"]), 24)
            self.assertGreaterEqual(len(values["SECRET_KEY"]), 24)
            self.assertEqual(values["DB_PASSWORD"], again["DB_PASSWORD"])


if __name__ == "__main__":
    unittest.main()
