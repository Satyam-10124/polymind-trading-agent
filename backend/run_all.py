"""
Single-entrypoint supervisor for the PolyMind backend.

Render (and most single-process PaaS services) run ONE start command, but the
backend is two long-lived processes that share one SQLite file:

  1. the FastAPI server (uvicorn) — serves the dashboard API, and
  2. the scheduler/bot loop (main.py) — whale scans, position checks, Telegram.

This launches both as child processes and ties their lifecycles together: if
either exits, the other is terminated and the supervisor exits non-zero so the
platform restarts the whole service cleanly. SQLite WAL mode (set per-connection
in db.models) makes the shared-file access safe across the two processes.

Locally you can still run them separately:
    uvicorn api:app --port 8000      # API only
    python main.py                   # scheduler only
"""
import os
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = os.getenv("PORT", "8000")  # Render injects PORT; default for local use.


def main():
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app",
         "--host", "0.0.0.0", "--port", PORT],
        cwd=HERE,
    )
    scheduler = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=HERE,
    )
    procs = {"api": api, "scheduler": scheduler}

    def shutdown(*_):
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
        sys.exit(1)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Block until either child exits, then take the whole service down so the
    # platform restarts it — we never want to run half the system silently.
    while True:
        for name, p in procs.items():
            code = p.poll()
            if code is not None:
                print(f"[run_all] '{name}' exited with code {code} — "
                      f"shutting down the service.", flush=True)
                shutdown()
        try:
            api.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


if __name__ == "__main__":
    main()
