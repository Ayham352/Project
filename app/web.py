"""Flask web app. Runs on either database: set DB_MODE=modern or DB_MODE=baseline."""
import os
from functools import wraps

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import get_repo
from app.game import play_turn

MODE = os.environ.get("DB_MODE", "modern")
app = Flask(__name__)
# No secret in the code: without SECRET_KEY a random one is made (logins reset on restart).
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)


@app.before_request
def open_repo():
    g.repo = get_repo(MODE)


@app.teardown_request
def close_repo(_exc):
    repo = g.pop("repo", None)
    if repo is not None:
        repo.conn.close()


@app.context_processor
def inject_globals():
    return {"mode": MODE, "me": session.get("username")}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "player_id" not in session:
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


def client_ip():
    # Behind Apache as a proxy, the real address is in X-Forwarded-For.
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or request.remote_addr


# ---------- accounts ------------------------------------------------------
@app.route("/")
def index():
    if "player_id" in session:
        return redirect(url_for("lobby"))
    return render_template("index.html")


@app.post("/register")
def register():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not (3 <= len(username) <= 30) or len(password) < 6:
        flash("Username needs 3-30 characters and password at least 6.")
        return redirect(url_for("index"))
    if g.repo.player_by_username(username):
        flash("That username is taken.")
        return redirect(url_for("index"))
    player_id = g.repo.create_player(username, generate_password_hash(password))
    g.repo.log_login(player_id, client_ip())
    session.update(player_id=player_id, username=username)
    return redirect(url_for("lobby"))


@app.post("/login")
def login():
    player = g.repo.player_by_username(request.form.get("username", "").strip())
    if not player or not check_password_hash(player["password_hash"],
                                             request.form.get("password", "")):
        flash("Wrong username or password.")
        return redirect(url_for("index"))
    g.repo.log_login(player["player_id"], client_ip())
    session.update(player_id=player["player_id"], username=player["username"])
    return redirect(url_for("lobby"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------- lobby and games -----------------------------------------------
@app.route("/lobby")
@login_required
def lobby():
    return render_template("lobby.html", boards=g.repo.boards(),
                           open_games=g.repo.open_games(),
                           my_games=g.repo.my_games(session["player_id"]))


@app.post("/games")
@login_required
def create_game():
    game_id = g.repo.create_game(int(request.form["board_id"]), session["player_id"])
    return redirect(url_for("show_game", game_id=game_id))


@app.post("/join")
@login_required
def join_by_code():
    return join_game(request.form.get("code", "").strip())


@app.post("/games/<game_id>/join")
@login_required
def join_game(game_id):
    try:
        g.repo.join_game(game_id, session["player_id"])
    except ValueError as err:
        flash(str(err))
        return redirect(url_for("lobby"))
    return redirect(url_for("show_game", game_id=game_id))


@app.post("/games/<game_id>/start")
@login_required
def start_game(game_id):
    try:
        g.repo.start_game(game_id)
    except ValueError as err:
        flash(str(err))
    return redirect(url_for("show_game", game_id=game_id))


@app.post("/games/<game_id>/leave")
@login_required
def leave_game(game_id):
    g.repo.leave_game(game_id, session["player_id"])
    return redirect(url_for("lobby"))


@app.post("/games/<game_id>/roll")
@login_required
def roll(game_id):
    try:
        result = play_turn(g.repo, game_id, session["player_id"])
        text = f"You rolled {result['roll']}: square {result['from']} to {result['to']}"
        if result["jump"] == "ladder":
            text += " (ladder!)"
        elif result["jump"] == "snake":
            text += " (snake!)"
        flash(text + (". You won!" if result["won"] else "."))
    except ValueError as err:
        flash(str(err))
    return redirect(url_for("show_game", game_id=game_id))


@app.route("/games/<game_id>")
@login_required
def show_game(game_id):
    game = g.repo.game(game_id)
    if game is None:
        abort(404)
    players = g.repo.game_players(game_id)
    jumps = {j["start_square"]: j for j in g.repo.jumps(game["board_id"])}
    cols = 10 if game["size"] >= 50 else 6
    rows = []                                    # board drawn top row first, snaking
    for r in range(game["size"] // cols - 1, -1, -1):
        squares = list(range(r * cols + 1, r * cols + cols + 1))
        rows.append(squares if r % 2 == 0 else squares[::-1])
    on_square = {}
    for p in players:
        on_square.setdefault(p["position"], []).append(p)
    current = next((p for p in players if p["turn_order"] == game["current_turn"]), None)
    return render_template("game.html", game=game, players=players, rows=rows,
                           jumps=jumps, on_square=on_square, current=current,
                           moves=g.repo.moves(game_id),
                           seated=any(p["player_id"] == session["player_id"] for p in players))


# ---------- statistics ----------------------------------------------------
@app.route("/leaderboard")
def leaderboard():
    return render_template("leaderboard.html", rows=g.repo.leaderboard())


@app.route("/logins")
@login_required
def logins():
    cidr = request.args.get("network", "").strip()
    found, error = None, None
    if cidr:
        try:
            found = g.repo.logins_in_network(cidr)
        except ValueError:
            error = "Not a valid network. Try 127.0.0.0/8 or 2001:db8::/32."
    return render_template("logins.html", cidr=cidr, found=found, error=error,
                           distinct=g.repo.count_distinct_ips())


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG") == "1")
