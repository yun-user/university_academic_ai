"""Start the local web app, or open a healthy instance that already owns port 8000."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8000"


def read_json(path):
    # Loopback checks must not use a configured external HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(URL + path, timeout=1) as response:
        return json.loads(response.read(1_000_000))


def running_planner():
    try:
        health = read_json("/api/health")
        if not isinstance(health, dict) or health.get("status") != "ok" or health.get("storage") != "sqlite":
            return False
        schema = read_json("/openapi.json")
        info = schema.get("info") if isinstance(schema, dict) else None
        return isinstance(info, dict) and info.get("title") == "졸업 로드맵 API"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def port_in_use():
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            return True
    except OSError:
        return False


def open_browser():
    print(f"Open {URL} in your browser.", flush=True)
    if os.environ.get("PLANNER_NO_BROWSER") == "1":
        return
    try:
        if not webbrowser.open(URL):
            print("The browser did not open automatically. Use the address above.", flush=True)
    except (webbrowser.Error, OSError):
        print("The browser did not open automatically. Use the address above.", flush=True)


def stop_child(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    if running_planner():
        print("PATH is already running. Opening the existing app; no second server is started.", flush=True)
        print("This uses the data of the running app, even if started from another folder.", flush=True)
        open_browser()
        return 0
    if port_in_use():
        print("Port 8000 is occupied, but a healthy PATH app was not found.", flush=True)
        print("Wait for startup to finish, or close the other program and retry.", flush=True)
        return 1
    if not (ROOT / "frontend/dist/index.html").is_file():
        print("The frontend build is missing. Run setup_web.cmd in this folder first.", flush=True)
        return 1
    if importlib.util.find_spec("uvicorn") is None:
        print("Web dependencies are missing. Run setup_web.cmd in this folder first.", flush=True)
        return 1

    print("Starting PATH. Keep this window open; press Ctrl+C to stop the server.", flush=True)
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app",
                                "--host", "127.0.0.1", "--port", "8000", "--no-access-log"], cwd=ROOT)
    try:
        deadline = time.monotonic() + 30
        while process.poll() is None:
            if running_planner():
                open_browser()
                return process.wait()
            if time.monotonic() >= deadline:
                print("PATH did not become ready within 30 seconds. Check the startup error above.", flush=True)
                return 1
            time.sleep(0.25)
        # Another simultaneous double-click may have started the same app first.
        if running_planner():
            open_browser()
            return 0
        print(f"PATH stopped during startup (exit code {process.returncode}).", flush=True)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        stop_child(process)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"PATH launcher error: {exc}", file=sys.stderr)
        raise SystemExit(1)
