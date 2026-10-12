"""Persistent approval snapshots and notification receipts in a project-local store."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from zoneinfo import ZoneInfo


def canonical_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class QQBotStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, payload TEXT NOT NULL,
                    digest TEXT NOT NULL, state TEXT NOT NULL, expires_at REAL NOT NULL,
                    actor TEXT, scope TEXT, target TEXT, risk_reviewed INTEGER DEFAULT 0,
                    created_at REAL NOT NULL, error TEXT
                );
                CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS notifications (
                    key TEXT PRIMARY KEY, state TEXT NOT NULL, message_id TEXT, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage (
                    day TEXT NOT NULL, kind TEXT NOT NULL, count INTEGER NOT NULL,
                    PRIMARY KEY(day, kind)
                );
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA journal_mode=WAL')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, payload: dict, ttl=1800) -> dict:
        digest = canonical_hash(payload)
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM approvals WHERE digest=? AND state IN ('pending','approved') AND expires_at>?",
                             (digest, now)).fetchone()
            if not row:
                identity = secrets.token_hex(8)
                db.execute('INSERT INTO approvals(id,project_id,payload,digest,state,expires_at,created_at) VALUES (?,?,?,?,?,?,?)',
                    (identity, payload['project_id'], json.dumps(payload, ensure_ascii=False), digest, 'pending', now+ttl, now))
                row = db.execute('SELECT * FROM approvals WHERE id=?', (identity,)).fetchone()
            result = dict(row)
            result['payload'] = json.loads(result['payload'])
            if not secrets.compare_digest(canonical_hash(result['payload']), result['digest']):
                raise ValueError('Approval snapshot content was modified')
            return result

    def get(self, identity: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM approvals WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise ValueError('Approval snapshot not found')
            result = dict(row)
            result['payload'] = json.loads(result['payload'])
            if not secrets.compare_digest(canonical_hash(result['payload']), result['digest']):
                raise ValueError('Approval snapshot content was modified')
            return result

    def list_pending(self, limit=10) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id FROM approvals WHERE state='pending' AND expires_at>? ORDER BY created_at DESC LIMIT ?",
                              (time.time(), limit)).fetchall()
        return [self.get(row['id']) for row in rows]

    def list_active(self, limit=100) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id FROM approvals WHERE state IN ('pending','approved') AND expires_at>? ORDER BY created_at DESC LIMIT ?",
                              (time.time(), limit)).fetchall()
        return [self.get(row['id']) for row in rows]

    def decide(self, identity, digest, *, actor, scope, target, approve, risk_reviewed=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM approvals WHERE id=?', (identity,)).fetchone()
            if row is None or row['state'] != 'pending' or row['expires_at'] <= time.time():
                raise ValueError('Approval is missing, expired or already decided')
            if not secrets.compare_digest(row['digest'][:16], digest):
                raise ValueError('Approval content version mismatch')
            payload = json.loads(row['payload'])
            if not secrets.compare_digest(canonical_hash(payload), row['digest']):
                raise ValueError('Approval snapshot content was modified')
            if payload.get('qq_target_type') != scope or payload.get('qq_target_id') != target:
                raise ValueError('Approval destination does not match the prepared snapshot')
            if approve and payload.get('review_required') and not risk_reviewed:
                raise ValueError('Unknown customer/qualification data requires explicit risk review')
            db.execute('UPDATE approvals SET state=?,actor=?,scope=?,target=?,risk_reviewed=? WHERE id=?',
                ('approved' if approve else 'rejected', actor, scope, target, int(risk_reviewed), identity))

    def claim(self, identity: str, daily_limit: int) -> dict:
        if daily_limit < 0:
            raise ValueError('Daily bid limit must be zero (unlimited) or positive')
        day = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM approvals WHERE id=?', (identity,)).fetchone()
            if row is None or row['state'] != 'approved' or row['expires_at'] <= time.time():
                raise ValueError('A current, approved snapshot is required')
            if not secrets.compare_digest(canonical_hash(json.loads(row['payload'])), row['digest']):
                raise ValueError('Approval snapshot content was modified')
            current = db.execute("SELECT count FROM usage WHERE day=? AND kind='bids'", (day,)).fetchone()
            if daily_limit > 0 and current and current['count'] >= daily_limit:
                raise ValueError('Daily bid attempt limit reached')
            db.execute("INSERT INTO usage(day,kind,count) VALUES (?,'bids',1) ON CONFLICT(day,kind) DO UPDATE SET count=count+1", (day,))
            db.execute("UPDATE approvals SET state='claimed' WHERE id=?", (identity,))
        return self.get(identity)

    def finish(self, identity: str, state: str, error=None):
        if state not in {'submitted', 'blocked', 'outcome_unknown'}:
            raise ValueError('Invalid terminal approval state')
        with self.connect() as db:
            db.execute("UPDATE approvals SET state=?,error=? WHERE id=? AND state='claimed'", (state, error, identity))

    def score_allowance(self, requested: int, limit: int) -> int:
        day = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT count FROM usage WHERE day=? AND kind='scores'", (day,)).fetchone()
            allowed = max(0, min(requested, limit-(row['count'] if row else 0)))
            db.execute("INSERT INTO usage(day,kind,count) VALUES (?,'scores',?) ON CONFLICT(day,kind) DO UPDATE SET count=count+excluded.count", (day, allowed))
            return allowed

    def receive_event(self, identity: str) -> bool:
        with self.connect() as db:
            try:
                db.execute('INSERT INTO events VALUES (?,?)', (identity, time.time()))
                return True
            except sqlite3.IntegrityError:
                return False

    def reserve_notification(self, key: str) -> bool:
        with self.connect() as db:
            try:
                db.execute("INSERT INTO notifications(key,state,created_at) VALUES (?,'sending',?)", (key, time.time()))
                return True
            except sqlite3.IntegrityError:
                return False

    def finish_notification(self, key: str, message_id=None):
        with self.connect() as db:
            db.execute('UPDATE notifications SET state=?,message_id=? WHERE key=?',
                       ('sent' if message_id else 'outcome_unknown', message_id, key))
