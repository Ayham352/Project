"""Game rules. Shared by both versions: only repo.insert_move() differs."""
import random


def play_turn(repo, game_id, player_id, roll=None):
    """Roll the dice for player_id and apply the move in ONE transaction.

    Steps: lock the game row, check it is this player's turn, move, follow a
    snake or ladder, log the move, update the position, then either finish
    the game or pass the turn on. Any error rolls everything back.
    Returns a dict describing what happened.
    """
    roll = roll or random.randint(1, 6)
    with repo.transaction() as cur:
        # FOR UPDATE locks the game so two clicks cannot play the same turn.
        cur.execute("SELECT g.board_id, b.size, g.status, g.current_turn "
                    "FROM games g JOIN boards b ON b.board_id = g.board_id "
                    "WHERE g.game_id = %s FOR UPDATE", (game_id,))
        game = cur.fetchone()
        if game is None or game["status"] != "active":
            raise ValueError("This game is not in progress.")

        cur.execute("SELECT player_id, turn_order, position FROM game_players "
                    "WHERE game_id = %s ORDER BY turn_order", (game_id,))
        seats = cur.fetchall()
        me = next((s for s in seats if s["turn_order"] == game["current_turn"]), None)
        if me is None or me["player_id"] != player_id:
            raise ValueError("It is not your turn.")

        from_sq = me["position"]
        to_sq = from_sq + roll
        if to_sq > game["size"]:
            to_sq = from_sq                     # must land exactly on the last square

        cur.execute("SELECT jump_id, jump_type, end_square FROM board_jumps "
                    "WHERE board_id = %s AND start_square = %s", (game["board_id"], to_sq))
        jump = cur.fetchone()
        if jump:
            to_sq = jump["end_square"]

        cur.execute("SELECT COUNT(*) + 1 AS n FROM moves WHERE game_id = %s", (game_id,))
        move_number = cur.fetchone()["n"]

        move = repo.insert_move(cur, game_id, player_id, move_number, roll, from_sq, to_sq,
                                jump["jump_id"] if jump else None)

        cur.execute("UPDATE game_players SET position = %s WHERE game_id = %s AND player_id = %s",
                    (to_sq, game_id, player_id))

        won = to_sq == game["size"]
        if won:
            cur.execute("UPDATE games SET status = 'finished', winner_id = %s, "
                        "finished_at = NOW() WHERE game_id = %s", (player_id, game_id))
        else:
            next_turn = game["current_turn"] % len(seats) + 1
            cur.execute("UPDATE games SET current_turn = %s WHERE game_id = %s",
                        (next_turn, game_id))

    return {"roll": roll, "from": from_sq, "to": to_sq, "won": won,
            "jump": jump["jump_type"] if jump else None,
            "move_id": move["move_id"], "played_at": move["played_at"]}
