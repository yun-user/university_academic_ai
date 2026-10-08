"""Launch behavior without browser side effects or access to student data."""
import os
from pathlib import Path
import subprocess

import pytest

from scripts import start_web as launcher


@pytest.mark.parametrize("health,schema,expected", [
    ({"status": "ok", "storage": "sqlite"}, {"info": {"title": "졸업 로드맵 API"}}, True),
    ({"status": "ok", "storage": "sqlite"}, {"info": {"title": "Other app"}}, False),
    ({"status": "ok", "storage": "sqlite"}, {"info": None}, False),
    ({"status": "ok", "storage": "sqlite"}, [], False),
    ({"status": "starting", "storage": "sqlite"}, {}, False),
    ([], {}, False),
])
def test_only_healthy_path_is_reused(monkeypatch, health, schema, expected):
    monkeypatch.setattr(launcher, "read_json", lambda path: health if path == "/api/health" else schema)
    assert launcher.running_planner() is expected


def test_existing_instance_opens_without_spawning(monkeypatch):
    opened = []
    monkeypatch.setattr(launcher, "running_planner", lambda: True)
    monkeypatch.setattr(launcher, "open_browser", lambda: opened.append(True))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: pytest.fail("Second server started"))
    assert launcher.main() == 0 and opened == [True]


def test_other_service_on_port_is_not_opened_or_stopped(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "running_planner", lambda: False)
    monkeypatch.setattr(launcher, "port_in_use", lambda: True)
    monkeypatch.setattr(launcher, "open_browser", lambda: pytest.fail("Opened another app"))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: pytest.fail("Spawned on occupied port"))
    assert launcher.main() == 1
    assert "Port 8000 is occupied" in capsys.readouterr().out


class Child:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15


@pytest.fixture
def fresh_launch(tmp_path, monkeypatch):
    (tmp_path / "frontend/dist").mkdir(parents=True)
    (tmp_path / "frontend/dist/index.html").write_text("synthetic")
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "port_in_use", lambda: False)
    monkeypatch.setattr(launcher.importlib.util, "find_spec", lambda name: True)
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)
    return tmp_path


def test_new_server_opens_only_when_healthy(fresh_launch, monkeypatch):
    probes, opened = [], []
    child = Child()
    def probe():
        probes.append(True)
        return len(probes) == 3
    monkeypatch.setattr(launcher, "running_planner", probe)
    monkeypatch.setattr(launcher, "open_browser", lambda: opened.append(len(probes)))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, cwd: child)
    assert launcher.main() == 0 and opened == [3]
    assert not child.terminated


def test_timeout_stops_only_own_child(fresh_launch, monkeypatch):
    child = Child()
    clock = iter([0, 31])
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(launcher, "running_planner", lambda: False)
    monkeypatch.setattr(launcher, "open_browser", lambda: pytest.fail("Opened before ready"))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, cwd: child)
    assert launcher.main() == 1 and child.terminated


def test_failed_server_keeps_error_status(fresh_launch, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "running_planner", lambda: False)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, cwd: Child(1))
    assert launcher.main() == 1
    assert "exit code 1" in capsys.readouterr().out


@pytest.mark.skipif(os.name != "nt", reason="Windows double-click wrapper")
def test_missing_environment_returns_visible_setup_help(tmp_path):
    root = Path(__file__).resolve().parents[2]
    folder = tmp_path / "path with spaces"
    folder.mkdir()
    (folder / "start_web.cmd").write_bytes((root / "start_web.cmd").read_bytes())
    result = subprocess.run(["cmd.exe", "/d", "/c", "start_web.cmd"], cwd=folder,
                            env={**os.environ, "PLANNER_NO_PAUSE": "1"}, capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 1
    assert "Python environment is missing" in result.stdout
    assert "setup_web.cmd" in result.stdout
