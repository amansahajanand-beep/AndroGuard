# PlayGuard

Google Play Compliance Auditor frontend.

## Run

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

Demo account:

- Email: `alex@northstar.dev`
- Password: `PlayGuard123`

Backend APIs are not connected yet. Services in `src/services` use a centralized mock layer in `src/mock`. Replace those service implementations when the API is available. Compliance, risk, readiness, and recommendations are never calculated in the UI.
