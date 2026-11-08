# FolioLens — AI Portfolio Health Analyzer

Upload your stock portfolio CSV and get a private, live-priced health report: valuation and P/L, sector
and concentration risk, volatility, current financial news, and transparent evidence-based
decision-support signals for individual stocks.

> FolioLens is a decision-support tool, **not** financial advice. It never places trades.

---

## Features

| Area | What it does |
|---|---|
| **Accounts** | Registration, login, logout, profile, password change, active sessions, account deletion. Each user's data is private. |
| **Overview** | Portfolio value, invested amount, overall and daily P/L, sector allocation, largest holdings, movers, alerts, recent activity. |
| **My Portfolio** | Holdings table with live price, market value, P/L, day change and weight; search, filter, sort; add / edit / remove holdings. |
| **CSV Import & Export** | Upload → auto-detect columns (Zerodha, Groww, Upstox, custom) → preview and row validation → confirm (replace or merge). Secure, re-importable export. |
| **Portfolio Health** | Health score, diversification (HHI), concentration, beta, volatility, max drawdown, historical value chart, risk indicators with explanations, AI or rule-based insights. |
| **Stock News & Insights** | Stock search, transparent signal (Potential Buy / Hold / Potential Sell / Insufficient Data) with every factor, positive and negative news, risks, what to monitor, a "wait for a lower price?" check, sources, an optional AI interpretation; market news; news for your holdings. |
| **Market Watchlist** | Track symbols, live prices, price alerts (above / below), per-symbol news. |
| **Reports & Analytics** | Historical performance, P/L and allocation charts; downloadable P/L, allocation, performance and holdings CSVs. |
| **Profile & Settings** | Profile, password, sessions, data-integration status, security and activity log, logout, delete account. |

No data is invented: if a provider fails, the app shows the last good value flagged as **stale**, or a
clear error. Holdings without a live price are shown as **unpriced** and excluded from totals; the
purchase price is never used as if it were a market price.

---

## Architecture

```
React 18 + Vite SPA  ──(same origin /api, HttpOnly cookies, CSRF header)──►  FastAPI
  react-router pages                                                           ├─ routers/   auth, users, portfolio, imports, market (news+insights), watchlist, reports, status
  axios client (auto refresh)                                                  ├─ services/  market_data, news, sentiment, signals, analytics, metrics_engine,
  recharts, lucide-react                                                       │             portfolio_service, csv_parser, ai_insights, auth_service, http_client
                                                                               ├─ core/      config, security (Argon2id, JWT), crypto (AES-256-GCM), ratelimit, cache, logging
                                                                               ├─ db/        SQLAlchemy models + session (SQLite default, PostgreSQL supported)
                                                                               └─ alembic/   migrations
External: Yahoo Finance (yfinance) · optional Finnhub · optional Marketaux · optional Anthropic Claude
```

```
foliolens/
├── backend/
│   ├── app/
│   │   ├── main.py                # app, security middleware (CSRF, headers, HTTPS), error handlers
│   │   ├── deps.py                # get_current_user (JWT validation + session check)
│   │   ├── core/                  # config, security, crypto, ratelimit, cache, logging
│   │   ├── db/                    # models.py, session.py
│   │   ├── models/schemas.py      # Pydantic request/response schemas
│   │   ├── routers/               # auth, users, portfolio, imports, market, watchlist, reports, status
│   │   └── services/              # business logic and provider integrations
│   ├── alembic/ + alembic.ini     # database migrations
│   ├── tests/                     # pytest suite (security, isolation, CSV, signals, live providers)
│   ├── requirements.txt / requirements-dev.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # routes + auth guard
│   │   ├── components/            # Layout (sidebar), ui kit, charts, SymbolSearch, NewsList
│   │   ├── context/               # AuthContext, ToastContext
│   │   ├── pages/                 # one page per sidebar section + Login/Register
│   │   ├── services/api.js        # axios client, CSRF, silent token refresh, downloads
│   │   ├── utils/format.js
│   │   └── test/                  # vitest tests
│   ├── package.json / vite.config.js
├── deploy/nginx.conf.example      # HTTPS reverse proxy example
├── sample_portfolio.csv
└── README.md
```

---

## Prerequisites

- Python **3.10+** (tested with 3.12)
- Node.js **20.19+** or **22.12+** (tested with 24) and npm
- Internet access for market data and news

---

## Installation & running (development)

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # Windows: copy .env.example .env
```

Generate the two required secrets and paste them into `backend/.env`:

```bash
python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import os, base64; print('CSV_ENCRYPTION_KEY=' + base64.b64encode(os.urandom(32)).decode())"
```

Create the database and start the API:

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000 · interactive docs: http://localhost:8000/docs (disabled when `APP_ENV=production`)
- The app refuses to start if `JWT_SECRET_KEY` or `CSV_ENCRYPTION_KEY` is missing or weak.

### 2. Frontend (new terminal)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, create an account, then import `sample_portfolio.csv` from **CSV Import & Export**.
Vite proxies `/api` to `http://localhost:8000` (override with `VITE_API_PROXY_TARGET`).

---

## Database & migrations

- Default: SQLite file `backend/foliolens.db` (`DATABASE_URL=sqlite:///./foliolens.db`), with
  `foreign_keys` and `secure_delete` enabled.
- PostgreSQL: install a driver (`pip install "psycopg[binary]"`) and set
  `DATABASE_URL=postgresql+psycopg://user:password@host:5432/foliolens`.
- Apply migrations: `alembic upgrade head`. After changing models: `alembic revision --autogenerate -m "describe change"`.
- Tables: `users`, `auth_sessions`, `refresh_tokens`, `holdings`, `csv_uploads`, `watchlist_items`,
  `portfolio_snapshots`, `activity_log`. Every user-owned table has a non-null `user_id` foreign key with `ON DELETE CASCADE`.

---

## API keys and providers

| Variable | Needed? | Where to get it |
|---|---|---|
| *(none)* — Yahoo Finance | Default for prices, history, fundamentals, search and news. No key. | — |
| `AI_API_KEY` | Optional — enables AI-written insights. | Anthropic Console → https://console.anthropic.com/settings/keys (billing required). |
| `FINANCIAL_NEWS_API_KEY` with `FINANCIAL_NEWS_PROVIDER=marketaux` | Optional — article summaries and provider sentiment; better Indian-market coverage. | https://www.marketaux.com/register (free tier: 100 requests/day). |
| `MARKET_DATA_API_KEY` with `MARKET_DATA_PROVIDER=finnhub` | Optional — alternative quote/profile source, mainly **US** listings on the free tier. | https://finnhub.io/register |

Keys live only in `backend/.env` and are used only on the server. They are never sent to the browser,
returned by the API or logged. The **Profile & Settings → Data integrations** panel shows whether each
provider is configured and when it last succeeded or failed.

If a provider is selected but its key is missing, the API returns a clear configuration error; it never
substitutes fake data. Without `AI_API_KEY`, insights are rule-based and labelled "Rule-based" with a notice.

**About Yahoo Finance:** it is an unofficial API accessed through `yfinance`. It can rate-limit or change
without notice; FolioLens retries transient failures (bounded), caches results, and falls back to the last
good value marked stale. For production reliability consider a paid licensed data feed.

### Ticker resolution

Bare tickers from Indian broker exports (e.g. `RELIANCE`) are resolved to NSE first (`RELIANCE.NS`), then
BSE (`.BO`), then the bare symbol (US). Change the order with `TICKER_SUFFIXES` (e.g. `,.NS,.BO` to prefer US).
Tickers renamed after corporate actions (e.g. demergers) show as unpriced until updated.

---

## Environment variables

All variables are documented inline in [`backend/.env.example`](backend/.env.example). Key groups:

- **App**: `APP_ENV`, `LOG_LEVEL`, `CORS_ORIGINS`, `TRUSTED_HOSTS`, `FORCE_HTTPS`
- **Database**: `DATABASE_URL`
- **JWT / cookies**: `JWT_SECRET_KEY`, `JWT_ISSUER`, `JWT_AUDIENCE`, `ACCESS_TOKEN_EXPIRE_MINUTES` (15),
  `REFRESH_TOKEN_EXPIRE_DAYS` (7), `COOKIE_SECURE`, `COOKIE_SAMESITE`, `COOKIE_DOMAIN`
- **Rate limits**: `LOGIN_RATE_LIMIT`, `REGISTER_RATE_LIMIT`, `REFRESH_RATE_LIMIT`, `API_RATE_LIMIT`
- **CSV**: `CSV_ENCRYPTION_KEY`, `CSV_MAX_BYTES`, `CSV_MAX_ROWS`, `CSV_UPLOAD_TTL_MINUTES`
- **Market data**: `MARKET_DATA_PROVIDER`, `MARKET_DATA_API_KEY`, `TICKER_SUFFIXES`, cache and timeout settings, `STALE_AFTER_SECONDS`
- **News**: `FINANCIAL_NEWS_PROVIDER`, `FINANCIAL_NEWS_API_KEY`, `NEWS_CACHE_SECONDS`
- **AI**: `AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL` (default `claude-opus-5-5`), `AI_TIMEOUT_SECONDS`

---

## Security design

### Authentication (JWT)

- Passwords hashed with **Argon2id** (`argon2-cffi`), transparently re-hashed when parameters change.
  Policy: 10–128 characters with upper, lower and digit, and not containing the email name.
- **Access token**: HS256 JWT, 15 minutes, claims `iss`, `aud`, `sub`, `sid`, `iat`, `nbf`, `exp`, `jti`, `typ`.
  Signature, expiry, issuer, audience and required claims are all validated; the algorithm is pinned (no `alg=none`).
  No personal data in the payload.
- **Refresh token**: 384-bit random opaque token, stored only as a SHA-256 hash, **rotated on every use**.
  Re-use of an already-rotated token revokes the whole session (theft detection).
- **Sessions**: each login is a server-side session; every request checks the session is not revoked, so
  **logout takes effect immediately** for existing access tokens. Password change signs out other sessions.
- **Storage**: tokens are in `HttpOnly`, `SameSite` cookies (`Secure` in production) — never in `localStorage`.
  The refresh cookie is scoped to `/api/auth`.
- **CSRF**: double-submit token (`fl_csrf` cookie + `X-CSRF-Token` header) required on every state-changing request.
- **Rate limits** on login (per IP and per email), registration, refresh, password checks and general API use.
- Login errors are identical for unknown email and wrong password, and unknown emails still run a full Argon2
  verification to equalise timing. (Registration necessarily reports an already-used email.)

### Data isolation

Every query for holdings, uploads, watchlist items, snapshots, sessions and activity filters by the
authenticated `user_id`. Accessing another user's record by ID returns **404** (no existence leak).
Covered by `tests/test_isolation.py`.

### CSV protection — in transit vs. at rest

- **HTTPS/TLS (in transit)** encrypts the connection between browser and server so uploads, downloads and
  cookies can't be read or modified on the network. Local development over `http://localhost` is **not**
  encrypted; production must run behind TLS (see below).
- **AES-256-GCM (at rest)** protects file contents stored on the server. While an upload waits for
  confirmation, it is kept only as ciphertext in the database, bound by associated data to the owner's user id
  and upload id (a copied ciphertext fails authentication). It is decrypted only to validate or import it,
  then deleted on confirm/cancel, and automatically after `CSV_UPLOAD_TTL_MINUTES` (30). SQLite `secure_delete`
  overwrites freed pages. Raw files are never written to disk.
- Validation: `.csv` extension, MIME allow-list, size limit (read bounded to `CSV_MAX_BYTES`+1), binary / Excel /
  ZIP / PDF signatures rejected, UTF-8/CP1252 decoding, row and column limits, header detection, per-row ticker /
  number validation with line-numbered errors. Filenames are sanitised and never used as paths.
- Exports and reports are generated per user, sent with `Content-Disposition: attachment` and `Cache-Control: no-store`,
  and **formula injection** is neutralised (cells beginning with `= + - @ | tab CR` get a leading `'`).
- Logs contain request metadata only (method, path, status, duration, user id, request id) — never CSV rows,
  tokens or keys. Error responses never include stack traces or internal paths.

### Key management

- Generate `JWT_SECRET_KEY` and `CSV_ENCRYPTION_KEY` per environment; store them in your platform's secret
  manager in production. Never commit `.env` (it is in `.gitignore`).
- Rotating `JWT_SECRET_KEY` signs everyone out. Rotating `CSV_ENCRYPTION_KEY` only affects uploads awaiting
  confirmation.
- **If a secret was ever committed:** rotate it immediately at the provider (revoke the old API key, issue a new
  one), then purge it from history with `git filter-repo --path backend/.env --invert-paths` (or BFG), force-push,
  and ask collaborators to re-clone. Rotation matters more than history rewriting — assume a pushed secret is compromised.
  (The uploaded project's `backend/.env` contained only the placeholder `your-key-here`, so no real key was exposed;
  it has been removed from the delivered project.)

---

## Production deployment (HTTPS)

1. Build the frontend: `cd frontend && npm ci && npm run build` → serve `frontend/dist/`.
2. Run the API behind a TLS-terminating reverse proxy on the **same origin** as the SPA:
   `uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1 --workers 1`
3. `backend/.env`: `APP_ENV=production`, `FORCE_HTTPS=true`, `COOKIE_SECURE=true`,
   `TRUSTED_HOSTS=your.domain`, `CORS_ORIGINS=https://your.domain`, a production `DATABASE_URL`, fresh secrets.
   The app refuses to start in production without `COOKIE_SECURE` and `FORCE_HTTPS`.
4. TLS certificates: e.g. Let's Encrypt (`certbot --nginx -d your.domain`) with auto-renewal; TLS 1.2+ only.
   See [`deploy/nginx.conf.example`](deploy/nginx.conf.example) for a complete config (HTTP→HTTPS redirect, HSTS, CSP, body size limit).
5. Platforms like Render/Railway/Fly terminate TLS for you — still set the variables above and serve SPA and API
   under one domain (or set `COOKIE_SAMESITE=none` + `COOKIE_SECURE=true` and exact `CORS_ORIGINS` if they must differ).
6. The rate limiter and data caches are in-process. With multiple workers/instances, use a shared store (e.g. Redis).

---

## How metrics and signals are calculated

**Health score (0–100)** — diversification 40% (HHI-based), largest holding 25% (penalty above 10%), largest sector
20% (penalty above 25%, "Unknown" sector excluded), beta distance from 1.0 15% (re-weighted away if no beta data).

**Volatility / drawdown** — from daily closes of your *current* holdings at constant quantities (hypothetical;
past trades are not included), annualised with 252 trading days.

**Stock signal** — nine factors, each with a fixed, documented contribution: price trend (50/200-day averages),
momentum (3m/6m), RSI(14), volatility, trailing P/E, profitability & growth, leverage, recent news sentiment
(≥3 articles in 14 days; halved if contradictory), and your own position size. Unavailable factors contribute 0
and are listed as "not evaluated". Score ≥ +2 with Medium/High evidence → *Potential Buy*; ≤ −2 → *Potential
Sell / Reduce Exposure*; otherwise *Hold / Wait*; no quote or < 60 days of history → *Insufficient Data*.
**Evidence quality** counts available evidence groups (200+ days of prices, 2+ fundamentals, 3+ recent articles)
and is downgraded when the quote is stale — it is *not* a probability of being right.

**News sentiment** — provider sentiment when available (Marketaux); otherwise a keyword heuristic whose
matched terms are shown on hover. The AI model (optional) only explains the computed result from the same
facts and is shown separately, labelled "AI interpretation".

---

## API overview

Interactive docs at `/docs`. Main endpoints (all except auth and `/api/health` require a session):

| Method & path | Purpose |
|---|---|
| `GET /api/auth/csrf` · `POST /api/auth/register` · `POST /api/auth/login` · `POST /api/auth/refresh` · `POST /api/auth/logout` · `GET /api/auth/me` | Authentication |
| `GET/PATCH /api/users/me` · `POST /api/users/me/password` · `GET /api/users/me/sessions` · `POST /api/users/me/sessions/revoke-others` · `GET /api/users/me/activity` · `DELETE /api/users/me` | Profile & security |
| `GET /api/portfolio/overview` · `GET/POST /api/portfolio/holdings` · `PUT/DELETE /api/portfolio/holdings/{id}` · `GET /api/portfolio/health` · `GET /api/portfolio/history` | Portfolio |
| `POST /api/imports/upload` · `POST /api/imports/validate` · `POST /api/imports/confirm` · `DELETE /api/imports/{id}` · `GET /api/imports/export/holdings.csv` | CSV |
| `GET /api/market/search` · `GET /api/market/quote/{symbol}` · `GET /api/market/history/{symbol}` | Market data |
| `GET /api/news` · `GET /api/news/portfolio` · `GET /api/insights/{symbol}?refresh=&ai=` | News & signals |
| `GET/POST /api/watchlist` · `PUT/DELETE /api/watchlist/{id}` | Watchlist |
| `GET /api/reports/pnl.csv` · `/allocation.csv` · `/performance.csv` | Reports |
| `GET /api/status` · `GET /api/health` | Integration status · liveness |

Errors are JSON `{"detail": "...", "request_id": "..."}` with appropriate status codes
(400/401/403/404/409/413/422/429/502/503).

---

## Tests

```bash
# Backend (from backend/, venv active)
pytest                                          # unit, security, isolation, CSV, crypto, signals
FOLIOLENS_LIVE_TESTS=1 pytest tests/test_live_providers.py   # real Yahoo Finance calls (needs internet)
#   add AI_API_KEY=... to also exercise the Anthropic integration

# Frontend (from frontend/)
npm test
npm run build
```

Unit tests replace external providers with deterministic fakes **inside the test suite only**; the running
application always uses real providers.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ConfigError: JWT_SECRET_KEY is missing…` | Create `backend/.env` from `.env.example` and generate the secrets (see Installation). |
| `no such table: users` | Run `alembic upgrade head` in `backend/`. |
| "Missing or invalid CSRF token" | Reload the page (the SPA fetches a new token automatically). Make sure you open the app via the Vite URL, not the API port. |
| Logged out immediately / cookies not set | Use the same origin for SPA and API (Vite proxy in dev). Don't set `COOKIE_SECURE=true` on plain HTTP. |
| Prices show "unavailable"/"stale" | Yahoo may be rate-limiting or unreachable; wait and use **Refresh**. Check **Settings → Data integrations** for the last error. |
| A ticker shows "no price" | The symbol may have changed (merger/demerger) or needs an exchange suffix (`.NS`, `.BO`). Edit it on My Portfolio. |
| Yahoo errors mention `curl_cffi` | `pip install -r requirements.txt` (yfinance needs `curl_cffi` for reliable access). |
| AI insights say "not configured" | Set `AI_API_KEY` in `backend/.env` and restart the backend. |
| `429 Too many requests` | Rate limit hit; wait for the `Retry-After` period. Adjust limits in `.env` if needed. |
| `npm install` fails on Windows with esbuild / path-length errors | Move the project to a short path such as `C:\projects\foliolens`. |

---

## Limitations

- Market data defaults to an unofficial Yahoo Finance API; there is no SLA.
- Yahoo news has no summaries, author names or sentiment; Indian-market coverage is limited — Marketaux improves this.
- Mixed-currency portfolios: totals use the most common currency; other-currency holdings are listed but excluded (no FX conversion).
- Historical performance values *current* holdings at past prices; transaction history is not tracked.
- Price alerts are evaluated when you open the app; no emails or push notifications.
- Rate limiting and caching are per process.

## License

MIT
#   F o l i o l e n s - A I - p o r t f o l i o - h e a l t h - A n a l y s i s  
 