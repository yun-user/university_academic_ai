"""Install only Tesseract language data, without changing system programs."""
import hashlib
import json
from pathlib import Path
import urllib.request
from src.config import PROJECT_ROOT


def main():
    folder = PROJECT_ROOT / "data/tessdata"
    folder.mkdir(parents=True, exist_ok=True)
    # Pin a release; record downloaded hashes for provenance.
    base = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/"
    report = {}
    for lang in ("kor", "eng"):
        target = folder / f"{lang}.traineddata"
        if not target.exists():
            with urllib.request.urlopen(base + target.name, timeout=60) as response:
                data = response.read(25 * 1024 * 1024)
            if len(data) < 1000:
                raise ValueError("OCR 언어 파일 다운로드에 실패했습니다.")
            temp = target.with_suffix(".tmp")
            temp.write_bytes(data)
            temp.replace(target)
        report[lang] = {"url": base + target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    (folder / "sources.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("한국어·영어 OCR 언어 데이터 준비 완료")


if __name__ == "__main__":
    main()
