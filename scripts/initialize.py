"""Prepare local settings without printing passwords or overwriting existing values."""
from pathlib import Path
import re
import secrets
from src.config import PROJECT_ROOT


def main():
    path = PROJECT_ROOT / ".env"
    text = path.read_text(encoding="utf-8") if path.exists() else (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    if not re.search(r"^ADMIN_PASSWORD=.+$", text, re.MULTILINE):
        value = "ADMIN_PASSWORD=" + secrets.token_urlsafe(24)
        if re.search(r"^ADMIN_PASSWORD=\s*$", text, re.MULTILINE):
            text = re.sub(r"^ADMIN_PASSWORD=[ \t]*$", value, text, flags=re.MULTILINE)
        else:
            text += "\n" + value + "\n"
        path.write_text(text, encoding="utf-8")
    print("환경 설정 준비 완료. 관리자 비밀번호는 프로젝트 .env의 ADMIN_PASSWORD에서 확인하세요.")


if __name__ == "__main__":
    main()
