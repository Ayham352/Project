-- =====================================================================
--  Example 5: CREATE OR REPLACE            (MariaDB 10.0.8 or later)
--  Paste into any scratch database:  mariadb test < examples/05_create_or_replace.sql
-- =====================================================================

-- WITHOUT: every re-runnable script carries a DROP list that must be kept in
-- sync with the CREATE statements below it (forget one and the script fails;
-- list one too many and it silently drops data you meant to keep).
DROP TABLE IF EXISTS ex_board_jumps, ex_boards;
CREATE TABLE ex_boards (board_id INT PRIMARY KEY, name VARCHAR(50) NOT NULL);
CREATE TABLE ex_board_jumps (jump_id INT PRIMARY KEY, board_id INT NOT NULL,
                             FOREIGN KEY (board_id) REFERENCES ex_boards(board_id));

-- WITH: each statement says what it replaces; the script can be re-run as is.
SET FOREIGN_KEY_CHECKS = 0;      -- lets a parent be replaced while children exist
CREATE OR REPLACE TABLE ex_boards (board_id INT PRIMARY KEY, name VARCHAR(50) NOT NULL);
CREATE OR REPLACE TABLE ex_board_jumps (jump_id INT PRIMARY KEY, board_id INT NOT NULL,
                                        FOREIGN KEY (board_id) REFERENCES ex_boards(board_id));
SET FOREIGN_KEY_CHECKS = 1;

-- It works for views, procedures, functions, triggers, sequences and more:
CREATE OR REPLACE VIEW ex_board_list AS SELECT board_id, name FROM ex_boards;
CREATE OR REPLACE VIEW ex_board_list AS SELECT board_id, UPPER(name) AS name FROM ex_boards;
SELECT * FROM ex_board_list;

-- LIMIT TO KNOW: CREATE OR REPLACE TABLE throws the old table and its rows
-- away, just like DROP + CREATE. It is for set-up scripts, not for changing
-- a table that holds data you need (use ALTER TABLE, see example 4).

DROP VIEW ex_board_list;
DROP TABLE ex_board_jumps, ex_boards;
