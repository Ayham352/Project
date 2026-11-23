-- =====================================================================
--  Example queries — Snakes & Ladders Platform
-- =====================================================================

-- Q1. Leaderboard: games played, games won, win rate per player
--     (only finished games count)
SELECT p.username,
       COUNT(g.game_id)                                    AS games_played,
       COALESCE(SUM(g.winner_id = p.player_id), 0)         AS games_won,
       COALESCE(ROUND(100 * SUM(g.winner_id = p.player_id)
                 / NULLIF(COUNT(g.game_id), 0), 1), 0)     AS win_rate_pct
FROM players p
LEFT JOIN (game_players gp
           JOIN games g ON g.game_id = gp.game_id AND g.status = 'finished')
       ON gp.player_id = p.player_id
GROUP BY p.player_id, p.username
ORDER BY games_won DESC, win_rate_pct DESC, p.username;

-- Q2. All snakes and ladders on a board, in square order
SELECT jump_type, start_square, end_square,
       CAST(end_square AS SIGNED) - CAST(start_square AS SIGNED) AS squares_moved
FROM board_jumps
WHERE board_id = 1
ORDER BY start_square;

-- Q3. Most-hit snakes and ladders across all games
SELECT b.name AS board, j.jump_type, j.start_square, j.end_square,
       COUNT(m.move_id) AS times_hit
FROM board_jumps j
JOIN boards b      ON b.board_id = j.board_id
LEFT JOIN moves m  ON m.jump_id = j.jump_id
GROUP BY j.jump_id
HAVING times_hit > 0
ORDER BY times_hit DESC;

-- Q4. Full move history of one game
SELECT m.move_number, p.username, m.dice_roll,
       m.from_square, m.to_square,
       COALESCE(j.jump_type, '-') AS hit
FROM moves m
JOIN players p          ON p.player_id = m.player_id
LEFT JOIN board_jumps j ON j.jump_id = m.jump_id
WHERE m.game_id = 1
ORDER BY m.move_number;

-- Q5. Open games a player can join (waiting, fewer than 4 players)
SELECT g.game_id, b.name AS board, COUNT(gp.player_id) AS players_joined
FROM games g
JOIN boards b             ON b.board_id = g.board_id
LEFT JOIN game_players gp ON gp.game_id = g.game_id
WHERE g.status = 'waiting'
GROUP BY g.game_id, b.name
HAVING players_joined < 4;

-- Q6. A move as a TRANSACTION (the Python app will do exactly this):
--     log the move and update the position together, or not at all.
START TRANSACTION;
  INSERT INTO moves (game_id, player_id, move_number, dice_roll,
                     from_square, to_square, jump_id)
  VALUES (2, 3, 1, 1, 0, 38, 1);            -- bob rolls 1 -> ladder 1->38
  UPDATE game_players SET position = 38
  WHERE game_id = 2 AND player_id = 3;
COMMIT;
