"""Local, masked API-key entry and a real citation-format connection test."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import webbrowser

from filelock import FileLock

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gpt-4.1-mini"
ENDPOINT = "https://api.openai.com/v1"


def connection_test(key: str) -> None:
    from src.answering.llm_answer_service import OpenAICompatibleProvider, _parse_grounded_completion
    from src.answering.prompts import SYSTEM_PROMPT, build_user_prompt
    from src.retrieval.document_models import DocumentSearchResult

    # Synthetic evidence only: this is not a university regulation.
    text = "연결 시험용 안내: 테스트 문서는 도서관 안내 데스크에서 확인할 수 있습니다."
    evidence = DocumentSearchResult(
        document_id="connection-test", chunk_id="connection-test-1",
        file_name="연결시험.txt", file_type="txt", document_type="안내",
        department="전체", title="연결 시험", source_path="connection-test.txt",
        text=text, score=0.9, content_hash=hashlib.sha256(text.encode()).hexdigest(),
        source_year="2026", is_current=True,
    )
    provider = OpenAICompatibleProvider(api_key=key, model_name=MODEL, base_url=ENDPOINT)
    raw = provider.generate(system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt("테스트 문서는 어디에서 확인할 수 있나요?", [evidence]),
        timeout_seconds=30)
    _, cited = _parse_grounded_completion(raw, [evidence])
    if "connection-test-1" not in cited:
        raise ValueError("Missing test citation")


def save_settings(root: Path, key: str) -> None:
    updates = dict(LLM_ENABLED="true", LLM_PROVIDER="openai", LLM_MODEL_NAME=MODEL,
        LLM_BASE_URL=ENDPOINT, LLM_API_KEY=key, LLM_TIMEOUT_SECONDS="60")
    with FileLock(str(root / ".openai-setup.lock"), timeout=5):
        path = root / ".env"
        original = path if path.exists() else root / ".env.example"
        text = original.read_text(encoding="utf-8-sig")
        for name, value in updates.items():
            pattern = re.compile(r"^(?:export[ \t]+)?" + name + r"[ \t]*=.*$", re.MULTILINE)
            line = name + "=" + value
            if pattern.search(text):
                text = pattern.sub(lambda _: line, text)
            else:
                text = text.rstrip("\n") + "\n" + line + "\n"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root,
                    prefix=".openai-setup-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(text)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def connect(root: Path, key: str) -> str:
    key = key.strip()
    if not re.fullmatch(r"sk-[A-Za-z0-9_-]{16,}", key):
        return "API 키 형식을 확인하세요. OpenAI에서 발급한 sk-로 시작하는 키를 입력하세요."
    try:
        connection_test(key)
    except Exception as exc:
        # Never display provider exception bodies: they may contain credentials.
        status = getattr(exc, "status_code", None)
        if status == 401:
            return "인증 실패: API 키가 올바른지 또는 폐기되었는지 확인하세요."
        if status == 429:
            return "사용 한도 오류: OpenAI API 결제 잔액·사용 한도를 확인하고 잠시 후 재시도하세요."
        if status in {403, 404}:
            return "모델 접근 실패: API 프로젝트에 gpt-4.1-mini 사용 권한이 있는지 확인하세요."
        if isinstance(exc, ValueError):
            return "API 응답을 받았지만 출처 검증을 통과하지 못했습니다. 다시 시도하세요."
        return "연결 실패: 인터넷·방화벽 또는 OpenAI 서비스 상태를 확인하고 다시 시도하세요."
    try:
        save_settings(root, key)
    except Exception:
        return "연결은 성공했지만 설정 저장에 실패했습니다. 프로젝트 폴더의 쓰기 권한을 확인하세요."
    return ""


def console_main() -> None:
    import getpass
    import warnings
    print("\nOpenAI 연결 설정 (gpt-4.1-mini)")
    print("API 키는 화면에 표시되지 않으며 이 PC의 .env에 저장합니다.")
    print("연결 시험은 유료 API 요청 1회입니다. ChatGPT 구독과 API 결제는 별도입니다.")
    print("키 발급: https://platform.openai.com/api-keys")
    print("키를 채팅에 보내지 마세요. 이 창에 붙여넣고 Enter를 누르세요.")
    while True:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                key = getpass.getpass("API 키 (입력 내용은 보이지 않음, 종료: Ctrl+C): ")
        except (EOFError, KeyboardInterrupt):
            print("\n설정을 취소했습니다.")
            return
        except getpass.GetPassWarning:
            print("보호된 키 입력을 사용할 수 없습니다. connect_openai.cmd를 직접 실행하세요.")
            return
        print("실제 API 응답과 출처 형식을 확인하는 중입니다…")
        error = connect(ROOT, key)
        key = ""
        if error:
            print(error + "\n설정은 변경하지 않았습니다.")
        else:
            print("연결 성공! API 응답과 출처 검증을 통과했고 설정을 저장했습니다.")
            print("실행 중인 프로그램을 Ctrl+C로 종료한 뒤 start.cmd를 다시 실행하세요.")
            input("Enter를 누르면 이 창을 닫습니다.")
            return


def main() -> None:
    import tkinter as tk
    from tkinter import ttk

    try:
        window = tk.Tk()
    except tk.TclError:
        console_main()
        return
    window.title("대학 학사정보 AI — OpenAI 연결")
    window.geometry("650x440")
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="OpenAI 연결", font=("맑은 고딕", 18, "bold")).pack(anchor="w")
    ttk.Label(frame, text="모델: gpt-4.1-mini · 키는 이 PC의 프로그램 .env에 저장됩니다.\n"
        "테스트는 짧은 OpenAI API 요청 1회를 보내며 API 이용료가 발생합니다.\n"
        "ChatGPT 구독과 별도로 API 결제 설정이 필요합니다.", wraplength=590).pack(anchor="w", pady=12)
    links = ttk.Frame(frame)
    links.pack(anchor="w")
    ttk.Button(links, text="API 키 발급 페이지", command=lambda: webbrowser.open(
        "https://platform.openai.com/api-keys")).pack(side="left")
    ttk.Button(links, text="API 결제 설정", command=lambda: webbrowser.open(
        "https://platform.openai.com/settings/organization/billing/overview")).pack(side="left", padx=8)
    ttk.Label(frame, text="API 키 (채팅에 보내지 말고 아래에 붙여넣으세요)").pack(anchor="w", pady=(20, 5))
    key_value = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=key_value, show="*", width=75)
    entry.pack(fill="x")
    status = tk.StringVar(value="키를 입력한 후 아래 버튼을 누르면 연결 시험과 설정 저장을 진행합니다.")
    events: queue.Queue[str] = queue.Queue()
    busy = False

    def start():
        nonlocal busy
        secret = key_value.get()
        key_value.set("")
        busy = True
        entry.configure(state="disabled")
        button.configure(state="disabled")
        status.set("OpenAI 응답과 출처 형식을 확인 중입니다. 최대 30초 정도 걸립니다…")
        threading.Thread(target=lambda: events.put(connect(ROOT, secret)), daemon=True).start()

    def poll():
        nonlocal busy
        try:
            error = events.get_nowait()
        except queue.Empty:
            pass
        else:
            busy = False
            if error:
                status.set(error + "\n설정은 변경하지 않았습니다.")
                entry.configure(state="normal")
                button.configure(state="normal")
                entry.focus_set()
            else:
                status.set("연결 성공! 실제 API 응답과 출처 검증을 통과했고 설정을 저장했습니다.\n"
                    "실행 중인 프로그램 창에서 Ctrl+C로 종료한 뒤 start.cmd를 다시 실행하세요.")
                button.configure(text="연결 완료")
        window.after(100, poll)

    button = ttk.Button(frame, text="연결 테스트 후 저장", command=start)
    button.pack(anchor="w", pady=15)
    ttk.Label(frame, textvariable=status, wraplength=590).pack(anchor="w")
    window.protocol("WM_DELETE_WINDOW", lambda: None if busy else window.destroy())
    entry.focus_set()
    window.after(100, poll)
    window.mainloop()


if __name__ == "__main__":
    main()
