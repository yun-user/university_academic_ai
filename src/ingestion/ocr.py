"""Optional Tesseract language-data based OCR; only reviewed pages enter search."""
import hashlib
import os
from pathlib import Path

from src.ingestion.registry import database, safe_path, timestamp
from src.operations import project_lock


def language_data(root, languages="kor+eng"):
    directory = Path(os.getenv("TESSDATA_PREFIX") or Path(root) / "data/tessdata")
    missing = [lang for lang in languages.split("+") if not (directory / f"{lang}.traineddata").is_file()]
    if missing:
        raise ValueError("OCR 언어 데이터가 없습니다: " + ", ".join(missing) +
                         ". python -m scripts.setup_ocr 명령으로 설치하세요.")
    return directory


def recognize_page(root, document, page_number, *, languages="kor+eng", dpi=250):
    import pymupdf
    if not 72 <= dpi <= 300:
        raise ValueError("OCR 해상도는 72~300 DPI로 지정하세요.")
    tessdata = language_data(root, languages)
    path = safe_path(root, document["path"])
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with pymupdf.open(path) as pdf:
        if not 1 <= page_number <= len(pdf):
            raise ValueError("PDF 페이지 범위를 벗어났습니다.")
        page = pdf[page_number - 1]
        if page.rect.width * page.rect.height * (dpi / 72) ** 2 > 30_000_000:
            raise ValueError("페이지가 너무 큽니다. OCR 해상도를 낮추세요.")
        textpage = page.get_textpage_ocr(language=languages, dpi=dpi, full=True,
                                       tessdata=str(tessdata))
        text = page.get_text("text", textpage=textpage).strip()
    if not text:
        raise ValueError("이 페이지에서 문자를 인식하지 못했습니다.")
    with project_lock(Path(root).resolve()), database(root) as con:
        con.execute("INSERT OR REPLACE INTO ocr VALUES (?,?,?,?,0)",
                    (document["id"], page_number, sha, text))
        con.execute("INSERT INTO audit VALUES (?,?,?,?)",
                    (timestamp(), "ocr_pending", document["id"], str(page_number)))
    return text


def review_page(root, document, page_number, text, *, approved=True):
    if not text.strip():
        raise ValueError("빈 OCR 결과는 승인할 수 없습니다.")
    sha = hashlib.sha256(safe_path(root, document["path"]).read_bytes()).hexdigest()
    with project_lock(Path(root).resolve()), database(root) as con:
        row = con.execute("SELECT hash FROM ocr WHERE id=? AND page=?",
                          (document["id"], page_number)).fetchone()
        if row is None or row["hash"] != sha:
            raise ValueError("원본이 변경되었거나 OCR 결과가 없습니다. 다시 실행하세요.")
        con.execute("UPDATE ocr SET text=?,approved=? WHERE id=? AND page=?",
                    (text.strip(), int(approved), document["id"], page_number))
        con.execute("INSERT INTO audit VALUES (?,?,?,?)",
                    (timestamp(), "ocr_approved" if approved else "ocr_rejected",
                     document["id"], str(page_number)))


def page_preview(root, document, page_number):
    import pymupdf
    with pymupdf.open(safe_path(root, document["path"])) as pdf:
        page = pdf[page_number - 1]
        scale = min(1.2, 1200 / max(page.rect.width, page.rect.height))
        return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png")
