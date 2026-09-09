"""
Local development runner for LLM Evaluator.
Starts both the API server (FastAPI via Uvicorn) and the background Worker
concurrently in a single terminal, handling graceful shutdown on Ctrl+C.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

DEFAULT_ENV_CONTENT = """# Local development defaults (SQLite + 100% sampling + Mock LLM)
DATABASE_URL=sqlite+aiosqlite:///./evaluator.db
SAMPLE_RATE=1.0
WORKER_POLL_SECONDS=1
LOG_LEVEL=INFO

PRIMARY_PROVIDER=mock
PRIMARY_MODEL=primary-mock

CANDIDATE_PROVIDER=mock
CANDIDATE_MODEL=candidate-mock

SCORE_BACKEND=heuristic
QUEUE_BACKEND=database
"""


def ensure_env_file() -> None:
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        print("[run.py] No .env found. Creating .env with local development defaults...")
        env_path.write_text(DEFAULT_ENV_CONTENT, encoding="utf-8")
        print("[run.py] Created .env (SQLite database, 100% sampling, mock models).")


def print_banner(host: str, port: int) -> None:
    border = "=" * 64
    print(border)
    print("  🚀 LLM Evaluator - Local Development Runner")
    print(border)
    print(f"  • Web Dashboard : http://{host}:{port}")
    print(f"  • Swagger Docs  : http://{host}:{port}/docs")
    print(f"  • Architecture  : FastAPI (API) + Async Background Worker")
    print(f"  • Stop          : Press Ctrl+C to terminate both")
    print(border)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run LLM Evaluator (API + Worker)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="API host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="API port (default: 8000)"
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for API"
    )
    args = parser.parse_args()

    ensure_env_file()
    print_banner(args.host, args.port)

    api_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.reload:
        api_cmd.append("--reload")

    worker_cmd = [sys.executable, "-m", "app.worker"]

    procs: list[subprocess.Popen] = []
    try:
        # Start API server
        api_proc = subprocess.Popen(api_cmd, cwd=ROOT_DIR)
        procs.append(api_proc)

        # Brief delay to allow initial schema creation by API lifespan
        time.sleep(0.6)

        # Start background worker
        worker_proc = subprocess.Popen(worker_cmd, cwd=ROOT_DIR)
        procs.append(worker_proc)

        # Monitor both processes
        while True:
            for p in procs:
                ret = p.poll()
                if ret is not None:
                    print(f"\n[run.py] Process {p.args} exited with code {ret}")
                    return ret
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[run.py] Stopping API and Worker processes...")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        time.sleep(1.0)
        for p in procs:
            if p.poll() is None:
                p.kill()
        print("[run.py] All processes stopped cleanly. Goodbye!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
