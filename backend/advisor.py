"""Owner-scoped local counseling history; no automatic model training."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException, Query, Request
from fastapi.responses import Response

from backend.database import MissingProfile, RevisionConflict
from backend.schemas import ChatFeedback, ChatRequest, ChatTurn, PlanningInput, SavedChatRequest
from src.planning.workspace import source_fingerprint, seoul_today


def input_fingerprint(data):
    # Keep the current academic snapshot separate from mutable conversational text.
    # Hashes stay local; neither transcript grades nor checklist notes enter memory.
    raw = data.model_dump(mode="json", include=set(PlanningInput.model_fields) - {"checklist"})
    # Crossing an expiry/submission date can change the audit without an edit.
    # Avoid invalidating every conversation merely because another day passed.
    record = data.profile.language
    today = seoul_today()
    confirmed = bool(record and record.submission_confirmed and record.submitted_on and record.submitted_on <= today)
    raw["language_time_state"] = {
        "confirmed": confirmed,
        "expired": bool(record and record.expires_on and record.expires_on < (record.submitted_on if confirmed else today)),
    }
    return hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class AdvisorStore:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def owner(db, profile_id, owner_id):
        row = db.execute("SELECT revision FROM profiles WHERE id=? AND owner_id=?", (profile_id, owner_id)).fetchone()
        if row is None:
            raise MissingProfile()
        return row[0]

    @staticmethod
    def decode(row):
        return {"id": row["id"], "sequence": row["sequence"], "created_at": row["created_at"],
                "question": row["question"], "status": row["status"], "revision": row["revision"],
                "input_fingerprint": row["input_fingerprint"], "rules_fingerprint": row["rules_fingerprint"],
                "feedback": json.loads(row["feedback_json"]), **json.loads(row["reply_json"])}

    def list(self, profile_id, owner_id, before=None, limit=50):
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, profile_id, owner_id)
            cutoff = (datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat()
            db.execute("UPDATE chat_turns SET status='interrupted' WHERE profile_id=? AND status='pending' AND created_at<=?", (profile_id, cutoff))
            rows = db.execute("SELECT * FROM chat_turns WHERE profile_id=? AND sequence<? ORDER BY sequence DESC LIMIT ?",
                              (profile_id, before or 2**63-1, limit+1)).fetchall()
            return {"messages": [self.decode(r) for r in reversed(rows[:limit])],
                    "before": rows[limit-1]["sequence"] if len(rows)>limit else None}

    def reserve(self, profile_id, owner_id, data, fingerprint, rules):
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            revision = self.owner(db, profile_id, owner_id)
            previous = db.execute("SELECT * FROM chat_turns WHERE profile_id=? AND request_id=?",
                                  (profile_id, data.request_id)).fetchone()
            if previous:
                if previous["question"] != data.question or previous["input_fingerprint"] != fingerprint or previous["rules_fingerprint"] != rules:
                    raise RevisionConflict()
                if previous["status"] != "complete":
                    raise HTTPException(409, "이미 처리 중이거나 중단된 상담입니다. 기록을 새로고침하고 새 질문으로 다시 시도하세요.")
                return previous["id"], self.decode(previous)
            if revision != data.profile_revision:
                raise RevisionConflict()
            cutoff = (datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat()
            if db.execute("SELECT 1 FROM chat_turns WHERE profile_id=? AND status='pending' AND created_at>?", (profile_id, cutoff)).fetchone():
                raise HTTPException(409, "이 계획의 다른 상담이 진행 중입니다. 잠시 후 다시 시도하세요.")
            db.execute("UPDATE chat_turns SET status='interrupted' WHERE profile_id=? AND status='pending'", (profile_id,))
            turn_id = uuid4().hex
            db.execute("INSERT INTO chat_turns(id,profile_id,request_id,created_at,input_fingerprint,rules_fingerprint,question,status) VALUES(?,?,?,?,?,?,?,'pending')",
                       (turn_id, profile_id, data.request_id, utc_now(), fingerprint, rules, data.question))
            return turn_id, None

    def complete(self, profile_id, owner_id, turn_id, reply):
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, profile_id, owner_id)
            if db.execute("UPDATE chat_turns SET status='complete',reply_json=? WHERE id=? AND profile_id=? AND status='pending'",
                          (json.dumps(reply, ensure_ascii=False), turn_id, profile_id)).rowcount != 1:
                raise MissingProfile()
            return self.decode(db.execute("SELECT * FROM chat_turns WHERE id=?", (turn_id,)).fetchone())

    def memory(self, profile_id, owner_id, fingerprint, rules, *, with_sources=False):
        with self.database.connect() as db:
            db.execute("BEGIN")
            self.owner(db, profile_id, owner_id)
            rows = db.execute("SELECT * FROM chat_turns WHERE profile_id=? AND status='complete' ORDER BY sequence DESC LIMIT 100", (profile_id,)).fetchall()
        history, corrections, available = [], [], set()
        for raw in reversed(rows):
            row = self.decode(raw)
            if row["input_fingerprint"] != fingerprint or row["rules_fingerprint"] != rules or row.get("mode") != "llm":
                continue
            feedback = row["feedback"]
            if feedback.get("verified"):
                source = {"id":row["id"], "revision":row["revision"], "kind":"correction"}
                available.add((row["id"], row["revision"], "correction"))
                corrections.append(({"question":row["question"], "correction":feedback["correction"], "source":feedback["source"]}, source))
                # Never replay the original answer once corrected.
                continue
            if feedback.get("rating") == "unhelpful" or feedback.get("correction", "").strip():
                continue
            # A later answer may have repeated a now-corrected/deleted answer.
            # Invalidate that dependency chain instead of replaying it indirectly.
            if any((s["id"], s["revision"], s["kind"]) not in available for s in row.get("memory_sources", [])):
                continue
            source = {"id":row["id"], "revision":row["revision"], "kind":"history"}
            available.add((row["id"], row["revision"], "history"))
            history.append((ChatTurn(question=row["question"], answer=row["answer"]), source))
        history, corrections = history[-6:], corrections[-3:]
        result = ([v for v, _ in history], [v for v, _ in corrections])
        return (*result, [s for _, s in history + corrections]) if with_sources else result

    def feedback(self, profile_id, owner_id, turn_id, data):
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, profile_id, owner_id)
            row = db.execute("SELECT * FROM chat_turns WHERE id=? AND profile_id=?", (turn_id, profile_id)).fetchone()
            if row is None:
                raise MissingProfile()
            if row["revision"] != data.revision:
                raise RevisionConflict()
            if row["status"] != "complete" or json.loads(row["reply_json"]).get("mode") != "llm":
                raise ValueError("생성 완료된 AI 답변만 평가할 수 있습니다.")
            raw = data.model_dump(exclude={"revision"}) | {"updated_at":utc_now()}
            encoded = json.dumps(raw, ensure_ascii=False)
            db.execute("UPDATE chat_turns SET feedback_json=?,revision=revision+1 WHERE id=?", (encoded, turn_id))
            db.execute("INSERT INTO chat_feedback_events(turn_id,created_at,feedback_json) VALUES(?,?,?)", (turn_id, raw["updated_at"], encoded))
            return self.decode(db.execute("SELECT * FROM chat_turns WHERE id=?", (turn_id,)).fetchone())

    def delete(self, profile_id, owner_id, turn_id, revision):
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, profile_id, owner_id)
            row = db.execute("SELECT revision,status FROM chat_turns WHERE id=? AND profile_id=?", (turn_id, profile_id)).fetchone()
            if not row:
                raise MissingProfile()
            if row[0] != revision:
                raise RevisionConflict()
            if row[1] == "pending":
                raise ValueError("처리 중인 상담은 완료 후 삭제하세요.")
            db.execute("DELETE FROM chat_turns WHERE id=?", (turn_id,))

    def export(self, profile_id, owner_id):
        with self.database.connect() as db:
            db.execute("BEGIN")
            self.owner(db, profile_id, owner_id)
            rows = [self.decode(r) for r in db.execute("SELECT * FROM chat_turns WHERE profile_id=? ORDER BY sequence", (profile_id,))]
            events = [dict(r) for r in db.execute("SELECT e.turn_id,e.created_at,e.feedback_json FROM chat_feedback_events e JOIN chat_turns t ON t.id=e.turn_id WHERE t.profile_id=? ORDER BY e.id", (profile_id,))]
        for event in events:
            event["feedback"] = json.loads(event.pop("feedback_json"))
        groups = {}
        for row in rows:
            if row.get("mode") != "llm":
                continue
            group = groups.setdefault(row["model"], {"answers":0, "rated":0, "helpful":0, "unhelpful":0, "verified_corrections":0})
            group["answers"] += 1
            rating = row["feedback"].get("rating")
            if rating in ("helpful", "unhelpful"):
                group["rated"] += 1
                group[rating] += 1
            group["verified_corrections"] += int(row["feedback"].get("verified", False))
        return {"kind":"path-counseling-export", "exported_at":utc_now(), "messages":rows,
                "feedback_events":events, "by_model":groups,
                "notice":"개인의 답변 평가·정정 기록입니다. 평가 비율은 공식 정확도나 성능 개선을 입증하지 않습니다. 자동 학습에 사용하지 않습니다."}


def register_advisor(app, service, database):
    store = AdvisorStore(database)

    @app.get("/api/profiles/{profile_id}/chat")
    def history(profile_id: str, request: Request, before: int | None = Query(default=None, ge=1)):
        return store.list(profile_id, request.state.owner_id, before)

    @app.post("/api/profiles/{profile_id}/chat/context")
    def context_status(profile_id: str, data: PlanningInput, request: Request):
        fingerprint, rules = input_fingerprint(data), source_fingerprint(service.root)
        history, corrections = store.memory(profile_id, request.state.owner_id, fingerprint, rules)
        return {"input_fingerprint":fingerprint, "rules_fingerprint":rules,
                "history_count":len(history), "correction_count":len(corrections)}

    @app.post("/api/profiles/{profile_id}/chat")
    def chat(profile_id: str, data: SavedChatRequest, request: Request):
        owner = request.state.owner_id
        if not data.consent:
            raise HTTPException(400, "AI 전송 항목을 확인하고 동의한 뒤 질문하세요.")
        fingerprint, rules = input_fingerprint(data), source_fingerprint(service.root)
        turn_id, previous = store.reserve(profile_id, owner, data, fingerprint, rules)
        if previous:
            return previous
        history, corrections, sources = store.memory(profile_id, owner, fingerprint, rules, with_sources=True) if data.use_history else ([], [], [])
        current = ChatRequest.model_validate(data.model_dump(exclude={"request_id", "profile_revision", "use_history"}))
        current.history = history  # Never trust browser-supplied historical answers.
        try:
            reply = service.chat(current, corrections=corrections)
        except Exception:
            store.complete(profile_id, owner, turn_id, {"mode":"fallback", "answer":"상담 처리가 중단되었습니다. 현재 입력을 확인하고 다시 질문하세요.", "referenced_checks":[], "recommended_codes":[], "model":""})
            raise
        reply["memory_used"] = {"history_count":len(history), "correction_count":len(corrections)}
        reply["memory_sources"] = sources
        return store.complete(profile_id, owner, turn_id, reply)

    @app.put("/api/profiles/{profile_id}/chat/{turn_id}/feedback")
    def feedback(profile_id: str, turn_id: str, data: ChatFeedback, request: Request):
        return store.feedback(profile_id, request.state.owner_id, turn_id, data)

    @app.delete("/api/profiles/{profile_id}/chat/{turn_id}", status_code=204)
    def delete(profile_id: str, turn_id: str, request: Request, revision: int = Query(ge=1)):
        store.delete(profile_id, request.state.owner_id, turn_id, revision)
        return Response(status_code=204)

    @app.get("/api/profiles/{profile_id}/chat-export")
    def export(profile_id: str, request: Request):
        return store.export(profile_id, request.state.owner_id)
