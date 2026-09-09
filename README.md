# AndroGuard

Android APK analysis backend. The API lives in [`backend/`](backend/README.md).

```bash
cd backend
docker compose up --build
```

Then `POST /api/v1/analyze` with an `.apk` file.

Production deploy: [backend/DEPLOY.md](backend/DEPLOY.md).
