-- =====================================================================
--  Example 4: instant ALTER TABLE       (instant ADD 10.3+, DROP 10.4+)
--  Paste into any scratch database:  mariadb test < examples/04_instant_alter.sql
-- =====================================================================

CREATE OR REPLACE TABLE ex_login (
    login_id  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ip        INET6 NOT NULL,
    note      VARCHAR(200) NOT NULL DEFAULT ''
);
INSERT INTO ex_login (ip, note) SELECT '::ffff:10.0.0.1', REPEAT('x', 100) FROM seq_1_to_50000;

-- WITHOUT: the table is rebuilt row by row. With COPY, writes from the
-- game wait until it finishes, which is the "maintenance window".
ALTER TABLE ex_login ADD COLUMN user_agent VARCHAR(255) NULL, ALGORITHM=COPY;
ALTER TABLE ex_login DROP COLUMN user_agent, ALGORITHM=COPY;

-- WITH: only the table's metadata changes; time does not grow with the rows.
ALTER TABLE ex_login ADD COLUMN user_agent VARCHAR(255) NULL, ALGORITHM=INSTANT;
ALTER TABLE ex_login DROP COLUMN note, ALGORITHM=INSTANT;

-- ALGORITHM=INSTANT is a promise: if the change cannot be instant, the server
-- refuses instead of quietly rebuilding. Uncomment to see error 1846:
-- ALTER TABLE ex_login MODIFY ip VARCHAR(45) NOT NULL, ALGORITHM=INSTANT;

-- LIMITS TO KNOW
-- 1. ALGORITHM=INPLACE means "INPLACE or better": MariaDB may pick INSTANT.
--    To force a real online rebuild, add FORCE:  ..., FORCE, ALGORITHM=INPLACE
-- 2. An instant DROP COLUMN does not give the disk space back. The old values
--    stay in the rows until the table is rebuilt, e.g. with OPTIMIZE TABLE
--    or ALTER TABLE ex_login FORCE (which is not instant).

DROP TABLE ex_login;
