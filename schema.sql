-- =====================================================================
--  Snakes & Ladders Platform — MariaDB schema
--  Databases course (Constructor University) — semester project
--
--  Run:  mariadb -u <user> -p <database> < schema.sql
-- =====================================================================

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS moves, game_players, games, board_jumps, boards, players;
SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------
-- 1. PLAYERS — registered user accounts
--    Passwords are stored only as a hash (never plain text).
-- ---------------------------------------------------------------------
CREATE TABLE players (
    player_id      INT UNSIGNED  AUTO_INCREMENT PRIMARY KEY,
    username       VARCHAR(30)   NOT NULL UNIQUE,
    email          VARCHAR(100)  NOT NULL UNIQUE,
    password_hash  VARCHAR(255)  NOT NULL,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 2. BOARDS — a board layout is data, not hard-coded in Python
-- ---------------------------------------------------------------------
CREATE TABLE boards (
    board_id     INT UNSIGNED  AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(50)   NOT NULL UNIQUE,
    size         TINYINT UNSIGNED NOT NULL DEFAULT 100,   -- number of squares
    created_by   INT UNSIGNED  NULL,
    CONSTRAINT fk_board_creator FOREIGN KEY (created_by)
        REFERENCES players(player_id) ON DELETE SET NULL,
    CONSTRAINT chk_board_size CHECK (size BETWEEN 20 AND 200)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 3. BOARD_JUMPS — snakes and ladders on a board
--    One table for both: a ladder goes up (end > start),
--    a snake goes down (end < start).
-- ---------------------------------------------------------------------
CREATE TABLE board_jumps (
    jump_id       INT UNSIGNED  AUTO_INCREMENT PRIMARY KEY,
    board_id      INT UNSIGNED  NOT NULL,
    jump_type     ENUM('snake','ladder') NOT NULL,
    start_square  TINYINT UNSIGNED NOT NULL,
    end_square    TINYINT UNSIGNED NOT NULL,
    CONSTRAINT fk_jump_board FOREIGN KEY (board_id)
        REFERENCES boards(board_id) ON DELETE CASCADE,
    -- a square can hold at most one snake head / ladder foot
    CONSTRAINT uq_jump_start UNIQUE (board_id, start_square),
    CONSTRAINT chk_jump_direction CHECK (
        (jump_type = 'ladder' AND end_square > start_square) OR
        (jump_type = 'snake'  AND end_square < start_square)
    ),
    CONSTRAINT chk_jump_min CHECK (start_square >= 1 AND end_square >= 1)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 4. GAMES — one match played on one board
-- ---------------------------------------------------------------------
CREATE TABLE games (
    game_id       INT UNSIGNED  AUTO_INCREMENT PRIMARY KEY,
    board_id      INT UNSIGNED  NOT NULL,
    status        ENUM('waiting','active','finished') NOT NULL DEFAULT 'waiting',
    current_turn  TINYINT UNSIGNED NOT NULL DEFAULT 1,  -- turn_order whose turn it is
    winner_id     INT UNSIGNED  NULL,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at   DATETIME      NULL,
    CONSTRAINT fk_game_board  FOREIGN KEY (board_id)
        REFERENCES boards(board_id),
    CONSTRAINT fk_game_winner FOREIGN KEY (winner_id)
        REFERENCES players(player_id) ON DELETE SET NULL
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 5. GAME_PLAYERS — many-to-many: which players are in which game
--    Also stores each player's turn order and current square.
-- ---------------------------------------------------------------------
CREATE TABLE game_players (
    game_id      INT UNSIGNED  NOT NULL,
    player_id    INT UNSIGNED  NOT NULL,
    turn_order   TINYINT UNSIGNED NOT NULL,     -- 1, 2, 3, 4
    position     TINYINT UNSIGNED NOT NULL DEFAULT 0,  -- 0 = not yet on board
    PRIMARY KEY (game_id, player_id),
    CONSTRAINT uq_turn UNIQUE (game_id, turn_order),
    CONSTRAINT fk_gp_game   FOREIGN KEY (game_id)
        REFERENCES games(game_id) ON DELETE CASCADE,
    CONSTRAINT fk_gp_player FOREIGN KEY (player_id)
        REFERENCES players(player_id) ON DELETE CASCADE,
    CONSTRAINT chk_turn_order CHECK (turn_order BETWEEN 1 AND 4)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 6. MOVES — log of every dice roll (the basis for all statistics)
-- ---------------------------------------------------------------------
CREATE TABLE moves (
    move_id      INT UNSIGNED  AUTO_INCREMENT PRIMARY KEY,
    game_id      INT UNSIGNED  NOT NULL,
    player_id    INT UNSIGNED  NOT NULL,
    move_number  SMALLINT UNSIGNED NOT NULL,   -- 1, 2, 3 ... within the game
    dice_roll    TINYINT UNSIGNED NOT NULL,
    from_square  TINYINT UNSIGNED NOT NULL,
    to_square    TINYINT UNSIGNED NOT NULL,    -- final square after any jump
    jump_id      INT UNSIGNED  NULL,           -- snake/ladder hit, if any
    played_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_move_number UNIQUE (game_id, move_number),
    CONSTRAINT fk_move_gp   FOREIGN KEY (game_id, player_id)
        REFERENCES game_players(game_id, player_id) ON DELETE CASCADE,
    CONSTRAINT fk_move_jump FOREIGN KEY (jump_id)
        REFERENCES board_jumps(jump_id) ON DELETE SET NULL,
    CONSTRAINT chk_dice CHECK (dice_roll BETWEEN 1 AND 6)
) ENGINE = InnoDB;

-- =====================================================================
--  SAMPLE DATA
-- =====================================================================

-- Password hashes are placeholders; the Python app will create real ones.
INSERT INTO players (username, email, password_hash) VALUES
  ('nancy', 'nancy@example.com', 'placeholder-hash'),
  ('alice', 'alice@example.com', 'placeholder-hash'),
  ('bob',   'bob@example.com',   'placeholder-hash');

-- Board 1: classic 100-square board
INSERT INTO boards (name, size, created_by) VALUES ('Classic', 100, 1);

INSERT INTO board_jumps (board_id, jump_type, start_square, end_square) VALUES
  (1,'ladder', 1,38), (1,'ladder', 4,14), (1,'ladder', 9,31),
  (1,'ladder',21,42), (1,'ladder',28,84), (1,'ladder',51,67),
  (1,'ladder',71,91), (1,'ladder',80,100),
  (1,'snake', 17, 7), (1,'snake', 54,34), (1,'snake', 62,19),
  (1,'snake', 64,60), (1,'snake', 87,24), (1,'snake', 93,73),
  (1,'snake', 95,75), (1,'snake', 99,78);

-- Board 2: a small quick board
INSERT INTO boards (name, size, created_by) VALUES ('Quick 30', 30, 1);
INSERT INTO board_jumps (board_id, jump_type, start_square, end_square) VALUES
  (2,'ladder', 3,22), (2,'ladder', 5, 8), (2,'ladder',11,26),
  (2,'snake', 17, 4), (2,'snake', 19, 7), (2,'snake', 27, 1);

-- One finished game: nancy vs alice on the Quick board
INSERT INTO games (board_id, status, winner_id, finished_at)
VALUES (2, 'finished', 1, NOW());

INSERT INTO game_players (game_id, player_id, turn_order, position) VALUES
  (1, 1, 1, 30),
  (1, 2, 2, 7);

INSERT INTO moves (game_id, player_id, move_number, dice_roll, from_square, to_square, jump_id) VALUES
  (1, 1, 1, 3,  0, 22, 17),   -- nancy lands on 3 -> ladder to 22
  (1, 2, 2, 5,  0,  8, 18),   -- alice lands on 5 -> ladder to 8
  (1, 1, 3, 4, 22, 26, NULL),
  (1, 2, 4, 6,  8, 14, NULL),
  (1, 1, 5, 2, 26, 28, NULL),
  (1, 2, 6, 5, 14,  7, 21),   -- alice lands on 19 -> snake to 7
  (1, 1, 7, 2, 28, 30, NULL); -- nancy reaches 30 and wins

-- One game still waiting for players: bob on the Classic board
INSERT INTO games (board_id, status) VALUES (1, 'waiting');
INSERT INTO game_players (game_id, player_id, turn_order) VALUES (2, 3, 1);
