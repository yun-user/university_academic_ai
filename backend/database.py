"""SQLite aggregate persistence with atomic revisions and normalized attempts."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from backend.schemas import SaveProfile
from src.planning.models import Profile


class MissingProfile(Exception):
    pass


class RevisionConflict(Exception):
    pass


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise RuntimeError("Unsupported database schema version")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision >= 1),
                    admission_year INTEGER NOT NULL CHECK(admission_year = 2020),
                    track TEXT NOT NULL CHECK(track IN ('심화', '일반')),
                    profile_json TEXT NOT NULL, options_json TEXT NOT NULL,
                    goal TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS course_attempts (
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
                    credits REAL NOT NULL CHECK(credits > 0), category TEXT NOT NULL,
                    area INTEGER NOT NULL, design_credits REAL NOT NULL,
                    equivalent_code TEXT NOT NULL, year INTEGER NOT NULL,
                    term INTEGER NOT NULL, grade TEXT NOT NULL, status TEXT NOT NULL,
                    PRIMARY KEY(profile_id, position)
                );
                CREATE INDEX IF NOT EXISTS idx_attempt_code ON course_attempts(profile_id, code);
                CREATE TABLE IF NOT EXISTS plan_runs (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, created_at TEXT NOT NULL,
                    rules_fingerprint TEXT NOT NULL, result_json TEXT NOT NULL,
                    UNIQUE(profile_id, revision)
                );
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(profiles)")}
            if "settings_json" not in columns:
                db.execute("ALTER TABLE profiles ADD COLUMN settings_json TEXT NOT NULL DEFAULT '{}'")
            if "owner_id" not in columns:
                db.execute("ALTER TABLE profiles ADD COLUMN owner_id TEXT NOT NULL DEFAULT ''")
            db.executescript("""
                CREATE INDEX IF NOT EXISTS idx_profile_owner ON profiles(owner_id);
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    password_hash TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
            """)
        if version < 3:
            self._upgrade_cohorts()

    def _upgrade_cohorts(self):
        # SQLite cannot alter a CHECK constraint in place. Rebuild only the
        # parent table in one transaction, preserving IDs, children and owners.
        with self.connect() as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE profiles_v3 (
                id TEXT PRIMARY KEY, label TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                admission_year INTEGER NOT NULL CHECK(admission_year BETWEEN 2018 AND 2026),
                track TEXT NOT NULL CHECK(track IN ('심화', '일반')),
                profile_json TEXT NOT NULL, options_json TEXT NOT NULL,
                goal TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                settings_json TEXT NOT NULL DEFAULT '{}', owner_id TEXT NOT NULL DEFAULT ''
            )""")
            columns = "id,label,revision,admission_year,track,profile_json,options_json,goal,created_at,updated_at,settings_json,owner_id"
            db.execute(f"INSERT INTO profiles_v3({columns}) SELECT {columns} FROM profiles")
            db.execute("DROP TABLE profiles")
            db.execute("ALTER TABLE profiles_v3 RENAME TO profiles")
            db.execute("CREATE INDEX idx_profile_owner ON profiles(owner_id)")
            if "sw_data_credits" not in {row[1] for row in db.execute("PRAGMA table_info(course_attempts)")}:
                db.execute("ALTER TABLE course_attempts ADD COLUMN sw_data_credits REAL NOT NULL DEFAULT 0")
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("DB 이전 중 참조 무결성 검사 실패. 이전을 취소했습니다.")
            db.execute("PRAGMA user_version=3")

    def list_profiles(self, owner_id=""):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT p.id,p.label,p.revision,p.admission_year,p.track,p.updated_at,
                       (SELECT count(*) FROM course_attempts a WHERE a.profile_id=p.id) AS course_count
                FROM profiles p WHERE p.owner_id=? ORDER BY p.updated_at DESC
            """, (owner_id,))]

    @staticmethod
    def _read(db, profile_id, owner_id=""):
        row = db.execute("SELECT * FROM profiles WHERE id=? AND owner_id=?", (profile_id, owner_id)).fetchone()
        if row is None:
            raise MissingProfile()
        attempts = [dict(a) for a in db.execute("SELECT * FROM course_attempts WHERE profile_id=? ORDER BY position", (profile_id,))]
        for attempt in attempts:
            attempt.pop("profile_id")
            attempt.pop("position")
        return {"id": row["id"], "label": row["label"], "revision": row["revision"],
                "created_at": row["created_at"], "updated_at": row["updated_at"],
                "profile": Profile.model_validate_json(row["profile_json"]).model_dump(), "options": json.loads(row["options_json"]),
                "goal": row["goal"], "attempts": attempts, **json.loads(row["settings_json"])}

    def get_profile(self, profile_id, owner_id=""):
        with self.connect() as db:
            # A consistent snapshot across profile and attempts while another tab saves.
            db.execute("BEGIN")
            return self._read(db, profile_id, owner_id)

    def save(self, data: SaveProfile, result, profile_id=None, owner_id=""):
        now = datetime.now(timezone.utc).isoformat()
        encode = lambda value: json.dumps(value, ensure_ascii=False)
        settings = data.model_dump_json(include={"candidates", "placements", "checklist"})
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if profile_id is None:
                if data.revision is not None:
                    raise RevisionConflict()
                profile_id, revision = uuid4().hex, 1
                db.execute("INSERT INTO profiles(id,label,revision,admission_year,track,profile_json,options_json,goal,created_at,updated_at,settings_json,owner_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                    profile_id, data.label, revision, data.profile.admission_year, data.profile.track,
                    data.profile.model_dump_json(), data.options.model_dump_json(), data.goal, now, now, settings, owner_id))
            else:
                current = db.execute("SELECT revision FROM profiles WHERE id=? AND owner_id=?", (profile_id, owner_id)).fetchone()
                if current is None:
                    raise MissingProfile()
                if data.revision != current["revision"]:
                    raise RevisionConflict()
                revision = current["revision"] + 1
                db.execute("""UPDATE profiles SET label=?,revision=?,admission_year=?,track=?,
                           profile_json=?,options_json=?,goal=?,updated_at=?,settings_json=? WHERE id=?""", (
                    data.label, revision, data.profile.admission_year, data.profile.track,
                    data.profile.model_dump_json(), data.options.model_dump_json(), data.goal, now, settings, profile_id))
                db.execute("DELETE FROM course_attempts WHERE profile_id=?", (profile_id,))
            db.executemany("INSERT INTO course_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                (profile_id, i, a.code, a.name, a.credits, a.category, a.area, a.design_credits,
                 a.equivalent_code, a.year, a.term, a.grade, a.status, a.sw_data_credits) for i, a in enumerate(data.attempts)])
            db.execute("INSERT INTO plan_runs VALUES(?,?,?,?,?,?)", (
                uuid4().hex, profile_id, revision, now, result["rules_fingerprint"], encode(result)))
            return self._read(db, profile_id, owner_id)

    def history(self, profile_id, owner_id=""):
        with self.connect() as db:
            db.execute("BEGIN")
            self._read(db, profile_id, owner_id)
            return [{"id": r["id"], "revision": r["revision"], "created_at": r["created_at"],
                     "rules_fingerprint": r["rules_fingerprint"], "result": json.loads(r["result_json"])}
                    for r in db.execute("SELECT * FROM plan_runs WHERE profile_id=? ORDER BY revision DESC LIMIT 20", (profile_id,))]

    def delete(self, profile_id, revision, owner_id=""):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._read(db, profile_id, owner_id)
            if record["revision"] != revision:
                raise RevisionConflict()
            db.execute("DELETE FROM profiles WHERE id=?", (profile_id,))

    def evaluations(self, owner_id=""):
        with self.connect() as db:
            return [{"id":r["id"], "created_at":r["created_at"], **json.loads(r["data_json"])}
                    for r in db.execute("SELECT * FROM evaluations WHERE owner_id=? ORDER BY created_at DESC LIMIT 500", (owner_id,))]

    def add_evaluation(self, data, owner_id=""):
        record_id, now = uuid4().hex, datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("INSERT INTO evaluations VALUES(?,?,?,?)", (record_id, owner_id, now, data.model_dump_json()))
        return {"id":record_id, "created_at":now, **data.model_dump(mode="json")}

    def delete_evaluation(self, record_id, owner_id=""):
        with self.connect() as db:
            if db.execute("DELETE FROM evaluations WHERE id=? AND owner_id=?", (record_id,owner_id)).rowcount != 1:
                raise MissingProfile()
