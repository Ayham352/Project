-- =====================================================================
--  Snakes & Ladders: BASELINE schema
--  The same data model WITHOUT the newer features, written the way
--  it is commonly done:
--    game_id  CHAR(36) ASCII, generated in Python with uuid.uuid4()
--    ip       VARCHAR(45) ASCII, plain text
--    no RETURNING: the app runs INSERT, then a SELECT (app/repo_baseline.py)
--    DROP TABLE IF EXISTS list instead of CREATE OR REPLACE TABLE
-- =====================================================================

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS moves, game_players, games, board_jumps, boards, logins, players;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE players (
    player_id      INT UNSIGNED  AUTO_INCREMENT PRIMARY KEY,
    username       VARCHAR(30)   NOT NULL UNIQUE,
    password_hash  VARCHAR(255)  NOT NULL,
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE = InnoDB;

-- Every successful login, with the address it came from.
-- Plain text: the database cannot validate it or compare it as an address.
CREATE TABLE logins (
    login_id      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    player_id     INT UNSIGNED  NOT NULL,
    ip            VARCHAR(45) CHARACTER SET ascii NOT NULL,
    logged_in_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_login_ip (ip),
    CONSTRAINT fk_login_player FOREIGN KEY (player_id)
        REFERENCES players(player_id) ON DELETE CASCADE
) ENGINE = InnoDB;

CREATE TABLE boards (
    board_id  INT UNSIGNED  AUTO_INCREMENT PRIMARY KEY,
    name      VARCHAR(50)   NOT NULL UNIQUE,
    size      TINYINT UNSIGNED NOT NULL,
    CONSTRAINT chk_board_size CHECK (size BETWEEN 20 AND 200)
) ENGINE = InnoDB;

-- Snakes and ladders in one table: a ladder goes up, a snake goes down.
CREATE TABLE board_jumps (
    jump_id       INT UNSIGNED  AUTO_INCREMENT PRIMARY KEY,
    board_id      INT UNSIGNED  NOT NULL,
    jump_type     ENUM('snake','ladder') NOT NULL,
    start_square  TINYINT UNSIGNED NOT NULL,
    end_square    TINYINT UNSIGNED NOT NULL,
    CONSTRAINT uq_jump_start UNIQUE (board_id, start_square),
    CONSTRAINT fk_jump_board FOREIGN KEY (board_id)
        REFERENCES boards(board_id) ON DELETE CASCADE,
    CONSTRAINT chk_jump_direction CHECK (
        (jump_type = 'ladder' AND end_square > start_square) OR
        (jump_type = 'snake'  AND end_square < start_square))
) ENGINE = InnoDB;

-- The game id is also the join code players share.
-- CHAR(36) text form of a UUID; the app must generate it.
CREATE TABLE games (
    game_id       CHAR(36) CHARACTER SET ascii NOT NULL PRIMARY KEY,
    board_id      INT UNSIGNED  NOT NULL,
    status        ENUM('waiting','active','finished') NOT NULL DEFAULT 'waiting',
    current_turn  TINYINT UNSIGNED NOT NULL DEFAULT 1,
    winner_id     INT UNSIGNED  NULL,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at   DATETIME      NULL,
    CONSTRAINT fk_game_board  FOREIGN KEY (board_id) REFERENCES boards(board_id),
    CONSTRAINT fk_game_winner FOREIGN KEY (winner_id)
        REFERENCES players(player_id) ON DELETE SET NULL
) ENGINE = InnoDB;

CREATE TABLE game_players (
    game_id     CHAR(36) CHARACTER SET ascii NOT NULL,
    player_id   INT UNSIGNED  NOT NULL,
    turn_order  TINYINT UNSIGNED NOT NULL,
    position    TINYINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, player_id),
    CONSTRAINT uq_turn UNIQUE (game_id, turn_order),
    CONSTRAINT fk_gp_game   FOREIGN KEY (game_id)
        REFERENCES games(game_id) ON DELETE CASCADE,
    CONSTRAINT fk_gp_player FOREIGN KEY (player_id)
        REFERENCES players(player_id) ON DELETE CASCADE,
    CONSTRAINT chk_turn_order CHECK (turn_order BETWEEN 1 AND 4)
) ENGINE = InnoDB;

CREATE TABLE moves (
    move_id      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    game_id      CHAR(36) CHARACTER SET ascii NOT NULL,
    player_id    INT UNSIGNED  NOT NULL,
    move_number  SMALLINT UNSIGNED NOT NULL,
    dice_roll    TINYINT UNSIGNED NOT NULL,
    from_square  TINYINT UNSIGNED NOT NULL,
    to_square    TINYINT UNSIGNED NOT NULL,
    jump_id      INT UNSIGNED  NULL,
    played_at    DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_move_number UNIQUE (game_id, move_number),
    CONSTRAINT fk_move_gp FOREIGN KEY (game_id, player_id)
        REFERENCES game_players(game_id, player_id) ON DELETE CASCADE,
    CONSTRAINT fk_move_jump FOREIGN KEY (jump_id)
        REFERENCES board_jumps(jump_id) ON DELETE SET NULL,
    CONSTRAINT chk_dice CHECK (dice_roll BETWEEN 1 AND 6)
) ENGINE = InnoDB;
