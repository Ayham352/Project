-- =====================================================================
--  Example 1: the UUID data type          (MariaDB 10.7 or later)
--  Paste into any scratch database:  mariadb test < examples/01_uuid.sql
-- =====================================================================

-- WITHOUT: a UUID kept as text. 36 bytes per value, and the application
-- has to create it (e.g. Python uuid.uuid4()) before it can insert.
CREATE OR REPLACE TABLE ex_game_text (
    game_id  CHAR(36) CHARACTER SET ascii NOT NULL PRIMARY KEY,
    board    VARCHAR(20) NOT NULL
);
INSERT INTO ex_game_text VALUES ('3f2b6c1e-8a4d-4c2b-9e1f-7d5a0b9c8e21', 'Classic 100');

-- WITH: the UUID type. 16 bytes per value, the server generates it,
-- and invalid text is refused.
CREATE OR REPLACE TABLE ex_game (
    game_id  UUID NOT NULL DEFAULT UUID() PRIMARY KEY,
    board    VARCHAR(20) NOT NULL
);
INSERT INTO ex_game (board) VALUES ('Classic 100'), ('Quick 30');
SELECT game_id, board FROM ex_game;

-- Values from elsewhere are still accepted, and compared as UUIDs:
INSERT INTO ex_game VALUES ('3F2B6C1E-8A4D-4C2B-9E1F-7D5A0B9C8E21', 'Imported');
SELECT board FROM ex_game WHERE game_id = '3f2b6c1e-8a4d-4c2b-9e1f-7d5a0b9c8e21';

-- Storage per value:
SELECT LENGTH(game_id) AS text_bytes FROM ex_game_text;                  -- 36
SELECT LENGTH(CAST(game_id AS BINARY)) AS uuid_bytes FROM ex_game LIMIT 1;  -- 16

-- Refused (uncomment to see the error "Incorrect uuid value"):
-- INSERT INTO ex_game VALUES ('not-a-uuid', 'Broken');

-- LIMIT TO KNOW: UUID() makes version-1 UUIDs, built from a timestamp and the
-- server's MAC address. They are unique, but predictable: do not use them as
-- secrets (such as unguessable invite links) on their own. MariaDB 11.7 adds
-- UUID_v4() (random) and UUID_v7() (time-ordered and random).

DROP TABLE ex_game_text, ex_game;
