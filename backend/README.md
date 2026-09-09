# AndroGuard APK Analyzer

FastAPI backend that accepts an Android APK and returns structured JSON:

- Manifest, permissions, metadata, SDK
- Activities and services (including intent filters)
- DEX static code analysis (sensitive API call sites, network/WebView/file/telephony usage, SDKs)
- Raster image assets extracted from `res/` and `assets/`

This service reports what the APK contains. It does not score policy violations, run the APK, or use AI.

## Quick start

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://127.0.0.1:8000/docs for Swagger UI.

Supported runtimes: Python 3.11+ (Docker image uses 3.11). Python 3.14 works locally with current wheels.

## Docker

```bash
cd backend
docker compose up --build
```

Production (localhost bind + restart policy):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

DigitalOcean (App Platform or droplet + nginx/HTTPS): see [DEPLOY.md](DEPLOY.md).

## API

### `GET /api/v1/health`

Liveness check.

### `POST /api/v1/auth/signup`

JSON body `full_name`, `company_name`, `email`, `password` (min 8 chars). Returns `201` with a
bearer token and the created user. `409 EMAIL_ALREADY_REGISTERED` if the email is taken.

### `POST /api/v1/auth/login`

JSON body `email`, `password`. Returns a bearer token, or `401 INVALID_CREDENTIALS`.

### `GET /api/v1/auth/me`

Requires `Authorization: Bearer <token>`. Returns the current user profile.

### `POST /api/v1/analyze`

`multipart/form-data` field `file` (`.apk`), plus these optional submission fields:

| Field | Notes |
| --- | --- |
| `app_name` | Submitter-supplied app name (max 200 chars). |
| `app_description` | App description / purpose (max 4000 chars). |
| `privacy_policy` | Either an `http(s)` link or a file path; echoed back with `privacy_policy_kind` of `url` or `file_path`. |
| `play_store_url` | Must start with `http://` or `https://`. |

Blank values are treated as omitted. An invalid value returns `400 INVALID_SUBMISSION`. The
values are echoed back under `data.submission` and stored with the analysis history.

Success envelope:

```json
{
  "schema_version": "1.0.0",
  "status": "completed",
  "data": {
    "apk": {},
    "submission": {
      "app_name": "Photo Editor",
      "app_description": "Edits and filters photos.",
      "privacy_policy": "https://example.com/privacy",
      "privacy_policy_kind": "url",
      "play_store_url": "https://play.google.com/store/apps/details?id=com.example"
    },
    "manifest": {},
    "permissions": [],
    "metadata": [],
    "sdk": {},
    "activities": [],
    "services": [],
    "screenshots": [],
    "code_analysis": {
      "summary": {},
      "classes": [],
      "methods": [],
      "api_calls": [
        {
          "class_name": "com.example.CallFunction",
          "method_name": "makeCall",
          "api_class": "android.telecom.TelecomManager",
          "api_method": "placeCall",
          "risk_category": "PHONE",
          "evidence": "method invocation detected",
          "confidence": "HIGH"
        }
      ],
      "sensitive_api_calls": [],
      "network_calls": [],
      "webview_usage": [],
      "file_storage_operations": [],
      "telephony_calls": [],
      "data_access_indicators": [],
      "dynamic_code_loading": [],
      "third_party_sdk_usage": [],
      "code_findings": []
    },
    "analysis": {}
  }
}
```

### `GET /api/v1/files/{job_id}/{file_name}`

Download an extracted image. When `DATABASE_URL` is set, screenshot bytes are stored in PostgreSQL (`screenshot_files`) so they survive process restarts. Local `tmp/jobs` is only a cache.

### Errors

```json
{
  "error": {
    "code": "INVALID_APK",
    "message": "The uploaded file is not a valid Android APK."
  }
}
```

Codes include `INVALID_FILE`, `INVALID_APK`, `CORRUPT_APK`, `UNSUPPORTED_APK`, `APK_TOO_LARGE`, `MANIFEST_INVALID`, `ANALYSIS_TIMEOUT`, `ANALYZER_ERROR`.

## Configuration

Copy `.env.example` to `.env`. Important limits:

| Variable | Default |
|---|---|
| `MAX_APK_SIZE_MB` | 80 |
| `ANALYSIS_TIMEOUT_SECONDS` | 90 |
| `MAX_SCREENSHOTS` | 40 |
| `DEX_ANALYSIS_ENABLED` | `true`. Set `false` to skip DEX/code analysis. |
| `MAX_CODE_CLASSES` / `MAX_CODE_METHODS` / `MAX_CODE_FINDINGS` | Caps for `code_analysis` lists (defaults 200 / 300 / 200). |
| `MAX_IMAGE_BYTES` | 8388608 |
| `DATABASE_URL` | unset (optional). Supabase pooler URL persists analysis history and user accounts. |
| `JWT_SECRET` | signing key for auth tokens. Set a long random value in production. |
| `JWT_ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` | `HS256` / `1440` (24h). |
| `AAPT_PATH` | optional path to `aapt`. Docker installs Debian `aapt`. Host without aapt still analyzes via Androguard. |
| `UVICORN_WORKERS` | `1` in production (memory). |
| `S3_ENDPOINT_URL` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Supabase S3-compatible storage for screenshot files. |

## Tests

```bash
cd backend
pytest
```

The suite covers invalid uploads, size/timeout limits, AAB rejection, zip-slip, and PNG/JPEG/WebP extraction. To also run a live Androguard parse, place a small `.apk` at `tests/fixtures/apks/sample.apk`.

## Out of scope

Google policy checks, authentication, Redis, emulator screenshots. DEX analysis reports referenced APIs and strings, not runtime behavior or policy verdicts.
