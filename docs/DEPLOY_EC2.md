# Deploying QBCals to an EC2 Instance

Step-by-step guide to run the QBCals backend (FastAPI + Celery + Redis) on a
single AWS EC2 instance. There is no frontend yet (Phase 1.4+, not built) —
this deploys the API and background workers only.

Assumes Ubuntu 24.04 LTS and Python 3.12 (matches this repo's dev environment).

## Architecture being deployed

```
Internet -> [nginx :443/:80] -> [uvicorn :8000 (FastAPI)] -> Postgres (Supabase or local)
                                        |
                                Redis (local, :6379)
                                        |
                        Celery workers (enrichment queue, matching queue)
```

## 0. Prerequisites

- An AWS account and an EC2 key pair (`.pem` file) — **never commit this file
  to git**. This repo's `.gitignore` already excludes `*.pem`; keep it that way.
- API keys ready: `AI_API_KEY` (OpenAI), `TAVILY_API_KEY`, optionally
  `CRUNCHBASE_API_KEY`.
- A Postgres database with the `pgvector` extension — either a
  [Supabase](https://supabase.com) project (recommended, matches this
  project's documented production architecture — see CLAUDE.md) or a
  self-hosted Postgres on the same EC2 box (Option B in Step 5).
- Optional: a domain name pointed at the instance, if you want HTTPS via
  Let's Encrypt (Step 9). Without one you can still serve plain HTTP on the
  instance's public IP for testing.

## 1. Launch the EC2 instance

1. AMI: **Ubuntu Server 24.04 LTS** (x86_64).
2. Instance type: **t3.medium** (2 vCPU / 4 GB RAM) minimum. Playwright
   launches a real headless Chromium for the website/LinkedIn scrapers —
   `t3.micro`/`t3.small` will swap heavily or OOM under real enrichment load.
3. Storage: 20 GB gp3 is enough (no large local datasets — the DB is
   typically external via Supabase).
4. Key pair: select your existing key pair (e.g. `sbiq.pem`).
5. Security group — open only:
   - **22 (SSH)** — restrict source to your IP, not `0.0.0.0/0`.
   - **80 (HTTP)** and **443 (HTTPS)** — from anywhere, if using nginx (Step 9).
   - Do **not** open 5432 (Postgres) or 6379 (Redis) publicly — both should
     stay bound to localhost (self-hosted Postgres) or go through Supabase's
     own managed endpoint over TLS.
6. Launch, then note the instance's public IP/DNS.

## 2. Connect

```bash
chmod 400 sbiq.pem
ssh -i sbiq.pem ubuntu@<your-instance-public-ip>
```

## 3. Install system dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3-pip git build-essential \
    libpq-dev nginx redis-server
```

`libpq-dev` is required for `psycopg2-binary` to build/install correctly.

## 4. Clone the repo and set up the virtualenv

```bash
cd ~
git clone <your-repo-url> SBIQ
cd SBIQ/backend

python3.12 -m venv myenv
source myenv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Playwright's own Chromium binary + OS-level deps (fonts, codecs, etc.)
playwright install --with-deps chromium
```

## 5. Configure environment

Copy the template and fill in real values — **this file must live at
`backend/.env`**, not the repo root (per `docs/CONFIG_CAVEATS.md` — a
root-level `.env` is silently ignored, no error).

```bash
cp ../.env.example .env
nano .env
```

Fill in at minimum: `AI_API_KEY`, `TAVILY_API_KEY`, `DATABASE_URL`.

**Database — pick one:**

- **Option A (recommended): Supabase.** Matches this project's documented
  production architecture. In `.env`:
  ```
  DATABASE_URL=postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres
  ```
  Enable the `vector` extension in the Supabase SQL editor once:
  `create extension if not exists vector;`

- **Option B: self-hosted Postgres on this box.**
  ```bash
  sudo apt install -y postgresql postgresql-contrib postgresql-16-pgvector
  sudo -u postgres psql -c "CREATE DATABASE qbcals;"
  sudo -u postgres psql -c "CREATE USER qbcals WITH PASSWORD '<strong-password>';"
  sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE qbcals TO qbcals;"
  # Postgres 15+ (including the 16 that ships with Ubuntu 24.04) no longer
  # grants CREATE on the public schema to all users by default - without
  # this, "alembic upgrade head" fails with "permission denied for schema
  # public" the moment it tries to create alembic_version.
  sudo -u postgres psql -d qbcals -c "GRANT ALL PRIVILEGES ON SCHEMA public TO qbcals;"
  sudo -u postgres psql -d qbcals -c "CREATE EXTENSION IF NOT EXISTS vector;"
  ```
  Then in `.env`: `DATABASE_URL=postgresql://qbcals:<strong-password>@localhost:5432/qbcals`

**Redis** — leave `REDIS_URL`/`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`
pointing at `localhost` (Redis was installed in Step 3, and unlike this
project's Windows/WSL dev setup, a native Linux `redis-server` needs no
extra port-forwarding — it just works). Confirm it's running:

```bash
sudo systemctl enable --now redis-server
redis-cli ping   # expect: PONG
```

## 6. Run database migrations

```bash
cd ~/SBIQ/backend
source myenv/bin/activate
alembic upgrade head
```

## 7. Smoke-test manually before wiring up systemd

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
# in a second SSH session:
curl http://localhost:8000/health
# {"status":"ok","model":"gpt-4o"}
```
Ctrl-C to stop once confirmed — systemd will own the process from here.

## 8. systemd services

Three services: the API, and two Celery workers split by queue (per
`worker.py`'s own guidance — production should run enrichment and matching
as separate worker processes, not the combined dev entrypoint).

**`/etc/systemd/system/qbcals-api.service`**
```ini
[Unit]
Description=QBCals FastAPI
After=network.target redis-server.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/SBIQ/backend
ExecStart=/home/ubuntu/SBIQ/backend/myenv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/qbcals-worker-enrichment.service`**
```ini
[Unit]
Description=QBCals Celery worker (enrichment queue)
After=network.target redis-server.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/SBIQ/backend
ExecStart=/home/ubuntu/SBIQ/backend/myenv/bin/python worker.py --queues=enrichment
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/qbcals-worker-matching.service`**
```ini
[Unit]
Description=QBCals Celery worker (matching queue)
After=network.target redis-server.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/SBIQ/backend
ExecStart=/home/ubuntu/SBIQ/backend/myenv/bin/python worker.py --queues=matching
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> **Do not add `--pool=solo` here.** That flag is a Windows-only workaround
> used in this project's local dev setup (`docs/CONFIG_CAVEATS.md`) because
> Celery's default prefork pool doesn't work reliably on Windows. On this
> Linux box, leave the default prefork pool for real concurrency.

Enable and start all three:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now qbcals-api qbcals-worker-enrichment qbcals-worker-matching
sudo systemctl status qbcals-api qbcals-worker-enrichment qbcals-worker-matching
```

View logs any time with `journalctl -u qbcals-api -f` (or the worker unit names).

## 9. nginx reverse proxy + HTTPS (optional but recommended)

**`/etc/nginx/sites-available/qbcals`**
```nginx
server {
    listen 80;
    server_name your-domain.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/qbcals /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# HTTPS via Let's Encrypt (requires a real domain pointed at this instance)
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.example.com
```

**No domain yet?** Two options:

- **Use nginx anyway, without TLS.** Same config as above but with
  `server_name _;` (nginx's catch-all) instead of a domain, and skip the
  `certbot` step entirely. Remove the default site first so it doesn't
  intercept requests: `sudo rm -f /etc/nginx/sites-enabled/default`. Then
  browse to `http://<instance-public-ip>/docs`.
- **Skip nginx entirely.** Add port `8000` to the security group and hit
  `http://<instance-public-ip>:8000/docs` directly — fine for internal
  testing, not for real client use (plain HTTP, no reverse proxy).

## 10. Verify end-to-end

```bash
curl https://your-domain.example.com/health
curl https://your-domain.example.com/events
```
Then exercise the real endpoints via `/docs` (same Swagger UI used in local
dev) at `https://your-domain.example.com/docs`.

## 11. Deploying updates later

```bash
cd ~/SBIQ
git pull
cd backend
source myenv/bin/activate
pip install -r requirements.txt   # only if dependencies changed
alembic upgrade head              # only if new migrations exist
sudo systemctl restart qbcals-api qbcals-worker-enrichment qbcals-worker-matching
```

## Things worth knowing before you flip this on for real traffic

- **CORS is currently wide open** (`allow_origins=["*"]` in `main.py`) — fine
  for an internal/admin-only deployment, but tighten this to your actual
  frontend origin before exposing it more broadly.
- **`AI_MAX_TOKENS_PER_RUN` does nothing yet** — it's a documented cost cap
  with no enforcement code behind it (`docs/CONFIG_CAVEATS.md`). Nothing on
  this server will stop a runaway matching run from spending real money.
- **`ENABLE_LLM_WEB_SEARCH=true` requires `AI_BASE_URL` to stay pointed at
  OpenAI** — it uses OpenAI's Responses API hosted `web_search` tool, which
  isn't portable to other "OpenAI-compatible" providers.
- **Crunchbase is off by default** (`ENABLE_CRUNCHBASE=false`) — no API key
  configured; its field mapping has also never been verified against a live
  account (`docs/CONFIG_CAVEATS.md`).
- **Playwright/Chromium needs real memory headroom.** If enrichment jobs
  start failing silently under load, check `free -h` before assuming it's a
  code bug — this is the most likely resource bottleneck on a small instance.
- **Watch your LLM provider's billing/quota**, independent of this app —
  a `429 insufficient_quota` error from OpenAI will fail every enrichment/
  matching call until the account's billing is topped up, and looks like a
  wave of task failures in `journalctl -u qbcals-worker-*`, not an obvious
  "add credits" message.
