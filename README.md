# FolioLens --- AI Portfolio Health Analyzer

FolioLens is a web application that analyzes stock portfolios using
market prices, financial news, and portfolio-risk metrics. Users can
upload a CSV file to view portfolio value, profit/loss, diversification,
risk, and stock insights.

> **Disclaimer:** FolioLens provides decision support, not financial
> advice. It does not execute trades.

## Features

-   **Dashboard:** Portfolio value, invested amount, profit/loss, sector
    allocation, and top holdings.
-   **Portfolio Management:** Add, edit, delete, search, and filter
    stock holdings.
-   **CSV Import/Export:** Import broker CSV files, validate holdings,
    and export reports.
-   **Portfolio Health:** Health score, diversification, concentration,
    beta, volatility, and drawdown.
-   **Stock Insights:** Price trends, financial news, risk factors, and
    transparent buy/hold/sell signals.
-   **Watchlist:** Track stocks and configure price alerts.
-   **Reports:** Download portfolio, P/L, allocation, and performance
    reports.
-   **Account Security:** Registration, login, password management,
    sessions, and account deletion.

## Tech Stack

  Layer         Technologies
  ------------- ----------------------------------------------
  Frontend      React 18, Vite, Axios, Recharts
  Backend       Python, FastAPI
  Database      SQLite, SQLAlchemy, PostgreSQL support
  Security      JWT, Argon2id, AES-256-GCM
  Market Data   Yahoo Finance (`yfinance`), optional Finnhub
  News          Yahoo Finance, optional Marketaux
  AI            Optional Anthropic Claude
  Testing       Pytest, Vitest

## Architecture

``` text
React + Vite Frontend
        |
        | REST API
        v
FastAPI Backend
        |
        +-- Routers
        +-- Services
        +-- Security and Authentication
        +-- SQLAlchemy Database
        +-- Alembic Migrations
        |
        v
Market Data / News / Optional AI Providers
```

## Project Structure

``` text
foliolens/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── routers/
│   │   └── services/
│   ├── alembic/
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── components/
│       ├── context/
│       ├── pages/
│       └── services/
├── sample_portfolio.csv
└── README.md
```

## Setup and Installation

### Requirements

-   Python 3.10+
-   Node.js 20.19+ and npm
-   Internet connection for market data and news

### 1. Backend

``` bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
```

Create the environment file:

``` bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Generate the required secrets and add them to `backend/.env`:

``` bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
```

Use the first value for `JWT_SECRET_KEY` and the second for
`CSV_ENCRYPTION_KEY`.

Initialize the database and run the API:

``` bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Backend: `http://localhost:8000`\
API documentation: `http://localhost:8000/docs`

### 2. Frontend

Open another terminal:

``` bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`, register an account, and import
`sample_portfolio.csv`.

## API Providers

Yahoo Finance is used by default and does not require an API key.

Optional integrations:

-   **Anthropic Claude:** Set `AI_API_KEY` for AI-generated
    explanations.
-   **Marketaux:** Set `FINANCIAL_NEWS_PROVIDER=marketaux` and
    `FINANCIAL_NEWS_API_KEY`.
-   **Finnhub:** Set `MARKET_DATA_PROVIDER=finnhub` and
    `MARKET_DATA_API_KEY`.

Keep all keys and secrets in `backend/.env`. Never commit this file.

## Security

-   Passwords are hashed using Argon2id.
-   JWT authentication uses secure HttpOnly cookies.
-   Refresh tokens are rotated and sessions can be revoked.
-   CSRF protection and API rate limiting are enabled.
-   User data is isolated by authenticated user ID.
-   Uploaded CSV data is encrypted using AES-256-GCM while awaiting
    confirmation.
-   HTTPS/TLS should be enabled in production.

## Running Tests

Backend, from `backend/`:

``` bash
pytest
```

Frontend, from `frontend/`:

``` bash
npm test
npm run build
```

Optional live market-provider tests:

``` bash
FOLIOLENS_LIVE_TESTS=1 pytest tests/test_live_providers.py
```

## Important Notes

-   Market prices may be marked **stale** if a provider is unavailable.
-   Holdings without a current price are marked **unpriced** and
    excluded from totals.
-   Yahoo Finance is an unofficial data source and may be rate-limited.
-   Historical performance uses current holdings at past prices;
    transaction history is not tracked.
-   Price alerts are checked when the app is opened.
-   FolioLens is an analytical tool, not investment advice.

## License

MIT
