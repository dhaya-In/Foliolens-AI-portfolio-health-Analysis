# FolioLens upgrade — implementation report (2026-10-28)

## 1. Audit of the original project

| Area | Original state | Status |
|---|---|---|
| Stack | FastAPI + pandas + yfinance 0.2.51 backend; React 18 + Vite + Recharts frontend | kept |
| CSV upload / column detection | Worked; validation only checked the `.csv` extension | kept & hardened |
| Market data | yfinance; **silently used the purchase price as the current price** when a ticker failed; `.info` per ticker (slow); no timeouts, retries or caching; old yfinance version fails against Yahoo today | fixed |
| Metrics engine | Health score, HHI diversification, concentration, beta — worked; beta defaulted to 1.0 when unknown | kept, unknown beta no longer faked |
| AI insights | Claude call with hardcoded model; template fallback presented like AI output | reworked, configurable, labelled |
| Auth / users / DB | None — single anonymous flow, nothing persisted | added |
| News, watchlist, reports | None | added |
| UI | One 3-step page flow with a single crowded dashboard | redesigned into 8 sidebar sections |
| Config | `.env` contained only the placeholder `your-key-here` (no real secret exposed); `node_modules` shipped in the ZIP | cleaned |

## 2. What was implemented

- **Backend** (modular `core/`, `db/`, `routers/`, `services/`): SQLAlchemy models + Alembic migration; Argon2id
  passwords; JWT access tokens + rotating refresh tokens with reuse detection, server-side session revocation,
  HttpOnly cookies, CSRF double-submit; rate limits; per-user data isolation on every query; AES-256-GCM encrypted
  staged CSV uploads with TTL purge; formula-injection-safe CSV exports and reports; security headers, HTTPS
  enforcement, structured JSON logs, consistent safe error bodies.
- **Integrations**: Yahoo Finance (quotes, history, fundamentals, search, news) with timeouts, bounded retries,
  TTL caching, stale fallback and provider-status tracking; optional Finnhub (market data), Marketaux (news with
  sentiment) and Anthropic Claude (insights, signal interpretation with structured JSON output and refusal fallback).
- **Signals**: deterministic 9-factor decision-support engine with evidence quality, risks, monitoring points,
  "wait for a lower price" check and sources; AI interpretation kept separate.
- **Frontend**: login/register, collapsible sidebar (mobile drawer), Overview, My Portfolio, CSV Import & Export,
  Portfolio Health, Stock News & Insights, Market Watchlist, Reports & Analytics, Profile & Settings; loading,
  empty, error, stale and toast states; keyboard/ARIA support; silent token refresh and session-expired handling.

## 3. Test results (actually executed on 2026-10-28)

| Suite | Command | Result |
|---|---|---|
| Backend unit/security | `pytest` | **54 passed**, 4 skipped (live tests are opt-in) |
| Backend live providers | `FOLIOLENS_LIVE_TESTS=1 pytest tests/test_live_providers.py` | **3 passed**, 1 skipped (Anthropic — no key). One earlier run failed on a local network connection reset; three subsequent runs passed. |
| Frontend | `npm test` | **7 passed** |
| Frontend build | `npm run build` | success, no warnings |
| Dependency audit | `npm audit` | 0 vulnerabilities |
| End-to-end (browser, manual) | register → import sample CSV → Overview/Portfolio/Health/Insights/Watchlist/Reports/Settings with live data → wrong password → correct login → server-side logout → "session expired" redirect; mobile 375px layout | all worked; bugs found here were fixed (naive timestamps shown 5½ h off, empty India market news, duplicate React keys, wrong tab title) |
| AI error path | real Anthropic call with a deliberately invalid key | returned the "rejected AI_API_KEY" error as designed |

Security behaviours covered by automated tests: Argon2id hashing, duplicate/weak/missing registration input,
generic login errors, protected endpoints, expired/tampered/wrong-audience/`alg=none` tokens, logout invalidation,
refresh rotation + reuse detection, CSRF enforcement, login rate limiting, password-change session revocation,
security headers, AES-GCM integrity (tamper, wrong key, wrong owner), invalid/oversized/binary uploads, row errors,
upload expiry, formula-injection escaping, filename sanitising, and cross-user access to holdings, uploads,
watchlists, exports, reports, activity and sessions.

## 4. Not verified

- **Anthropic AI insights with a valid key** — no key available; integration is implemented and its error path was tested.
- **Marketaux news** and **Finnhub market data** — no keys available; implemented from their documented REST APIs, untested live.
- **PostgreSQL** — code is database-agnostic via SQLAlchemy, but only SQLite was run.
- **Production HTTPS deployment** — configuration and `deploy/nginx.conf.example` provided; not deployed.
