# Deploying Apparel MCP to Railway

This guide walks through hosting the apparel-mcp server on
[Railway](https://railway.app) so it is always online and reachable by
Perplexity as a remote MCP connector.

## Why this is different from the Printavo MCP

The apparel-mcp server uses a **SQLite database** on disk, so it needs
**persistent storage** on Railway (a Volume). It also talks to the
SanMar SOAP API and the S&S REST API with your dealer credentials, so
we **must** protect the public endpoint with a Bearer token.

## One-time setup

### 1. Push to GitHub

Railway deploys from a GitHub repo. Make sure this repo is pushed to
GitHub and that `.env` is in `.gitignore` (it already is).

### 2. Create a new Railway project

1. Sign in at [railway.app](https://railway.app).
2. Click **New Project → Deploy from GitHub repo**.
3. Pick `apparel-mcp`. Railway will detect the `Dockerfile` and start
   building.

### 3. Add a Volume for the SQLite database

1. In your service, open the **Volumes** tab.
2. Click **New Volume**.
3. Set the **mount path** to `/app/data`.
4. Size: 1 GB is plenty (SQLite + product data is tiny).

Without this, the database gets wiped on every redeploy.

### 4. Set environment variables

In **Variables**, add:

| Variable | Value |
|---|---|
| `SANMAR_CUSTOMER_NUMBER` | your SanMar customer number |
| `SANMAR_USERNAME` | your SanMar integration username |
| `SANMAR_PASSWORD` | your SanMar integration password |
| `SS_ACCOUNT_NUMBER` | your S&S account number |
| `SS_API_KEY` | your S&S API key |
| `MCP_API_KEY` | a long random secret — Perplexity will send this as a Bearer token |
| `DB_PATH` | `/app/data/apparel.db` (matches the Volume mount) |

Do **not** set `PORT` — Railway injects it automatically.

Generate `MCP_API_KEY` with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Generate a public domain

In **Settings → Networking → Generate Domain**, you'll get a URL like
`apparel-mcp-production.up.railway.app`. The MCP endpoint is at
`https://<that-domain>/mcp`.

### 6. Seed the database

The Dockerfile runs `scripts/setup_db.py` at build time, which creates
the schema but leaves the tables empty. To populate it you need to run
the sync. Two options:

**Option A — one-off sync from your Mac (simplest):**

```bash
# Copy the DB out of Railway after a local sync, or
# run sync locally and commit styles you track, then sync on the server
# via Railway's "Run Command" button under the service.
```

**Option B — scheduled sync on Railway (recommended for production):**

Add a Railway **Cron** service pointing at the same repo, with the
start command set to your sync script (e.g.
`python scripts/sync.py --supplier sanmar`). Point it at the same
Volume so it writes to the same database the MCP server reads from.

### 7. Connect Perplexity

In Perplexity, go to **Settings → Connectors** and update the Apparel
MCP connector:

- **Server URL:** `https://<your-railway-domain>/mcp`
- **Authentication:** Bearer token
- **Token:** the `MCP_API_KEY` value from step 4

That's it. The server will restart automatically whenever you
`git push`, and the Volume keeps your synced data safe between
deploys.

## Smoke test from your terminal

```bash
# Health check (should return JSON)
curl https://<your-railway-domain>/

# Tools list (should 401 without a token)
curl -X POST https://<your-railway-domain>/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# Tools list with auth (should succeed)
curl -X POST https://<your-railway-domain>/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_API_KEY" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```
