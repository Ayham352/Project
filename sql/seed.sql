-- Board layouts, loaded into BOTH databases (modern and baseline).

INSERT INTO boards (board_id, name, size) VALUES
  (1, 'Classic 100', 100),
  (2, 'Quick 30', 30);

INSERT INTO board_jumps (board_id, jump_type, start_square, end_square) VALUES
  (1,'ladder', 1,38), (1,'ladder', 4,14), (1,'ladder', 9,31),
  (1,'ladder',21,42), (1,'ladder',28,84), (1,'ladder',51,67),
  (1,'ladder',71,91), (1,'ladder',80,100),
  (1,'snake', 17, 7), (1,'snake', 54,34), (1,'snake', 62,19),
  (1,'snake', 64,60), (1,'snake', 87,24), (1,'snake', 93,73),
  (1,'snake', 95,75), (1,'snake', 99,78),
  (2,'ladder', 3,22), (2,'ladder', 5, 8), (2,'ladder',11,26),
  (2,'snake', 17, 4), (2,'snake', 19, 7), (2,'snake', 27, 1);
