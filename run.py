#!/usr/bin/env python3
"""Digonto local launcher.

One command from a fresh clone to a running product:

    python3 run.py

It checks prerequisites, installs both dependency trees, vendors the fonts,
generates the secrets that must not be shared between machines, applies database
migrations, seeds the judging accounts, and starts the API and the web client
together. Ctrl+C stops both.

Useful flags:
    --skip-install   do not touch pip or npm (fast restart)
    --skip-fonts     do not download webfonts
    --backend-only   run the API alone
    --frontend-only  run the web client alone
    --reset          delete local databases and re-seed from scratch
    --check          run every check and exit without starting anything
    --verbose-install show pip and npm output when an install fails
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENV_FILE = ROOT / ".env"
VENV = ROOT / ".venv"
FONT_DIR = FRONTEND / "public" / "fonts"

MIN_PYTHON = (3, 12)
# First version the pinned dependency set cannot install on. pydantic-core ships
# no wheel for it, and building from source fails because its bundled PyO3
# supports up to 3.13. Raise this once the pins are updated and verified.
NEXT_UNSUPPORTED_PYTHON = (3, 14)
MIN_NODE = 20

IS_WINDOWS = platform.system() == "Windows"


# --------------------------------------------------------------------------- ui
class C:
    G = "\033[32m"
    Y = "\033[33m"
    R = "\033[31m"
    B = "\033[34m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    X = "\033[0m"

    @classmethod
    def off(cls) -> None:
        for k in ("G", "Y", "R", "B", "DIM", "BOLD", "X"):
            setattr(cls, k, "")


if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    C.off()

_step = 0


def step(msg: str) -> None:
    global _step
    _step += 1
    print(f"\n{C.BOLD}{C.B}[{_step}]{C.X} {C.BOLD}{msg}{C.X}")


def ok(msg: str) -> None:
    print(f"  {C.G}OK{C.X}   {msg}")


def warn(msg: str) -> None:
    print(f"  {C.Y}WARN{C.X} {msg}")


def fail(msg: str, *, fatal: bool = True) -> None:
    print(f"  {C.R}FAIL{C.X} {msg}")
    if fatal:
        sys.exit(1)


def info(msg: str) -> None:
    print(f"  {C.DIM}{msg}{C.X}")


def run(cmd: list[str], *, cwd: Path | None = None, quiet: bool = True) -> int:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.STDOUT if quiet else None,
    )
    return proc.returncode


# ------------------------------------------------------------------ prereqs
def check_python() -> None:
    found = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.version_info < MIN_PYTHON:
        fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, found {found}")
    if sys.version_info >= NEXT_UNSUPPORTED_PYTHON:
        # Caught only by trying it: on 3.14 the pinned pydantic-core has no
        # prebuilt wheel, so pip falls back to building it, and its bundled PyO3
        # refuses to compile against an interpreter newer than 3.13. The failure
        # surfaced from deep inside a Rust build log, which is not a useful place
        # to learn that the interpreter is the problem, so it is checked here.
        supported = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} to " \
                    f"{NEXT_UNSUPPORTED_PYTHON[0]}.{NEXT_UNSUPPORTED_PYTHON[1] - 1}"
        fail(
            f"Python {found} is newer than this dependency set supports "
            f"(needs {supported}).\n"
            f"       Install one and point this script at it, for example:\n"
            f"       brew install python@3.12 && python3.12 run.py\n"
            f"       The deployed image pins python:3.12-slim, so production is "
            f"unaffected."
        )
    ok(f"Python {found}")


def check_node() -> None:
    if not shutil.which("node"):
        fail("Node.js not found. Install Node 20 or newer from https://nodejs.org")
    out = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()
    major = int(re.sub(r"[^0-9.]", "", out).split(".")[0] or 0)
    if major < MIN_NODE:
        fail(f"Node {MIN_NODE}+ required, found {out}")
    ok(f"Node {out}")
    if not shutil.which("npm"):
        fail("npm not found alongside Node")


def _http_ok(url: str, timeout: float = 2.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def check_services() -> dict[str, bool]:
    """Redis, Qdrant and Ollama. Only Ollama is required to answer questions."""
    state = {
        "redis": False,
        "qdrant": _http_ok("http://localhost:6333/readyz")
        or _http_ok("http://localhost:6333/"),
        "ollama": _http_ok("http://localhost:11434/api/tags"),
    }
    try:
        import socket

        with socket.create_connection(("localhost", 6379), timeout=1.5):
            state["redis"] = True
    except Exception:
        pass

    for name, up in state.items():
        if up:
            ok(f"{name} reachable")
        else:
            warn(f"{name} not reachable")

    if not state["ollama"]:
        info("Start it with:  ollama serve")
    if not state["redis"]:
        info("Start it with:  docker run -d -p 6379:6379 redis:7-alpine")
    if not state["qdrant"]:
        info("Start it with:  docker run -d -p 6333:6333 qdrant/qdrant")
    return state


def check_model(ollama_up: bool) -> None:
    if not ollama_up:
        warn("skipping model check, Ollama is not running")
        return
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            tags = json.load(r)
    except Exception as exc:
        warn(f"could not list models: {exc}")
        return

    names = [m.get("name", "") for m in tags.get("models", [])]
    wanted = "gemma4:e2b"
    if any(n.startswith(wanted) for n in names):
        ok(f"{wanted} present")
    else:
        warn(f"{wanted} not pulled. Run:  ollama pull {wanted}")
        return

    # The agents depend on native tool calling. Verify rather than assume: the
    # published model page has listed this incorrectly for the E variants.
    try:
        conn = http.client.HTTPConnection("localhost", 11434, timeout=10)
        conn.request(
            "POST", "/api/show", json.dumps({"model": wanted}), {"Content-Type": "application/json"}
        )
        show = json.loads(conn.getresponse().read())
        caps = show.get("capabilities", []) or []
        if "tools" in caps:
            ok(f"capabilities: {', '.join(caps)}")
        else:
            warn(f"{wanted} does not report tool support. Agents will not work.")
    except Exception:
        info("could not read model capabilities")

    if not any(n.startswith("bge-m3") for n in names):
        warn("embedding model missing. Run:  ollama pull bge-m3")


# ----------------------------------------------------------------------- env
def ensure_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        example = ROOT / ".env.example"
        if example.exists():
            shutil.copy(example, ENV_FILE)
            ok("created .env from .env.example")
        else:
            ENV_FILE.write_text("APP_ENV=development\n", encoding="utf-8")
            ok("created a minimal .env")

    text = ENV_FILE.read_text(encoding="utf-8")
    changed = False

    # Secrets must differ per machine. An empty value means "generate one".
    for key, gen in (
        ("JWT_SECRET", lambda: secrets.token_urlsafe(48)),
        ("VAULT_MASTER_KEY", lambda: secrets.token_urlsafe(32)),
    ):
        m = re.search(rf"^{key}=(.*)$", text, re.M)
        if m is None:
            text += f"\n{key}={gen()}\n"
            changed = True
        elif not m.group(1).strip():
            text = re.sub(rf"^{key}=.*$", f"{key}={gen()}", text, flags=re.M)
            changed = True

    if changed:
        ENV_FILE.write_text(text, encoding="utf-8")
        ok("generated missing local secrets in .env")
    else:
        ok(".env present with secrets set")

    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    for d in ("data/db", "data/vault", "data/snapshots"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    return env


# ------------------------------------------------------------------ installs
def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def install_backend(skip: bool, verbose: bool = False) -> Path:
    if not VENV.exists():
        step_msg = "creating virtual environment"
        info(step_msg)
        if run([sys.executable, "-m", "venv", str(VENV)]) != 0:
            fail("could not create .venv")
        ok("virtual environment created")

    py = venv_python()
    if not py.exists():
        fail(f"virtual environment looks broken, {py} missing")

    if skip:
        info("skipping pip install")
        return py

    info("installing Python dependencies (first run takes a minute)")
    pip_base = [str(py), "-m", "pip", "install"]
    quiet_flag = [] if verbose else ["--quiet"]
    run(pip_base + ["--upgrade", "pip"] + quiet_flag, quiet=not verbose)
    rc = run(
        pip_base + ["-r", str(BACKEND / "requirements.txt")] + quiet_flag,
        quiet=not verbose,
    )
    if rc != 0:
        fail("pip install failed. Re-run with --verbose-install to see why")
    ok("Python dependencies installed")
    return py


def install_frontend(skip: bool) -> None:
    if skip:
        info("skipping npm install")
        return
    if not (FRONTEND / "package.json").exists():
        fail("frontend/package.json missing")
    info("installing web dependencies")
    lock = FRONTEND / "package-lock.json"
    cmd = ["npm", "ci"] if lock.exists() else ["npm", "install"]
    rc = run(cmd, cwd=FRONTEND)
    if rc != 0 and cmd[1] == "ci":
        info("npm ci failed, falling back to npm install")
        rc = run(["npm", "install"], cwd=FRONTEND)
    if rc != 0:
        fail("npm install failed")
    ok("web dependencies installed")


# ------------------------------------------------------------------- fonts
# The design brief forbids loading fonts from a CDN at runtime: users are on
# mid-range Android over slow connections, and a third-party font request is
# both a latency cost and a privacy leak. These are vendored instead.
FONT_FAMILIES = {
    "Fraunces": [400, 500, 600, 700],
    "Space Grotesk": [400, 500, 600, 700],
    "JetBrains Mono": [400, 500, 600],
    "Noto Serif Bengali": [400, 500, 600, 700],
    "Hind Siliguri": [300, 400, 500, 600, 700],
}
GWFH = "https://gwfh.mranftl.com/api/fonts"


def slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def download_fonts(skip: bool) -> None:
    if skip:
        info("skipping font download")
        return

    FONT_DIR.mkdir(parents=True, exist_ok=True)
    expected = sum(len(w) for w in FONT_FAMILIES.values())
    present = len(list(FONT_DIR.glob("*.woff2")))
    if present >= expected:
        ok(f"fonts already vendored ({present} files)")
        return

    info(f"downloading {expected} webfont files")
    got, missed = 0, []
    for family, weights in FONT_FAMILIES.items():
        fam = slug(family)
        try:
            url = f"{GWFH}/{fam}?subsets=latin,bengali" if "Bengali" in family or "Hind" in family else f"{GWFH}/{fam}?subsets=latin"
            with urllib.request.urlopen(url, timeout=20) as r:
                meta = json.load(r)
        except Exception as exc:
            missed.append(f"{family} ({exc})")
            continue

        variants = {str(v.get("fontWeight")): v for v in meta.get("variants", [])
                    if v.get("fontStyle") == "normal"}
        for w in weights:
            target = FONT_DIR / f"{fam}-{w}.woff2"
            if target.exists():
                got += 1
                continue
            v = variants.get(str(w))
            link = (v or {}).get("woff2")
            if not link:
                missed.append(f"{family} {w}")
                continue
            try:
                with urllib.request.urlopen(link, timeout=30) as resp:
                    target.write_bytes(resp.read())
                got += 1
            except Exception as exc:
                missed.append(f"{family} {w} ({exc})")

    if got:
        ok(f"vendored {got} font files into frontend/public/fonts")
    if missed:
        warn(f"{len(missed)} font files could not be downloaded")
        for m in missed[:6]:
            info(m)
        info("The site still runs; it falls back to system fonts for those weights.")


# -------------------------------------------------------------------- serve
class Runner:
    def __init__(self) -> None:
        self.procs: list[tuple[str, subprocess.Popen]] = []

    def spawn(self, name: str, cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
        merged = {**os.environ, **(env or {})}
        p = subprocess.Popen(cmd, cwd=cwd, env=merged)
        self.procs.append((name, p))
        ok(f"{name} started (pid {p.pid})")

    def wait(self) -> None:
        try:
            while True:
                for name, p in self.procs:
                    code = p.poll()
                    if code is not None:
                        print(f"\n{C.R}{name} exited with code {code}{C.X}")
                        self.stop()
                        sys.exit(code or 1)
                time.sleep(0.4)
        except KeyboardInterrupt:
            print("\nshutting down")
            self.stop()

    def stop(self) -> None:
        for name, p in reversed(self.procs):
            if p.poll() is None:
                try:
                    if IS_WINDOWS:
                        p.terminate()
                    else:
                        os.kill(p.pid, signal.SIGTERM)
                    p.wait(timeout=8)
                except Exception:
                    p.kill()
                print(f"  stopped {name}")


def banner(env: dict[str, str]) -> None:
    fe = env.get("FRONTEND_PORT", "5173")
    be = env.get("BACKEND_PORT", "8000")
    judge_e = env.get("SEED_JUDGE_EMAIL", "judge@digonto.ahbab.dev")
    judge_p = env.get("SEED_JUDGE_PASSWORD", "(see .env)")
    mod_e = env.get("SEED_MODERATOR_EMAIL", "moderator@digonto.ahbab.dev")
    mod_p = env.get("SEED_MODERATOR_PASSWORD", "(see .env)")
    print(
        f"""
{C.BOLD}  Digonto is running{C.X}

  Web app    {C.B}http://localhost:{fe}{C.X}
  API docs   {C.B}http://localhost:{be}/docs{C.X}
  Health     {C.B}http://localhost:{be}/readyz{C.X}

{C.BOLD}  Sign in{C.X}
  Student    {judge_e}  /  {judge_p}
  Moderator  {mod_e}  /  {mod_p}

  {C.DIM}Ctrl+C stops both processes.{C.X}
"""
    )


def reset_data() -> None:
    db_dir = ROOT / "data" / "db"
    if db_dir.exists():
        for f in db_dir.glob("*.db*"):
            f.unlink()
        ok("local databases deleted, they will be rebuilt and re-seeded")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Digonto locally")
    ap.add_argument("--skip-install", action="store_true")
    ap.add_argument("--skip-fonts", action="store_true")
    ap.add_argument("--backend-only", action="store_true")
    ap.add_argument("--frontend-only", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument(
        "--verbose-install",
        action="store_true",
        help="show pip and npm output instead of hiding it, for diagnosing a "
             "failed dependency install",
    )
    args = ap.parse_args()

    print(f"{C.BOLD}Digonto{C.X} {C.DIM}local launcher{C.X}")

    step("Checking prerequisites")
    check_python()
    if not args.backend_only:
        check_node()

    step("Checking services")
    services = check_services()
    check_model(services["ollama"])

    step("Preparing environment")
    env = ensure_env()
    if args.reset:
        reset_data()

    step("Installing dependencies")
    py = (install_backend(args.skip_install, args.verbose_install)
           if not args.frontend_only else venv_python())
    if not args.backend_only:
        install_frontend(args.skip_install)

    step("Vendoring fonts")
    if args.backend_only:
        info("skipped, backend only")
    else:
        download_fonts(args.skip_fonts)

    if args.check:
        print(f"\n{C.G}All checks complete.{C.X} Nothing was started (--check).")
        return

    step("Starting")
    r = Runner()
    if not args.frontend_only:
        # Migrations and seeding run inside the API lifespan, so there is one
        # code path for local and container startup rather than two.
        r.spawn(
            "api",
            [
                str(py), "-m", "uvicorn", "app.main:app",
                "--host", env.get("BACKEND_HOST", "127.0.0.1"),
                "--port", env.get("BACKEND_PORT", "8000"),
                "--reload",
            ],
            cwd=BACKEND,
        )
    if not args.backend_only:
        r.spawn(
            "web",
            ["npm", "run", "dev", "--", "--port", env.get("FRONTEND_PORT", "5173")],
            cwd=FRONTEND,
            env={"VITE_API_BASE": f"http://localhost:{env.get('BACKEND_PORT','8000')}/api/v1"},
        )

    time.sleep(2.0)
    banner(env)
    r.wait()


if __name__ == "__main__":
    main()
