-- Run once as an admin user (e.g. `sudo mariadb < sql/setup.sql`).
-- Creates the two databases and one application user.
-- Change the password, and put the same one in your .env file.

CREATE DATABASE IF NOT EXISTS snl_modern   CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS snl_baseline CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'snl'@'localhost' IDENTIFIED BY 'change-me';
GRANT ALL PRIVILEGES ON snl_modern.*   TO 'snl'@'localhost';
GRANT ALL PRIVILEGES ON snl_baseline.* TO 'snl'@'localhost';

-- Used only by the tests (python -m unittest); their tables are recreated each run.
CREATE DATABASE IF NOT EXISTS snl_test_modern   CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS snl_test_baseline CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON snl_test_modern.*   TO 'snl'@'localhost';
GRANT ALL PRIVILEGES ON snl_test_baseline.* TO 'snl'@'localhost';
