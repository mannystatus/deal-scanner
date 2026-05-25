# Deal Scanner

Reddit ingest → Neon Postgres → FastAPI on Render → React frontend on Cloudflare Pages.

## Architecture

Four independent pieces, one shared database. Each runs on its provider's free tier.

```
┌────────────────────────────┐
│  GitHub Actions cron       │  ← every 10 min, ~30s per run
│  (worker.py)               │
└──────────────┬─────────────┘
               │ writes
               ▼
       ┌───────────────┐
       │ Neon Postgres │  ← free tier: 0.5 GB, scale-to-zero
       └───────┬───────┘
               │ reads
               ▼
┌──────────────────────────────┐
│  Render web service          │  ← FastAPI, free tier (cold starts)
│  (api.py)                    │     or Starter $7/mo (always on)
└──────────────┬───────────────┘
               │ JSON over HTTPS
               ▼
┌──────────────────────────────┐
│  Cloudflare Pages            │  ← static, free, global CDN
│  (frontend/)                 │
└──────────────────────────────┘
```

Why this split: the worker is idle 99% of the time, so paying for a 24/7 cron is wasteful. The API needs to be reachable but is cheap. The DB is tiny. The frontend is flat files. Total cost at MVP: **$0/month**. Flip the Render service to Starter once cold starts annoy you: **$7/month**.

## Layout

```
deal_scanner/
├── models.py                    # SQLAlchemy + Pydantic models
├── schemas.py                   # Public API response shapes
├── parsers.py                   # Per-subreddit title parsers
├── reddit_source.py             # Reddit JSON client + ingest
├── db.py                        # Engine, session, idempotent upsert
├── worker.py                    # Ingest entry point (runs on GitHub Actions)
├── api.py                       # FastAPI read API (runs on Render)
├── frontend/
│   ├── index.html               # React SPA (no build step)
│   ├── config.js                # Runtime config — points at the API
│   └── _headers                 # Cloudflare Pages headers + caching
├── .github/workflows/
│   └── ingest.yml               # Cron worker, every 10 min
├── render.yaml                  # Render blueprint (API only)
├── test_parsers.py
├── requirements.txt
└── .env.example
```

## Local quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Seed local SQLite with a real Reddit pull
python worker.py

# 2. Start the API
uvicorn api:app --reload

# 3. Serve the frontend
python -m http.server 5173 --directory frontend
# Open http://localhost:5173 — auto-detects localhost and hits localhost:8000
```

## Deploy walkthrough (~20 min, all free)

### 1. Neon (database) — 3 min
1. Sign up at [neon.tech](https://neon.tech), create a project.
2. Copy the connection string (Dashboard → Connection Details → "Direct connection"). It looks like `postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require`.
3. Hold onto it — you'll paste it into Render *and* GitHub.

### 2. Push to GitHub
```bash
git init && git add . && git commit -m "initial"
gh repo create deal-scanner --public --source=. --push
```

### 3. Render (API) — 5 min
1. [render.com](https://render.com) → New → Blueprint → connect the GitHub repo.
2. It reads `render.yaml` and creates the `deal-scanner-api` web service.
3. Before first deploy, set two env vars:
   - `DATABASE_URL` = your Neon connection string
   - `CORS_ORIGINS` = leave as `https://deal-scanner.pages.dev` for now (update in step 5)
4. Deploy. Note the URL — something like `https://deal-scanner-api.onrender.com`.

### 4. GitHub Actions (worker) — 2 min
1. Repo → Settings → Secrets and variables → Actions → New repository secret. Add:
   - `DATABASE_URL` = same Neon connection string
   - `REDDIT_USER_AGENT` = `deal-scanner/0.1 (contact: you@example.com)`
2. Repo → Actions → "Reddit ingest" → Run workflow. This seeds the DB with the first batch so the API has something to return. After that it runs automatically every 10 min.

### 5. Cloudflare Pages (frontend) — 5 min
1. [Cloudflare dashboard](https://dash.cloudflare.com) → Workers & Pages → Create → Pages → Connect to Git → select repo.
2. Build settings:
   - Build command: *(leave empty)*
   - Build output directory: `frontend`
3. Deploy. Note the URL — `https://deal-scanner.pages.dev` or similar.
4. Edit `frontend/config.js` so `window.API_BASE` points at your Render URL, commit and push. Cloudflare auto-redeploys on push.
5. Go back to Render → set `CORS_ORIGINS` to the actual Pages URL → "Manual Deploy" → "Deploy latest commit".

That's it. Open the Pages URL and you should see live deals.

## Configuration reference

| Variable | Where | Notes |
|---|---|---|
| `DATABASE_URL` | Render env, GitHub secret | Neon connection string; same value in both |
| `CORS_ORIGINS` | Render env | Cloudflare Pages URL(s), comma-separated |
| `REDDIT_USER_AGENT` | GitHub secret | Reddit asks for a descriptive UA; include your email |
| `SUBREDDITS` | GitHub workflow | Comma-separated list, edit in `.github/workflows/ingest.yml` |
| `FETCH_LIMIT` | GitHub workflow | Max posts per subreddit per cycle (100 cap) |
| `window.API_BASE` | `frontend/config.js` | Render API URL — edit this file, push, CF redeploys |

## API surface

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness + deal count + latest ingest time |
| `GET /categories` | Active deal counts per category |
| `GET /deals` | Paginated, filterable feed (newest first) |
| `GET /deals/{id}` | Single deal detail |
| `GET /docs` | OpenAPI explorer |

`/deals` query params: `category`, `source`, `min_discount`, `max_price`, `search`, `min_confidence` (default 0.5), `limit` (max 100), `offset`.

## Tests

```bash
pytest test_parsers.py -v
```

## Migration paths

**API cold starts annoy you.** Flip Render service from `free` to `starter` in `render.yaml` (or in the dashboard). $7/mo, always-on.

**Outgrow Neon free tier.** You'd need >0.5 GB or >100 CU-hours/month (~3,000 hours of active DB time). Upgrade to Neon Launch ($19/mo) or migrate to Render Postgres ($7/mo) — either is a connection-string swap.

**Custom domain.** Both Render and Cloudflare Pages support custom domains for free. Add DNS records and point them. Update `CORS_ORIGINS` to the new domain.

**Worker outgrows GitHub Actions.** If you push the cycle to every 1-2 min or add lots of sources, you'll start eating into the 2,000 min/month quota on private repos (public repos stay free). At that point, move the worker to Render (`type: cron` in `render.yaml`) or a tiny Hetzner VPS.

## Next steps

1. **URL normalization** — resolve `amzn.to`/`bit.ly` and strip `utm_*` before storage.
2. **Cross-source fuzzy dedup** — `rapidfuzz` over `dedup_hash` buckets.
3. **Amazon PA-API source** — same `ParsedDeal` contract.
4. **Affiliate link wrapping** — populate `affiliate_url` once Associates is approved.
5. **Email digest worker** — second GitHub Actions cron, sends daily/weekly digests.
