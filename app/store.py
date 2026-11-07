import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path
from app.cloud import enabled as cloud_enabled

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('OFFICE_DATA_DIR', ROOT / 'local-data'))

def connect():
    if cloud_enabled():
        from app.postgres import connect as pg_connect
        return pg_connect()
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / 'office.db', timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    return db

@contextlib.contextmanager
def transaction():
    db = connect()
    try:
        if not cloud_enabled():
            db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init():
    if cloud_enabled():
        with transaction() as db:
            if not db.execute('SELECT version FROM schema_migrations WHERE version=1').fetchone():
                raise RuntimeError('Run the Supabase migration before starting the app')
        return
    with transaction() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, mode TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL, author TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, draft_id TEXT UNIQUE NOT NULL REFERENCES drafts(id), payload TEXT NOT NULL, status TEXT NOT NULL, lease TEXT, leased_at REAL, result TEXT, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots(mode TEXT PRIMARY KEY, payload TEXT NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL, at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS report_requests(id TEXT PRIMARY KEY, report TEXT NOT NULL, params TEXT NOT NULL, status TEXT NOT NULL, result TEXT, lease TEXT, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS history_periods(start TEXT PRIMARY KEY,end_date TEXT NOT NULL,payload TEXT NOT NULL,updated REAL,attempted REAL NOT NULL,lease TEXT,error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, mode TEXT NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL, path TEXT NOT NULL, created REAL NOT NULL);
        ''')

def audit(db, actor, action, target):
    db.execute('INSERT INTO audit(actor,action,target,at) VALUES(?,?,?,?)', (actor, action, target, time.time()))

def snapshot(db, mode):
    row = db.execute('SELECT * FROM snapshots WHERE mode=?', (mode,)).fetchone()
    return json.loads(row['payload']) | {'synced_at': row['updated']} if row else {'ledgers': [], 'stock': [], 'company': 'Upkar Agency', 'synced_at': None}
