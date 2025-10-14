# app/common/storage.py
import os, sqlite3

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

JOBS_DB_PATH  = os.path.join(DATA_DIR, "print_jobs.sqlite")
CACHE_DB_PATH = os.path.join(DATA_DIR, "tracking_cache.sqlite")

# -------------------------------------------------
# Connections
# -------------------------------------------------
def _apply_pragmas(con: sqlite3.Connection):
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=3000;")
    con.row_factory = sqlite3.Row

def jobs_db() -> sqlite3.Connection:
    con = sqlite3.connect(JOBS_DB_PATH)
    _apply_pragmas(con)
    return con

def cache_db() -> sqlite3.Connection:
    con = sqlite3.connect(CACHE_DB_PATH)
    _apply_pragmas(con)
    return con

# -------------------------------------------------
# print_jobs schema (mail) + indexes
# -------------------------------------------------
def ensure_jobs_schema():
    con = jobs_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS print_jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          module          TEXT NOT NULL,
          job_type        TEXT,
          payload         TEXT,
          checkin_date    TEXT,
          checkin_id      TEXT,
          package_type    TEXT,
          package_id      TEXT,
          recipient_name  TEXT,
          tracking_number TEXT,
          status          TEXT DEFAULT 'queued',
          printer         TEXT,
          template        TEXT,
          ts_utc          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)
    try: con.execute("ALTER TABLE print_jobs ADD COLUMN package_type TEXT")
    except Exception: pass
    con.execute("CREATE INDEX IF NOT EXISTS pj_idx_module   ON print_jobs(module)")
    con.execute("CREATE INDEX IF NOT EXISTS pj_idx_created  ON print_jobs(ts_utc)")
    con.execute("CREATE INDEX IF NOT EXISTS pj_idx_tracking ON print_jobs(tracking_number)")
    con.execute("CREATE INDEX IF NOT EXISTS pj_idx_checkin  ON print_jobs(checkin_id)")
    con.execute("CREATE INDEX IF NOT EXISTS pj_idx_package  ON print_jobs(package_id)")
    con.execute("CREATE INDEX IF NOT EXISTS pj_idx_packtype ON print_jobs(package_type)")
    con.commit(); con.close()

# -------------------------------------------------
# Sequences for Send (CheckInID + per-type PackageID)
# -------------------------------------------------
def ensure_mail_sequences():
    con = jobs_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS checkin_id_seq(
          id INTEGER PRIMARY KEY CHECK (id=1),
          last_value INTEGER
        )
    """)
    row = con.execute("SELECT last_value FROM checkin_id_seq WHERE id=1").fetchone()
    if not row:
        con.execute("INSERT INTO checkin_id_seq(id, last_value) VALUES (1, 9999999999)")
    con.execute("""
        CREATE TABLE IF NOT EXISTS package_seq(
          package_type TEXT PRIMARY KEY,
          last_value   INTEGER
        )
    """)
    con.commit(); con.close()

def next_checkin_id() -> int:
    con = jobs_db(); cur = con.cursor()
    cur.execute("BEGIN IMMEDIATE")
    last = cur.execute("SELECT last_value FROM checkin_id_seq WHERE id=1").fetchone()[0]
    nxt  = last + 1
    cur.execute("UPDATE checkin_id_seq SET last_value=?", (nxt,))
    con.commit(); con.close()
    return nxt

def peek_next_checkin_id() -> int:
    con = jobs_db()
    last = con.execute("SELECT last_value FROM checkin_id_seq WHERE id=1").fetchone()[0]
    con.close()
    return last + 1

PACKAGE_PREFIX = {
    "Box":"BOX", "Envelope":"ENV", "Packs":"PACK", "Tubes":"TUBE",
    "Certified":"CERT", "Sensitive":"SEN", "Critical":"CRIT",
}

def ensure_package_row(pkg_type: str):
    con = jobs_db()
    row = con.execute("SELECT last_value FROM package_seq WHERE package_type=?", (pkg_type,)).fetchone()
    if not row:
        con.execute("INSERT INTO package_seq(package_type, last_value) VALUES(?, 0)", (pkg_type,))
        con.commit()
    con.close()

def next_package_id(pkg_type: str) -> str:
    prefix = PACKAGE_PREFIX.get(pkg_type, "PACK")
    ensure_package_row(pkg_type)
    con = jobs_db(); cur = con.cursor()
    cur.execute("BEGIN IMMEDIATE")
    last = cur.execute("SELECT last_value FROM package_seq WHERE package_type=?", (pkg_type,)).fetchone()[0]
    nxt  = last + 1
    cur.execute("UPDATE package_seq SET last_value=? WHERE package_type=?", (nxt, pkg_type))
    con.commit(); con.close()
    return f"{prefix}{nxt:08d}"

def peek_next_package_id(pkg_type: str) -> str:
    prefix = PACKAGE_PREFIX.get(pkg_type, "PACK")
    ensure_package_row(pkg_type)
    con  = jobs_db()
    last = con.execute("SELECT last_value FROM package_seq WHERE package_type=?", (pkg_type,)).fetchone()[0]
    con.close()
    return f"{prefix}{(last+1):08d}"

# -------------------------------------------------
# Inventory schema + seq
# -------------------------------------------------
def ensure_inventory_schema():
    con = jobs_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS inventory_reports(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          checkin_date    TEXT,
          inventory_id    INTEGER,
          item_type       TEXT,
          manufacturer    TEXT,
          product_name    TEXT,
          submitter_name  TEXT,
          notes           TEXT,
          part_number     TEXT,
          serial_number   TEXT,
          count           INTEGER,
          location        TEXT,
          template        TEXT,
          printer         TEXT,
          status          TEXT DEFAULT 'queued',
          ts_utc          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
          payload         TEXT
        )
    """)
    for ddl in (
        "ALTER TABLE inventory_reports ADD COLUMN part_number TEXT",
        "ALTER TABLE inventory_reports ADD COLUMN serial_number TEXT",
        "ALTER TABLE inventory_reports ADD COLUMN count INTEGER",
        "ALTER TABLE inventory_reports ADD COLUMN location TEXT",
    ):
        try: con.execute(ddl)
        except Exception: pass
    for idx in (
        "CREATE INDEX IF NOT EXISTS inv_idx_checkin_date ON inventory_reports(checkin_date)",
        "CREATE INDEX IF NOT EXISTS inv_idx_inventory_id ON inventory_reports(inventory_id)",
        "CREATE INDEX IF NOT EXISTS inv_idx_item_type    ON inventory_reports(item_type)",
        "CREATE INDEX IF NOT EXISTS inv_idx_manu         ON inventory_reports(manufacturer)",
        "CREATE INDEX IF NOT EXISTS inv_idx_product      ON inventory_reports(product_name)",
        "CREATE INDEX IF NOT EXISTS inv_idx_submitter    ON inventory_reports(submitter_name)",
        "CREATE INDEX IF NOT EXISTS inv_idx_location     ON inventory_reports(location)",
    ):
        con.execute(idx)
    con.commit(); con.close()

def ensure_inventory_seq():
    con = jobs_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS inventory_id_seq(
          id INTEGER PRIMARY KEY CHECK (id=1),
          last_value INTEGER
        )
    """)
    row = con.execute("SELECT last_value FROM inventory_id_seq WHERE id=1").fetchone()
    if not row:
        con.execute("INSERT INTO inventory_id_seq(id, last_value) VALUES (1, 999999999)")
    con.commit(); con.close()

def next_inventory_id() -> int:
    ensure_inventory_seq()
    con = jobs_db(); cur = con.cursor()
    cur.execute("BEGIN IMMEDIATE")
    last = cur.execute("SELECT last_value FROM inventory_id_seq WHERE id=1").fetchone()[0]
    nxt  = last + 1
    cur.execute("UPDATE inventory_id_seq SET last_value=?", (nxt,))
    con.commit(); con.close()
    return nxt

def peek_next_inventory_id() -> int:
    ensure_inventory_seq()
    con  = jobs_db()
    last = con.execute("SELECT last_value FROM inventory_id_seq WHERE id=1").fetchone()[0]
    con.close()
    return last + 1

# -------------------------------------------------
# Tracking cache (for /mail/tracking)
# -------------------------------------------------
def ensure_cache_schema():
    con = cache_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS cache(
          tracking TEXT PRIMARY KEY,
          carrier  TEXT,
          payload  TEXT,
          updated  TEXT
        )
    """)
    con.commit(); con.close()

# -------------------------------------------------
# Fulfillment Center schema + sequence
# -------------------------------------------------
def ensure_fulfillment_schema():
    con = jobs_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS fulfillment_requests(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          service_id       TEXT UNIQUE,
          description      TEXT,
          requester_user_id INTEGER,
          requester_name   TEXT,
          date_submitted   TEXT,
          date_due         TEXT,
          status           TEXT,
          print_type       TEXT,
          paper_size       TEXT,
          paper_stock      TEXT,
          paper_color      TEXT,
          paper_sides      TEXT,
          binding          TEXT,
          covers           TEXT,
          tabs             TEXT,
          finishing        TEXT,
          page_count       INTEGER,
          additional_details TEXT,
          meta_json        TEXT,
          ts_utc           TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS fulfillment_files(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          request_id INTEGER,
          filename   TEXT,
          stored_path TEXT,
          bytes      INTEGER,
          status     TEXT,
          note       TEXT,
          uploaded_utc TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS f_req_idx ON fulfillment_requests(ts_utc)")
    con.execute("CREATE INDEX IF NOT EXISTS f_files_req_idx ON fulfillment_files(request_id)")
    con.commit(); con.close()

def ensure_fulfillment_seq():
    con = jobs_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS fulfillment_id_seq(
          id INTEGER PRIMARY KEY CHECK (id=1),
          last_value INTEGER
        )
    """)
    row = con.execute("SELECT last_value FROM fulfillment_id_seq WHERE id=1").fetchone()
    if not row:
        con.execute("INSERT INTO fulfillment_id_seq(id, last_value) VALUES(1, 0)")
    con.commit(); con.close()

def next_service_id() -> str:
    ensure_fulfillment_seq()
    con = jobs_db(); cur = con.cursor()
    cur.execute("BEGIN IMMEDIATE")
    last = cur.execute("SELECT last_value FROM fulfillment_id_seq WHERE id=1").fetchone()[0]
    nxt = last + 1
    cur.execute("UPDATE fulfillment_id_seq SET last_value=?", (nxt,))
    con.commit(); con.close()
    return f"F{nxt:06d}"

# -------------------------------------------------
# One-shot initializer
# -------------------------------------------------
def init_all_dbs():
    ensure_jobs_schema()
    ensure_mail_sequences()
    ensure_inventory_schema()
    ensure_inventory_seq()
    ensure_cache_schema()
    ensure_fulfillment_schema()   
    ensure_fulfillment_seq()      