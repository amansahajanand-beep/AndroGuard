# DigitalOcean deployment

The API is a single Docker service. HTTPS terminates at DigitalOcean (App Platform) or at nginx on a droplet. Do not expose Uvicorn on port 80 without a proxy.

Recommended size: **2 GB RAM**, 1 vCPU. Androguard can use a few hundred MB per large APK. Keep **one Uvicorn worker** unless you have 4 GB+.

## Environment

Set these in the App Platform / droplet environment. Copy from `.env.example`. Never commit `.env`.

| Variable | Production |
|---|---|
| `DATABASE_URL` | Supabase pooler URL (`6543`) |
| `TEMP_ROOT` | `/app/tmp` |
| `LOG_LEVEL` | `INFO` |
| `MAX_APK_SIZE_MB` | `80` |
| `ANALYSIS_TIMEOUT_SECONDS` | `90` |
| `UVICORN_WORKERS` | `1` |
| `AAPT_PATH` | leave empty (image includes `aapt`) |

Health check path: `GET /api/v1/health`  
Expect `database.ready: true` and `aapt_available: true` in the container.

Upload and analysis timeouts at the proxy must be **greater than** `ANALYSIS_TIMEOUT_SECONDS` (use 120s). Body size must be **at least** `MAX_APK_SIZE_MB` (use 80m).

## Option A — App Platform (simplest HTTPS)

1. Push this repo to GitHub.
2. DigitalOcean → **Apps** → Create → GitHub → this repo.
3. Set **source directory** to `backend` so the Dockerfile and `requirements.txt` resolve.
4. HTTP port **8000**.
5. Health check **HTTP**, path `/api/v1/health`.
6. Add env vars from the table above. Mark `DATABASE_URL` as **secret**.
7. Instance: at least `basic-xs` / 1 GB; prefer 2 GB if you analyze 50 MB+ APKs.
8. After deploy, open `https://<app>.ondigitalocean.app/api/v1/health`.

App Platform already provides HTTPS. Point a domain at the app in **Settings → Domains**.

If APK uploads fail with 413, raise the App Platform / CDN body limit or upload through a droplet with nginx (`client_max_body_size 80m`).

A sample spec is in [`.do/app.yaml`](../.do/app.yaml) at the repo root (`doctl apps create --spec .do/app.yaml`).

## Option B — Droplet + Docker Compose + nginx

### 1. Droplet

- Image: Ubuntu 24.04
- Size: 2 GB RAM
- Region: closest to users (e.g. Bangalore `blr1`)
- Add your SSH key
- Enable a firewall: allow 22, 80, 443 only

```bash
apt-get update
apt-get install -y docker.io docker-compose-plugin nginx certbot python3-certbot-nginx
```

### 2. App

```bash
git clone <your-repo> /opt/androguard
cd /opt/androguard/backend
cp .env.example .env
# edit .env — set DATABASE_URL
export TEMP_ROOT=/app/tmp
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Confirm:

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
```

### 3. nginx

Replace `api.example.com`. The compose file binds Uvicorn to localhost in prod.

```nginx
server {
    listen 80;
    server_name api.example.com;
    client_max_body_size 80m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Request-ID $request_id;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/androguard /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d api.example.com
```

Certbot enables HTTPS. Android clients should call `https://api.example.com`.

### 4. Firewall

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable
```

Do not publish port 8000 on the public interface. `docker-compose.prod.yml` maps `127.0.0.1:8000:8000`.

## Checks after deploy

```bash
curl -sS https://api.example.com/api/v1/health
curl -sS -F "file=@app.apk" https://api.example.com/api/v1/analyze
```

- `aapt_available` should be `true` (Debian `aapt` in the image).
- `database.ready` should be `true` if `DATABASE_URL` is set.
- Screenshots persist in Postgres (`screenshot_files`).

## Operations

- Logs: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api`
- Restart: `docker compose ... restart api`
- Disk: APK temp files are deleted after analyze; keep a volume on `/app/tmp` for in-flight jobs only.

No Kubernetes. One container is enough.
