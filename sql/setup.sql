-- Databases used by the project. Run by `python -m app.setup`, which also
-- creates the application user with the password from your .env file.
-- (No password is written in this file.)

CREATE DATABASE IF NOT EXISTS snl_modern        CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS snl_baseline      CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Used only by the tests (python -m unittest); their tables are recreated each run.
CREATE DATABASE IF NOT EXISTS snl_test_modern   CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS snl_test_baseline CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
