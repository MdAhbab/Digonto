#!/usr/bin/env python3
"""Digonto cloud deployment.

Takes a fresh Ubuntu 22.04 or 24.04 virtual machine to a running, TLS-secured
deployment at https://<domain>. Run it as root, or as a user with sudo, on the
VM itself:

    sudo python3 run_onVM.py --domain digonto.ahbab.dev --email you@example.com

What it does, in order:
  1. Verifies the machine can actually host this (RAM, disk, architecture) and
     that DNS for the domain already points at this machine.
  2. Installs Docker Engine and the Compose plugin from Docker's own apt
     repository, not the distribution's older packages.
  3. Installs and configures nginx as the public entry point.
  4. Obtains a Let's Encrypt certificate with certbot and installs a renewal
     timer.
  5. Writes the production .env, generating strong secrets, and refuses to reuse
     development values.
  6. Builds and starts the stack, pulls the model, and waits for health.
  7. Applies a basic firewall and unattended security updates.

It is idempotent. Running it twice is safe and is the intended way to redeploy.

Flags:
    --domain            required, the public hostname
    --email             required, for Let's Encrypt expiry notices
    --skip-tls          set up HTTP only, useful before DNS has propagated
    --skip-model-pull   do not pull the model (it is large)
    --update            redeploy code only: rebuild, restart, skip provisioning
    --dry-run           print every command without running it
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
COMPOSE_FILE = APP_DIR / "docker-compose.prod.yml"
ENV_FILE = APP_DIR / ".env.production"

MIN_RAM_GB = 8
MIN_DISK_GB = 40
DRY_RUN = False
MIN_PYTHON = (3, 10)
NEXT_UNSUPPORTED_PYTHON = (3, 16)


class C:
    G, Y, R, B, DIM, BOLD, X = (
        "\033[32m", "\033[33m", "\033[31m", "\033[34m", "\033[2m", "\033[1m", "\033[0m"
    )


if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    C.G = C.Y = C.R = C.B = C.DIM = C.BOLD = C.X = ""

_n = 0


def step(msg: str) -> None:
    global _n
    _n += 1
    print(f"\n{C.BOLD}{C.B}[{_n}]{C.X} {C.BOLD}{msg}{C.X}")


def ok(m: str) -> None:
    print(f"  {C.G}OK{C.X}   {m}")


def warn(m: str) -> None:
    print(f"  {C.Y}WARN{C.X} {m}")


def die(m: str) -> None:
    print(f"  {C.R}FAIL{C.X} {m}")
    sys.exit(1)


def info(m: str) -> None:
    print(f"  {C.DIM}{m}{C.X}")


def sh(cmd: str, *, check: bool = True, quiet: bool = True) -> int:
    if DRY_RUN:
        print(f"  {C.DIM}$ {cmd}{C.X}")
        return 0
    r = subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.STDOUT if quiet else None,
    )
    if check and r.returncode != 0:
        die(f"command failed: {cmd}")
    return r.returncode


def sh_out(cmd: str) -> str:
    if DRY_RUN:
        return ""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


# ------------------------------------------------------------------- checks
def require_root() -> None:
    if DRY_RUN:
        return
    if os.geteuid() != 0:
        die("run as root:  sudo python3 run_onVM.py --domain ... --email ...")
    ok("running as root")


def check_python() -> None:
    found = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.version_info < MIN_PYTHON:
        die(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, found {found}")
    if sys.version_info >= NEXT_UNSUPPORTED_PYTHON:
        supported = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} to " \
                    f"{NEXT_UNSUPPORTED_PYTHON[0]}.{NEXT_UNSUPPORTED_PYTHON[1] - 1}"
        die(
            f"Python {found} is newer than this dependency set supports "
            f"(needs {supported})."
        )
    ok(f"Python {found}")


def check_machine() -> None:
    check_python()
    if platform.system() != "Linux":
        die("this script provisions a Linux VM; run it on the server, not your laptop")

    arch = platform.machine()
    if arch not in ("x86_64", "aarch64"):
        die(f"unsupported architecture {arch}")

    try:
        with open("/proc/meminfo") as f:
            kb = int(next(l for l in f if l.startswith("MemTotal")).split()[1])
        ram_gb = kb / 1024 / 1024
    except Exception:
        ram_gb = 0.0

    if ram_gb and ram_gb < MIN_RAM_GB:
        warn(f"{ram_gb:.1f} GB RAM. The model needs roughly 8 GB resident.")
        info("The stack will start but generation may be killed by the OOM killer.")
    else:
        ok(f"{ram_gb:.1f} GB RAM")

    free_gb = shutil.disk_usage("/").free / 1024**3
    if free_gb < MIN_DISK_GB:
        die(f"{free_gb:.0f} GB free disk, need at least {MIN_DISK_GB} GB for images and the model")
    ok(f"{free_gb:.0f} GB free disk")

    if not (APP_DIR / "backend").exists() or not (APP_DIR / "frontend").exists():
        die(f"run this from the project root; {APP_DIR} has no backend/ and frontend/")


def check_dns(domain: str, skip_tls: bool) -> None:
    """Certbot fails confusingly when DNS is wrong. Catch it here instead."""
    try:
        resolved = socket.gethostbyname(domain)
    except socket.gaierror:
        if skip_tls:
            warn(f"{domain} does not resolve yet; continuing because --skip-tls")
            return
        die(f"{domain} does not resolve. Point an A record at this server first.")

    public_ip = ""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                public_ip = r.read().decode().strip()
                break
        except Exception:
            continue

    if not public_ip:
        warn(f"{domain} resolves to {resolved}; could not determine this server's public IP")
        return
    if resolved != public_ip:
        msg = f"{domain} resolves to {resolved} but this server is {public_ip}"
        if skip_tls:
            warn(msg)
        else:
            die(msg + ". Fix DNS, or re-run with --skip-tls.")
    else:
        ok(f"{domain} resolves to this server ({public_ip})")


# ------------------------------------------------------------------ install
def install_base() -> None:
    sh("export DEBIAN_FRONTEND=noninteractive; apt-get update -y")
    sh(
        "export DEBIAN_FRONTEND=noninteractive; apt-get install -y "
        "ca-certificates curl gnupg lsb-release ufw fail2ban "
        "unattended-upgrades python3-venv git"
    )
    ok("base packages installed")


def install_docker() -> None:
    if shutil.which("docker") and "Compose" in sh_out("docker compose version"):
        ok("Docker and the Compose plugin already installed")
        return
    # Docker's own repository, because distribution packages lag badly and the
    # compose plugin is often missing entirely.
    sh("install -m 0755 -d /etc/apt/keyrings")
    sh(
        "curl -fsSL https://download.docker.com/linux/ubuntu/gpg "
        "| gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes"
    )
    sh("chmod a+r /etc/apt/keyrings/docker.gpg")
    sh(
        'echo "deb [arch=$(dpkg --print-architecture) '
        'signed-by=/etc/apt/keyrings/docker.gpg] '
        'https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" '
        "> /etc/apt/sources.list.d/docker.list"
    )
    sh("apt-get update -y")
    sh(
        "export DEBIAN_FRONTEND=noninteractive; apt-get install -y docker-ce docker-ce-cli "
        "containerd.io docker-buildx-plugin docker-compose-plugin"
    )
    sh("systemctl enable --now docker")
    ok("Docker installed")


# ---------------------------------------------------------------------- env
def write_env(domain: str) -> None:
    if ENV_FILE.exists():
        text = ENV_FILE.read_text()
        if "change-me" in text or "JWT_SECRET=\n" in text:
            warn(".env.production has unset values, regenerating secrets")
        else:
            ok(".env.production already present, leaving it alone")
            return

    body = textwrap.dedent(
        f"""\
        # Generated by run_onVM.py. Do not commit. Do not reuse elsewhere.
        APP_ENV=production
        APP_NAME=Digonto
        API_BASE_PATH=/api/v1
        PUBLIC_BASE_URL=https://{domain}
        BACKEND_HOST=0.0.0.0
        BACKEND_PORT=8000

        JWT_SECRET={secrets.token_urlsafe(48)}
        JWT_ACCESS_TTL_SECONDS=900
        JWT_REFRESH_TTL_DAYS=30
        VAULT_MASTER_KEY={secrets.token_urlsafe(32)}

        DB_DIR=/data/db
        VAULT_DIR=/data/vault
        SNAPSHOT_DIR=/data/snapshots
        REDIS_URL=redis://redis:6379/0
        QDRANT_URL=http://qdrant:6333

        OLLAMA_BASE_URL=http://ollama:11434
        GEMMA_MODEL=gemma4:e2b
        EMBED_MODEL=bge-m3
        OLLAMA_KEEP_ALIVE=30m

        SEED_DEMO_DATA=false
        """
    )
    ENV_FILE.write_text(body)
    os.chmod(ENV_FILE, 0o600)
    ok("wrote .env.production with fresh secrets (mode 600)")
    warn("Add any model provider key to .env.production by hand; it is not stored in git.")


# ------------------------------------------------------------------- nginx
NGINX_TEMPLATE = """\
# Digonto. Managed by run_onVM.py; hand edits are overwritten on redeploy.

limit_req_zone $binary_remote_addr zone=digonto_api:10m rate=10r/s;

upstream digonto_api {{
    server 127.0.0.1:8000;
    keepalive 32;
}}

server {{
    listen 80;
    listen [::]:80;
    server_name {domain};

    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}
    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name {domain};

    ssl_certificate     /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_stapling on;
    ssl_stapling_verify on;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), geolocation=(), microphone=(self)" always;

    client_max_body_size 25m;

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css application/javascript application/json
               image/svg+xml application/xml;

    # Streaming endpoints. Buffering here would hold tokens back and make the
    # answer appear all at once, which defeats the point of streaming.
    location ~ ^/api/v1/(ask|stream)$ {{
        proxy_pass http://digonto_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;
        proxy_read_timeout 3600s;
    }}

    location /api/v1/interview/ {{
        proxy_pass http://digonto_api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;
    }}

    location /api/ {{
        limit_req zone=digonto_api burst=20 nodelay;
        proxy_pass http://digonto_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }}

    # Hashed build assets are immutable, so they can be cached hard.
    location /assets/ {{
        root /var/www/digonto;
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }}
    location /fonts/ {{
        root /var/www/digonto;
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }}

    location = /robots.txt  {{ root /var/www/digonto; }}
    location = /sitemap.xml {{ root /var/www/digonto; }}

    # Single-page application: unknown paths are client routes, not 404s.
    location / {{
        root /var/www/digonto;
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-cache";
    }}
}}
"""

NGINX_HTTP_ONLY = """\
server {{
    listen 80;
    listen [::]:80;
    server_name {domain};
    location /.well-known/acme-challenge/ {{ root /var/www/certbot; }}
    location /api/ {{
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;
    }}
    location / {{
        root /var/www/digonto;
        try_files $uri $uri/ /index.html;
    }}
}}
"""


def setup_nginx(domain: str, tls: bool) -> None:
    sh("export DEBIAN_FRONTEND=noninteractive; apt-get install -y nginx")
    Path("/var/www/certbot").mkdir(parents=True, exist_ok=True)
    Path("/var/www/digonto").mkdir(parents=True, exist_ok=True)

    conf = (NGINX_TEMPLATE if tls else NGINX_HTTP_ONLY).format(domain=domain)
    if not DRY_RUN:
        Path("/etc/nginx/sites-available/digonto").write_text(conf)
    sh("ln -sf /etc/nginx/sites-available/digonto /etc/nginx/sites-enabled/digonto")
    sh("rm -f /etc/nginx/sites-enabled/default")
    if sh("nginx -t", check=False) != 0:
        die("nginx configuration is invalid; run `nginx -t` to see why")
    sh("systemctl reload nginx || systemctl restart nginx")
    ok(f"nginx configured for {domain} ({'https' if tls else 'http only'})")


def setup_tls(domain: str, email: str) -> bool:
    sh("export DEBIAN_FRONTEND=noninteractive; apt-get install -y certbot python3-certbot-nginx")

    if Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem").exists():
        ok("certificate already present")
    else:
        # webroot rather than the nginx plugin: it does not rewrite our config,
        # which we regenerate on every deploy anyway.
        rc = sh(
            f"certbot certonly --webroot -w /var/www/certbot "
            f"-d {domain} --email {email} --agree-tos --non-interactive "
            f"--no-eff-email",
            check=False,
            quiet=False,
        )
        if rc != 0:
            warn("certbot failed. Continuing over HTTP.")
            info("Common causes: DNS not propagated, or port 80 blocked by a cloud firewall.")
            return False
        ok("certificate issued")

    sh("systemctl enable --now certbot.timer", check=False)
    if not DRY_RUN:
        hook = Path("/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh")
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\nsystemctl reload nginx\n")
        os.chmod(hook, 0o755)
    ok("automatic renewal enabled")
    return True


# ------------------------------------------------------------------ deploy
def build_frontend() -> None:
    """Build the client on the VM and serve it from nginx as static files.

    Serving the built assets directly from nginx rather than from a Node
    container removes a long-running process and a whole class of failure.
    """
    if not shutil.which("node"):
        sh("curl -fsSL https://deb.nodesource.com/setup_20.x | bash -")
        sh("export DEBIAN_FRONTEND=noninteractive; apt-get install -y nodejs")
    fe = APP_DIR / "frontend"
    sh(f"cd {fe} && npm ci --no-audit --no-fund || npm install --no-audit --no-fund", quiet=False)
    sh(f"cd {fe} && npm run build", quiet=False)
    dist = fe / "dist"
    if not DRY_RUN and not dist.exists():
        die("frontend build produced no dist/ directory")
    sh(f"rsync -a --delete {dist}/ /var/www/digonto/")
    sh("chown -R www-data:www-data /var/www/digonto")
    ok("web client built and published to /var/www/digonto")


def compose_up() -> None:
    if not COMPOSE_FILE.exists():
        die(f"{COMPOSE_FILE.name} not found. It ships with the repository.")
    sh(f"cd {APP_DIR} && docker compose -f {COMPOSE_FILE.name} --env-file {ENV_FILE.name} pull || true")
    sh(
        f"cd {APP_DIR} && docker compose -f {COMPOSE_FILE.name} "
        f"--env-file {ENV_FILE.name} up -d --build",
        quiet=False,
    )
    ok("containers started")


def pull_model(skip: bool) -> None:
    if skip:
        info("skipping model pull")
        return
    info("pulling gemma4:e2b, this is several gigabytes and takes a while")
    sh("docker compose -f docker-compose.prod.yml exec -T ollama ollama pull gemma4:e2b",
       check=False, quiet=False)
    sh("docker compose -f docker-compose.prod.yml exec -T ollama ollama pull bge-m3",
       check=False, quiet=False)

    caps = sh_out(
        "docker compose -f docker-compose.prod.yml exec -T ollama "
        "ollama show gemma4:e2b 2>/dev/null"
    )
    if "tools" in caps:
        ok("model present and reports native tool support")
    else:
        warn("could not confirm tool support on the pulled model; agents may not work")


def wait_healthy(domain: str, tls: bool, timeout: int = 180) -> None:
    scheme = "https" if tls else "http"
    url = f"{scheme}://{domain}/api/v1/readyz"
    info(f"waiting for {url}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    body = json.loads(r.read() or b"{}")
                    ok(f"service healthy: {body}")
                    return
        except Exception:
            pass
        time.sleep(4)
    warn("service did not report healthy in time")
    info("Inspect with:  docker compose -f docker-compose.prod.yml logs --tail=100 api")


def harden(tls: bool) -> None:
    sh("ufw --force reset", check=False)
    sh("ufw default deny incoming", check=False)
    sh("ufw default allow outgoing", check=False)
    sh("ufw allow OpenSSH", check=False)
    sh("ufw allow 80/tcp", check=False)
    if tls:
        sh("ufw allow 443/tcp", check=False)
    sh("ufw --force enable", check=False)
    ok("firewall enabled: SSH, 80" + (", 443" if tls else ""))

    sh("systemctl enable --now fail2ban", check=False)
    if not DRY_RUN:
        Path("/etc/apt/apt.conf.d/20auto-upgrades").write_text(
            'APT::Periodic::Update-Package-Lists "1";\n'
            'APT::Periodic::Unattended-Upgrade "1";\n'
        )
    ok("fail2ban and unattended security updates enabled")

    # The database ports must never be reachable from outside. They are bound to
    # the compose network only, but Docker publishing rules bypass ufw, so this
    # is worth verifying rather than assuming.
    for port in (6379, 6333, 11434, 8000):
        listening = sh_out(f"ss -ltnp 2>/dev/null | grep ':{port} ' || true")
        if "0.0.0.0" in listening:
            warn(f"port {port} is listening on all interfaces; it should be internal only")


def main() -> None:
    global DRY_RUN
    ap = argparse.ArgumentParser(description="Deploy Digonto to a cloud VM")
    ap.add_argument("--domain", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--skip-tls", action="store_true")
    ap.add_argument("--skip-model-pull", action="store_true")
    ap.add_argument("--update", action="store_true", help="redeploy code only")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    DRY_RUN = a.dry_run

    print(f"{C.BOLD}Digonto{C.X} {C.DIM}deploying to {a.domain}{C.X}")
    if DRY_RUN:
        warn("dry run: printing commands, changing nothing")

    tls = not a.skip_tls

    if a.update:
        step("Redeploying code only")
        build_frontend()
        compose_up()
        wait_healthy(a.domain, tls)
        print(f"\n{C.G}Updated.{C.X} https://{a.domain}\n")
        return

    step("Checking the machine")
    require_root()
    check_machine()
    check_dns(a.domain, a.skip_tls)

    step("Installing system packages")
    install_base()
    install_docker()

    step("Writing production configuration")
    write_env(a.domain)

    step("Building the web client")
    build_frontend()

    step("Configuring nginx")
    setup_nginx(a.domain, tls=False)  # HTTP first so certbot can answer the challenge

    if tls:
        step("Obtaining the TLS certificate")
        tls = setup_tls(a.domain, a.email)
        if tls:
            setup_nginx(a.domain, tls=True)

    step("Starting the stack")
    compose_up()

    step("Pulling the model")
    pull_model(a.skip_model_pull)

    step("Waiting for health")
    wait_healthy(a.domain, tls)

    step("Hardening")
    harden(tls)

    scheme = "https" if tls else "http"
    print(
        f"""
{C.BOLD}  Digonto is deployed{C.X}

  Site     {C.B}{scheme}://{a.domain}{C.X}
  Health   {C.B}{scheme}://{a.domain}/api/v1/readyz{C.X}

  Logs        docker compose -f docker-compose.prod.yml logs -f api
  Restart     docker compose -f docker-compose.prod.yml restart api
  Redeploy    sudo python3 run_onVM.py --domain {a.domain} --email {a.email} --update

  {C.DIM}Production uses SEED_DEMO_DATA=false; create accounts via sign-up or mod tools.{C.X}
"""
    )


if __name__ == "__main__":
    main()
