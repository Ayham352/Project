"""Recreate the screenshots in docs/screenshots/ (needs Google Chrome or Chromium).

    python -m docs.make_screenshots

Plays a few games on the MODERN database (it recreates its tables first),
renders each page with the Flask test client, and photographs it with
headless Chrome.
"""
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import app.web as web
from app.db import get_repo
from app.game import play_turn
from app.schema import reset

OUT = Path(__file__).resolve().parent / "screenshots"
PAGES = {                       # name: (window height, which client, url)
    "game": 1000, "lobby": 820, "compare": 1450, "logins": 760, "leaderboard": 480,
}


def chrome():
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(name):
            return name
    raise SystemExit("Chrome or Chromium is needed for screenshots")


def build_state():
    web.MODE = "modern"
    reset("modern")
    a, b, c = (web.app.test_client() for _ in range(3))
    a.post("/register", data={"username": "ayham", "password": "secret1"},
           environ_base={"REMOTE_ADDR": "10.1.4.20"})
    b.post("/register", data={"username": "sara", "password": "secret1"},
           environ_base={"REMOTE_ADDR": "192.168.0.14"})
    c.post("/register", data={"username": "omar", "password": "secret1"},
           environ_base={"REMOTE_ADDR": "2001:db8::7"})
    repo, rng = get_repo("modern"), random.Random(7)

    finished = a.post("/games", data={"board_id": "2"}).headers["Location"].rsplit("/", 1)[1]
    b.post(f"/games/{finished}/join")
    a.post(f"/games/{finished}/start")
    seats = [p["player_id"] for p in repo.game_players(finished)]
    turn = 0
    while not play_turn(repo, finished, seats[turn % 2], roll=rng.randint(1, 6))["won"]:
        turn += 1

    game = a.post("/games", data={"board_id": "1"}).headers["Location"].rsplit("/", 1)[1]
    b.post(f"/games/{game}/join")
    c.post(f"/games/{game}/join")
    a.post(f"/games/{game}/start")
    seats = [p["player_id"] for p in repo.game_players(game)]
    for i in range(17):
        play_turn(repo, game, seats[i % 3], roll=rng.randint(1, 6))
    clients = {1: a, 2: b, 3: c}
    roller = clients[repo.game(game)["current_turn"]]
    roller.post(f"/games/{game}/roll")             # fills the "last move" panel
    c.post("/games", data={"board_id": "2"})       # an open game for the lobby
    repo.conn.close()
    return {"game": (roller, f"/games/{game}"), "lobby": (a, "/lobby"),
            "compare": (a, "/compare"), "logins": (a, "/logins?network=10.0.0.0/8"),
            "leaderboard": (a, "/leaderboard")}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pages = build_state()
    browser = chrome()
    with tempfile.TemporaryDirectory() as tmp:
        for name, height in PAGES.items():
            client, url = pages[name]
            html = client.get(url).get_data(as_text=True)
            html = re.sub(r'<meta http-equiv="refresh"[^>]*>', "", html)
            page = Path(tmp) / f"{name}.html"
            page.write_text(html)
            subprocess.run([browser, "--headless=new", "--no-sandbox", "--disable-gpu",
                            "--hide-scrollbars", f"--window-size=1200,{height}",
                            f"--screenshot={OUT / (name + '.png')}", page.as_uri()],
                           check=True, capture_output=True, timeout=60)
            print("saved", OUT / f"{name}.png")
    reset("modern")                                  # leave a clean database


if __name__ == "__main__":
    main()
