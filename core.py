"""Framework-independent booking core. Correctness lives in SQL, not in app-level locks."""
import json
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS shows(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seats(
  id INTEGER PRIMARY KEY, show_id INTEGER NOT NULL REFERENCES shows(id),
  label TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'AVAILABLE',
  held_by TEXT, hold_expires_at REAL, booking_id INTEGER,
  UNIQUE(show_id, label));
CREATE TABLE IF NOT EXISTS bookings(
  id INTEGER PRIMARY KEY, show_id INTEGER NOT NULL, user TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE, seats TEXT NOT NULL, created_at REAL NOT NULL);
"""


class Conflict(Exception):
    """Seats are taken, or the hold is missing/expired."""


class BookingService:
    def __init__(self, path="bookings.db", hold_seconds=300, clock=time.time):
        self.path, self.hold_seconds, self.clock = path, hold_seconds, clock
        c = sqlite3.connect(path)
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        c.close()

    @contextmanager
    def _tx(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    @staticmethod
    def _labels(labels):
        labels = sorted(set(labels))
        if not labels:
            raise ValueError("no seats given")
        return labels, ",".join("?" * len(labels))

    def create_show(self, name, rows, cols):
        with self._tx() as c:
            sid = c.execute("INSERT INTO shows(name) VALUES(?)", (name,)).lastrowid
            c.executemany("INSERT INTO seats(show_id,label) VALUES(?,?)",
                          [(sid, f"{chr(65 + r)}{k + 1}") for r in range(rows) for k in range(cols)])
        return {"show_id": sid, "seats": rows * cols}

    def seats(self, show_id):
        now = self.clock()
        c = sqlite3.connect(self.path)
        rows = c.execute("SELECT label,status,hold_expires_at FROM seats WHERE show_id=? ORDER BY id",
                         (show_id,)).fetchall()
        c.close()
        # Lazy expiry: an expired hold is reported (and treated) as AVAILABLE, no cron needed.
        return [{"seat": l, "status": "AVAILABLE" if s == "HELD" and (e or 0) < now else s}
                for l, s, e in rows]

    def hold(self, show_id, user, labels):
        labels, q = self._labels(labels)
        now = self.clock()
        expires = now + self.hold_seconds
        with self._tx() as c:
            # One atomic conditional UPDATE: only free (or expired-hold) seats can be claimed.
            n = c.execute(
                f"""UPDATE seats SET status='HELD', held_by=?, hold_expires_at=?
                    WHERE show_id=? AND label IN ({q})
                    AND (status='AVAILABLE' OR (status='HELD' AND hold_expires_at<?))""",
                [user, expires, show_id, *labels, now]).rowcount
            if n != len(labels):  # all-or-nothing: raising rolls the whole transaction back
                raise Conflict("one or more seats are unavailable")
        return {"seats": labels, "expires_at": expires}

    def book(self, show_id, user, labels, idempotency_key):
        labels, q = self._labels(labels)
        now = self.clock()
        with self._tx() as c:
            prev = c.execute("SELECT id, seats FROM bookings WHERE idempotency_key=?",
                             (idempotency_key,)).fetchone()
            if prev:  # client retry: return the original result, never double-book
                return {"booking_id": prev[0], "seats": json.loads(prev[1]), "replayed": True}
            n = c.execute(
                f"""UPDATE seats SET status='BOOKED', hold_expires_at=NULL
                    WHERE show_id=? AND label IN ({q})
                    AND status='HELD' AND held_by=? AND hold_expires_at>=?""",
                [show_id, *labels, user, now]).rowcount
            if n != len(labels):
                raise Conflict("hold missing or expired")
            bid = c.execute("INSERT INTO bookings(show_id,user,idempotency_key,seats,created_at) "
                            "VALUES(?,?,?,?,?)", (show_id, user, idempotency_key, json.dumps(labels), now)).lastrowid
            c.execute(f"UPDATE seats SET booking_id=? WHERE show_id=? AND label IN ({q})",
                      [bid, show_id, *labels])
        return {"booking_id": bid, "seats": labels, "replayed": False}
