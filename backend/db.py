"""SQLite 初始化与建表。使用标准库 sqlite3，无需 CGO 或外部驱动。"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  openid      TEXT UNIQUE,
  unionid     TEXT,
  nickname    TEXT,
  avatar      TEXT,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS weread_accounts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER UNIQUE,
  cookie       TEXT,
  wr_vid       TEXT,
  wr_name      TEXT,
  last_sync_at DATETIME,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS books (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id   INTEGER,
  book_id   TEXT,
  title     TEXT,
  author    TEXT,
  cover     TEXT,
  source    TEXT,
  status    TEXT,
  progress  INTEGER DEFAULT 0,
  added_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, book_id)
);
CREATE TABLE IF NOT EXISTS checkins (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER,
  date       TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, date)
);
CREATE TABLE IF NOT EXISTS reminders (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER,
  time         TEXT,
  enabled      INTEGER DEFAULT 1,
  last_sent_at TEXT,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  user_id    INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS user_stats (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER,
  date       TEXT,
  payload    TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def init(path: str) -> sqlite3.Connection:
    """打开 SQLite 并建表。check_same_thread=False 以允许后台调度线程复用连接。"""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    print("db initialized at", path)
    return conn
