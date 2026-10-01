"""Prepare local settings without printing passwords or overwriting existing values."""
from io import StringIO
import secrets
from dotenv import dotenv_values, set_key
from src.config import PROJECT_ROOT


def main():
    path = PROJECT_ROOT / ".env"
    text = path.read_text(encoding="utf-8-sig") if path.exists() else (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8-sig")
    if not path.exists():
        path.write_text(text, encoding="utf-8")
    if not (dotenv_values(stream=StringIO(text)).get("ADMIN_PASSWORD") or "").strip():
        # Parse the same syntax as runtime: quotes, export, whitespace and comments.
        set_key(path, "ADMIN_PASSWORD", secrets.token_urlsafe(24))
    print("환경 설정 준비 완료. 관리자 비밀번호는 프로젝트 .env의 ADMIN_PASSWORD에서 확인하세요.")


if __name__ == "__main__":
    main()
