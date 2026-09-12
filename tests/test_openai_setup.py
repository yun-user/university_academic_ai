from dotenv import dotenv_values

from scripts import connect_openai as setup


def test_success_preserves_unrelated_settings_and_enables_app(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("# local\nADMIN_PASSWORD=keep-this\nLLM_ENABLED=false\nLLM_API_KEY=\nSEARCH_MODE=hybrid\n", encoding="utf-8")
    monkeypatch.setattr(setup, "connection_test", lambda key: None)
    assert setup.connect(tmp_path, "sk-" + "x" * 32) == ""
    values = dotenv_values(path)
    assert values["ADMIN_PASSWORD"] == "keep-this"
    assert values["SEARCH_MODE"] == "hybrid"
    assert values["LLM_ENABLED"] == "true"
    assert values["LLM_MODEL_NAME"] == "gpt-4.1-mini"
    assert values["LLM_BASE_URL"] == "https://api.openai.com/v1"
    assert values["LLM_API_KEY"] == "sk-" + "x" * 32
    assert not list(tmp_path.glob("*.tmp"))


def test_auth_error_never_echoes_key_or_changes_existing_settings(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("ADMIN_PASSWORD=keep\nLLM_ENABLED=false\n", encoding="utf-8")
    original = path.read_bytes()
    class AuthenticationError(Exception):
        status_code = 401
    def fail(key):
        raise AuthenticationError("bad credential " + key)
    monkeypatch.setattr(setup, "connection_test", fail)
    key = "sk-" + "y" * 32
    result = setup.connect(tmp_path, key)
    assert "인증 실패" in result
    assert key not in result
    assert path.read_bytes() == original


def test_key_cannot_inject_env_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "connection_test", lambda key: (_ for _ in ()).throw(AssertionError()))
    assert "형식" in setup.connect(tmp_path, "sk-" + "x" * 32 + "\nADMIN_PASSWORD=injected")
    assert not (tmp_path / ".env").exists()


def test_connection_probe_uses_application_prompt_and_validates_citation(monkeypatch):
    from src.answering.llm_answer_service import OpenAICompatibleProvider
    import json
    def generate(self, **kwargs):
        assert "테스트 문서" in kwargs["user_prompt"]
        return json.dumps({"claims": [{"quote": "테스트 문서는 도서관 안내 데스크에서 확인할 수 있습니다.",
                                       "evidence_id": "connection-test-1"}]})
    monkeypatch.setattr(OpenAICompatibleProvider, "generate", generate)
    setup.connection_test("sk-" + "x" * 32)


def test_console_key_is_not_echoed(monkeypatch, capsys):
    key = "sk-" + "z" * 32
    monkeypatch.setattr("getpass.getpass", lambda prompt: key)
    monkeypatch.setattr(setup, "connect", lambda root, secret: "" if secret == key else "bad")
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    setup.console_main()
    output = capsys.readouterr().out
    assert key not in output
    assert "연결 성공" in output
