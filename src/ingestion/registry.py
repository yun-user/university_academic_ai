"""Immutable document uploads, activation state, OCR review and audit history."""
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from urllib.parse import urlsplit

from src.operations import project_lock


def timestamp():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def database(root):
    path = Path(root) / "data/catalog/registry.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL,
          metadata TEXT NOT NULL, hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS states (id TEXT PRIMARY KEY, active INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS ocr (
          id TEXT, page INTEGER, hash TEXT, text TEXT, approved INTEGER DEFAULT 0,
          PRIMARY KEY(id,page));
        CREATE TABLE IF NOT EXISTS audit (
          time TEXT, action TEXT, document_id TEXT, detail TEXT);
        ''')
        with con:
            yield con
    finally:
        con.close()


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root / "data"):
        raise ValueError("자료 폴더 밖의 파일은 사용할 수 없습니다.")
    return path


def validate_upload(name, data, *, max_mb=50, max_pages=1000):
    if not data or len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"비어 있거나 {max_mb}MB를 초과한 파일입니다.")
    suffix = Path(name).suffix.lower()
    if suffix not in {".pdf", ".csv", ".txt"}:
        raise ValueError("PDF, CSV, TXT만 등록할 수 있습니다.")
    if suffix == ".pdf":
        import pymupdf
        if not data.startswith(b"%PDF-"):
            raise ValueError("올바른 PDF 파일이 아닙니다.")
        try:
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                if doc.needs_pass or not 0 < len(doc) <= max_pages:
                    raise ValueError("암호화되었거나 허용 페이지 수를 초과한 PDF입니다.")
        except RuntimeError as exc:
            raise ValueError("PDF를 읽을 수 없습니다.") from exc
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeError as exc:
            raise ValueError("CSV/TXT는 UTF-8로 저장한 뒤 등록하세요.") from exc
        if "\x00" in text or not text.strip():
            raise ValueError("내용이 없거나 텍스트 형식이 올바르지 않습니다.")
        if suffix == ".csv":
            rows = list(csv.reader(io.StringIO(text)))
            if len(rows) < 2 or not any(rows[0]):
                raise ValueError("CSV에는 머리글과 데이터 행이 필요합니다.")
    return suffix


def register_document(root, name, data, metadata, *, replaces=None):
    suffix = validate_upload(name, data)
    url = str(metadata.get("source_url") or "")
    if url and (urlsplit(url).scheme != "https" or not urlsplit(url).hostname
                or urlsplit(url).username):
        raise ValueError("출처 URL은 인증정보 없는 HTTPS 주소여야 합니다.")
    document_id = "UPLOAD-" + uuid4().hex
    name = Path(name.replace("\\", "/")).name
    if len(name) > 180 or any(ord(c) < 32 for c in name):
        raise ValueError("파일명이 너무 길거나 올바르지 않습니다.")
    relative = f"data/uploads/{document_id}/source{suffix}"
    sha = hashlib.sha256(data).hexdigest()
    with project_lock(Path(root).resolve()), database(root) as con:
        # Identical active registrations are idempotent, but changed metadata is a new version.
        meta = {str(k): str(v or "") for k, v in metadata.items()}
        serialized = json.dumps(meta, ensure_ascii=False, sort_keys=True)
        duplicate = con.execute('''SELECT d.id FROM documents d LEFT JOIN states s ON d.id=s.id
          WHERE d.hash=? AND d.name=? AND d.metadata=? AND COALESCE(s.active,1)=1''',
          (sha, name, serialized)).fetchone()
        if duplicate and not replaces:
            return duplicate["id"]
        path = safe_path(root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(data)
        con.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                    (document_id, name, relative, serialized, sha, timestamp()))
        con.execute("INSERT INTO states VALUES (?,1)", (document_id,))
        if replaces:
            con.execute("INSERT OR REPLACE INTO states VALUES (?,0)", (replaces,))
        con.execute("INSERT INTO audit VALUES (?,?,?,?)",
                    (timestamp(), "register", document_id, json.dumps({"replaces": replaces})))
    return document_id


def set_active(root, document_id, active):
    with project_lock(Path(root).resolve()), database(root) as con:
        con.execute("INSERT OR REPLACE INTO states VALUES (?,?)", (document_id, int(active)))
        con.execute("INSERT INTO audit VALUES (?,?,?,?)",
                    (timestamp(), "activate" if active else "deactivate", document_id, ""))


def list_documents(root):
    from src.ingestion.build_corpus import MANIFEST_RELATIVE_PATH
    manifest = Path(root) / MANIFEST_RELATIVE_PATH
    rows = []
    if manifest.exists():
        with manifest.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                folder = {"pdf": "pdfs", "csv": "tables", "txt": "text"}.get(row["file_type"])
                if folder:
                    rows.append({"id": row["document_id"], "name": row["file_name"],
                        "path": f'data/raw/{folder}/{row["file_name"]}', "metadata": row})
    with database(root) as con:
        rows.extend({**dict(row), "metadata": json.loads(row["metadata"])}
                    for row in con.execute("SELECT * FROM documents ORDER BY created_at DESC"))
        states = dict(con.execute("SELECT id,active FROM states"))
    return [{**row, "active": bool(states.get(row["id"], 1))} for row in rows]


def augment_corpus(root, documents, report):
    from src.ingestion.build_corpus import _process_pdf, _process_csv, _process_txt
    with database(root) as con:
        managed = list(con.execute("SELECT * FROM documents ORDER BY created_at"))
        states = dict(con.execute("SELECT id,active FROM states"))
        ocr = {(r["id"], r["page"]): dict(r) for r in con.execute("SELECT * FROM ocr WHERE approved=1")}
    for row in managed:
        if not states.get(row["id"], 1):
            continue
        path = safe_path(root, row["path"])
        kind = path.suffix[1:]
        manifest = {**json.loads(row["metadata"]), "document_id": row["id"],
                    "file_name": row["name"], "file_type": kind}
        report["total_files"] += 1
        report[{"pdf": "pdf_files", "csv": "csv_files", "txt": "txt_files"}[kind]] += 1
        records = {"pdf": _process_pdf, "csv": _process_csv, "txt": _process_txt}[kind](
            path, project_root=Path(root), manifest=manifest, report=report)
        for record in records:
            record["file_name"] = row["name"]
            record["title"] = manifest.get("title") or Path(row["name"]).stem
            record["metadata"]["collected_at"] = manifest.get("collected_at")
        documents.extend(records)
    kept = []
    for record in documents:
        if not states.get(record["document_id"], 1):
            continue
        override = ocr.get((record["document_id"], record.get("page_number")))
        if override and override["hash"] == record["metadata"].get("source_file_hash"):
            record["text"] = override["text"]
            record["searchable"] = bool(override["text"].strip())
            record["metadata"]["ocr_reviewed"] = True
        kept.append(record)
    return kept
