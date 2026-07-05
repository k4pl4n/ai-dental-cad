"""Case persistence. (SPEC §9)

Two backends behind the same interface:
- SQLite (default) — local dev, zero setup.
- Postgres/Supabase — set DATABASE_URL (Supabase → Project Settings →
  Database → Connection string). Schema in supabase/migrations/0001_init.sql.

Audit log doubles as the regulatory evidence pack (SPEC §12).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading

from ..models.schemas import AuditEvent, Case, Correction

DATA_DIR = os.environ.get("AIDCAD_DATA_DIR",
                          os.path.join(os.path.dirname(__file__), "..", "..", "data"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))

_DB_PATH = os.path.join(DATA_DIR, "aidcad.db")
_lock = threading.Lock()


# ------------------------------------------------------------------ SQLite

def _sqlite() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(_DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS cases (
        case_id TEXT PRIMARY KEY, reference TEXT, user_id TEXT,
        status TEXT, payload TEXT, updated_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT,
        event TEXT, detail TEXT, timestamp TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT,
        correction_type TEXT, tooth_number INTEGER,
        original_value TEXT, corrected_value TEXT, timestamp TEXT)""")
    return c


# ---------------------------------------------------------------- Postgres

_pg_pool = None


def _pg():
    """Connection via psycopg2. Schema is created by the Supabase migration,
    but CREATE IF NOT EXISTS here keeps `railway run` and fresh DBs working."""
    global _pg_pool
    import psycopg2
    import psycopg2.pool
    if _pg_pool is None:
        _pg_pool = psycopg2.pool.SimpleConnectionPool(1, 5, DATABASE_URL)
        conn = _pg_pool.getconn()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY, reference TEXT, user_id TEXT,
                    status TEXT, payload JSONB, updated_at TIMESTAMPTZ)""")
                cur.execute("""CREATE TABLE IF NOT EXISTS audit (
                    id BIGSERIAL PRIMARY KEY, case_id TEXT,
                    event TEXT, detail TEXT, timestamp TIMESTAMPTZ)""")
                cur.execute("""CREATE TABLE IF NOT EXISTS corrections (
                    id BIGSERIAL PRIMARY KEY, case_id TEXT,
                    correction_type TEXT, tooth_number INTEGER,
                    original_value TEXT, corrected_value TEXT, timestamp TIMESTAMPTZ)""")
        finally:
            _pg_pool.putconn(conn)
    return _pg_pool


class _PgConn:
    def __enter__(self):
        self.pool = _pg()
        self.conn = self.pool.getconn()
        return self.conn

    def __exit__(self, exc_type, *a):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.pool.putconn(self.conn)


# ------------------------------------------------------------------ public

def save_case(case: Case) -> None:
    if _PG:
        with _PgConn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO cases (case_id, reference, user_id, status, payload, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (case_id) DO UPDATE SET
                     status=EXCLUDED.status, payload=EXCLUDED.payload,
                     updated_at=EXCLUDED.updated_at""",
                (case.case_id, case.reference, case.user_id, case.status.value,
                 case.model_dump_json(), case.updated_at))
        return
    with _lock, _sqlite() as c:
        c.execute("REPLACE INTO cases VALUES (?,?,?,?,?,?)",
                  (case.case_id, case.reference, case.user_id, case.status.value,
                   case.model_dump_json(), case.updated_at.isoformat()))


def load_case(case_id: str) -> Case | None:
    if _PG:
        with _PgConn() as conn, conn.cursor() as cur:
            cur.execute("SELECT payload FROM cases WHERE case_id=%s", (case_id,))
            row = cur.fetchone()
        if not row:
            return None
        payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return Case.model_validate(payload)
    with _lock, _sqlite() as c:
        row = c.execute("SELECT payload FROM cases WHERE case_id=?", (case_id,)).fetchone()
    return Case.model_validate(json.loads(row[0])) if row else None


def list_cases(user_id: str = "dev") -> list[dict]:
    q = ("SELECT case_id, reference, status, updated_at FROM cases "
         "WHERE user_id={} ORDER BY updated_at DESC LIMIT 100")
    if _PG:
        with _PgConn() as conn, conn.cursor() as cur:
            cur.execute(q.format("%s"), (user_id,))
            rows = cur.fetchall()
    else:
        with _lock, _sqlite() as c:
            rows = c.execute(q.format("?"), (user_id,)).fetchall()
    return [{"case_id": r[0], "reference": r[1], "status": r[2], "updated_at": str(r[3])}
            for r in rows]


def add_audit(event: AuditEvent) -> None:
    if _PG:
        with _PgConn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO audit (case_id, event, detail, timestamp) "
                        "VALUES (%s,%s,%s,%s)",
                        (event.case_id, event.event, event.detail, event.timestamp))
        return
    with _lock, _sqlite() as c:
        c.execute("INSERT INTO audit (case_id, event, detail, timestamp) VALUES (?,?,?,?)",
                  (event.case_id, event.event, event.detail, event.timestamp.isoformat()))


def add_correction(corr: Correction) -> None:
    """Every override is training data — the flywheel. (SPEC §8)"""
    if _PG:
        with _PgConn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO corrections (case_id, correction_type, tooth_number, "
                        "original_value, corrected_value, timestamp) VALUES (%s,%s,%s,%s,%s,%s)",
                        (corr.case_id, corr.correction_type, corr.tooth_number,
                         corr.original_value, corr.corrected_value, corr.timestamp))
        return
    with _lock, _sqlite() as c:
        c.execute("INSERT INTO corrections (case_id, correction_type, tooth_number, "
                  "original_value, corrected_value, timestamp) VALUES (?,?,?,?,?,?)",
                  (corr.case_id, corr.correction_type, corr.tooth_number,
                   corr.original_value, corr.corrected_value, corr.timestamp.isoformat()))
