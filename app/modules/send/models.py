# app/modules/mail/models.py
import os, sqlite3
from app.common.storage import DATA_DIR

MAIL_DB = os.path.join(DATA_DIR, "mail.sqlite")

def _conn():
    con = sqlite3.connect(MAIL_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON;")
    return con

def ensure_mail_schema():
    con = _conn()
    con.execute("""
      CREATE TABLE IF NOT EXISTS print_jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        submitter_name TEXT,
        tracking TEXT,
        carrier TEXT,
        status TEXT
      )
    """)
    con.commit(); con.close()
