-- =====================================================================
--  Example 2: the INET6 data type         (MariaDB 10.5 or later)
--  Paste into any scratch database:  mariadb test < examples/02_inet6.sql
-- =====================================================================

-- WITHOUT: addresses as text.
CREATE OR REPLACE TABLE ex_login_text (ip VARCHAR(45) NOT NULL);
INSERT INTO ex_login_text VALUES
  ('10.0.0.9'), ('10.0.0.10'), ('10.9.0.1'), ('10.255.0.1'),
  ('2001:db8::1'), ('2001:0db8:0000:0000:0000:0000:0000:0001'),
  ('not-an-ip');                                     -- accepted!

SELECT ip FROM ex_login_text WHERE ip LIKE '10.%' ORDER BY ip;
-- Wrong order: 10.0.0.10, 10.0.0.9, 10.255.0.1, 10.9.0.1 (sorted as text)

SELECT COUNT(*) FROM ex_login_text WHERE ip BETWEEN '10.0.0.0' AND '10.255.255.255';
-- 3, but 4 addresses are in 10.0.0.0/8 ('10.9.0.1' > '10.255...' as text)

SELECT COUNT(DISTINCT ip) FROM ex_login_text;
-- 7: the two spellings of 2001:db8::1 count twice, and 'not-an-ip' counts too

-- WITH: INET6. 16 bytes, validated, compared as numbers.
-- IPv4 goes in IPv4-mapped form ::ffff:a.b.c.d (10.11 refuses plain '10.0.0.9').
CREATE OR REPLACE TABLE ex_login (ip INET6 NOT NULL, INDEX (ip));
INSERT INTO ex_login VALUES
  ('::ffff:10.0.0.9'), ('::ffff:10.0.0.10'), ('::ffff:10.9.0.1'), ('::ffff:10.255.0.1'),
  ('2001:db8::1'), ('2001:0db8:0000:0000:0000:0000:0000:0001');

SELECT ip FROM ex_login WHERE ip BETWEEN '::ffff:10.0.0.0' AND '::ffff:10.255.255.255'
ORDER BY ip;
-- All 4, in the right order. The BETWEEN can use the index.

SELECT COUNT(DISTINCT ip) FROM ex_login;          -- 5: same address, same value
SELECT ip FROM ex_login WHERE ip = '2001:db8:0::1';  -- any spelling finds it

-- Refused (uncomment to see "Incorrect inet6 value"):
-- INSERT INTO ex_login VALUES ('not-an-ip');

-- WHEN NOT: for IPv4-only data, INET6 is no smaller than text (16 bytes vs
-- about 12). INET4 (MariaDB 10.10+) stores 4 bytes and has the same benefits:
CREATE OR REPLACE TABLE ex_login4 (ip INET4 NOT NULL, INDEX (ip));
INSERT INTO ex_login4 VALUES ('10.0.0.9'), ('10.0.0.10'), ('10.9.0.1'), ('10.255.0.1');
SELECT ip FROM ex_login4 WHERE ip BETWEEN '10.0.0.0' AND '10.255.255.255' ORDER BY ip;
SELECT LENGTH(CAST(ip AS BINARY)) AS inet4_bytes FROM ex_login4 LIMIT 1;   -- 4

DROP TABLE ex_login_text, ex_login, ex_login4;
