"""Optional app accounts; school credentials are never accepted or stored."""
from collections import defaultdict, deque
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from uuid import uuid4

from fastapi import HTTPException

COOKIE = "path_session"
TTL = 8 * 60 * 60


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + digest


class Auth:
    def __init__(self, db):
        self.db = db
        self.buckets = defaultdict(deque)
        self.lock = threading.Lock()

    def limit(self, key, count=10, window=60):
        now = time.monotonic()
        with self.lock:
            # Bound cardinality even when caller-controlled usernames vary.
            for k in list(self.buckets):
                if not self.buckets[k] or self.buckets[k][-1] <= now - window:
                    del self.buckets[k]
            values = self.buckets[key]
            while values and values[0] <= now-window:
                values.popleft()
            if len(values) >= count:
                raise HTTPException(429, "요청이 많습니다. 1분 후 다시 시도하세요.")
            values.append(now)

    def register(self, data):
        account_id = uuid4().hex
        try:
            with self.db.connect() as db:
                db.execute("INSERT INTO accounts VALUES(?,?,?,?)", (account_id, data.username,
                    password_hash(data.password), datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "사용할 수 없는 계정 이름입니다.") from None
        return account_id

    def login(self, data):
        with self.db.connect() as db:
            row = db.execute("SELECT id,password_hash FROM accounts WHERE username=?", (data.username,)).fetchone()
        stored = row["password_hash"] if row else "00"*16 + ":" + "00"*64
        match = hmac.compare_digest(password_hash(data.password, stored.split(":")[0]), stored)
        if not row or not match:
            raise HTTPException(401, "계정 이름 또는 비밀번호를 확인하세요.")
        return row["id"]

    def issue(self, owner):
        token = secrets.token_urlsafe(32)
        with self.db.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (self.token_hash(token), owner, time.time()+TTL))
        return token

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def user(self, token):
        if not token or len(token) > 100:
            return None
        with self.db.connect() as db:
            row = db.execute("SELECT a.id,a.username FROM sessions s JOIN accounts a ON a.id=s.owner_id WHERE s.token_hash=? AND s.expires>?",
                             (self.token_hash(token), time.time())).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        if token:
            with self.db.connect() as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (self.token_hash(token),))
