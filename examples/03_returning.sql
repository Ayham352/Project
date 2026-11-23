-- =====================================================================
--  Example 3: INSERT ... RETURNING and DELETE ... RETURNING  (MariaDB 10.5+)
--  Paste into any scratch database:  mariadb test < examples/03_returning.sql
-- =====================================================================

CREATE OR REPLACE TABLE ex_move (
    move_id    BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    player     VARCHAR(30) NOT NULL,
    dice_roll  TINYINT UNSIGNED NOT NULL,
    played_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);

-- WITHOUT: two statements (two round trips) to learn what the server filled in.
INSERT INTO ex_move (player, dice_roll) VALUES ('alice', 4);
SELECT move_id, played_at FROM ex_move WHERE move_id = LAST_INSERT_ID();

-- WITH: one statement returns the new row's server-generated values.
INSERT INTO ex_move (player, dice_roll) VALUES ('bob', 6)
RETURNING move_id, played_at;

-- Works for several rows at once (LAST_INSERT_ID() only gives the first id):
INSERT INTO ex_move (player, dice_roll) VALUES ('alice', 2), ('bob', 1)
RETURNING move_id, player;

-- DELETE ... RETURNING: remove rows and see what was removed, in one step.
-- WITHOUT it you would SELECT first, then DELETE (and lock between them).
DELETE FROM ex_move WHERE player = 'bob' RETURNING move_id, dice_roll;

-- LIMIT TO KNOW: on MariaDB 10.11 there is no UPDATE ... RETURNING.
-- RETURNING works with INSERT, INSERT ... SELECT, REPLACE and DELETE.

DROP TABLE ex_move;
