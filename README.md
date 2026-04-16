# Apparel MCP

SQLite-backed MCP server for wholesale apparel data from **SanMar** and **S&S Activewear**. Built for Compound Sportswear (CMP).

Rather than hitting supplier APIs on every query, this server syncs product, pricing, and inventory data into a local SQLite database. Claude Desktop (or any MCP-compatible client) can then query that data instantly through 10 purpose-built tools.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuring Credentials (.env)](#configuring-credentials-env)
- [Database Setup](#database-setup)
- [Adding Styles to Track](#adding-styles-to-track)
- [Running Sync](#running-sync)
- [Starting the MCP Server](#starting-the-mcp-server)
- [Claude Desktop Configuration](#claude-desktop-configuration)
- [Available MCP Tools](#available-mcp-tools)
- [Automating Sync with Cron](#automating-sync-with-cron)
- [GitHub Actions (Automated Sync)](#github-actions-automated-sync)
- [Running with Podman](#running-with-podman)
- [Project Structure](#project-structure)

---

## Prerequisites

- **Python 3.11+**
- **SanMar API credentials** — Requires a signed integration agreement. Contact [sanmarintegrations@sanmar.com](mailto:sanmarintegrations@sanmar.com) to request access. You'll receive a customer number, username, and password.
- **S&S Activewear API credentials** — Account number and API key from your S&S dealer portal. *(Phase 2 — sync not yet implemented, but credentials can be configured now.)*

---

## Installation

```bash
# Clone the repo
git clone https://github.com/watson-pierbras/apparel-mcp.git
cd apparel-mcp

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows

# Install the package and all dependencies
pip install -e .

# For development (adds pytest)
pip install -e ".[dev]"
```

This installs all required packages:

| Package | Purpose |
|---------|---------|
| `mcp[cli]` | FastMCP SDK — stdio transport for Claude Desktop |
| `zeep` | SOAP/XML client for SanMar API |
| `httpx` | Async HTTP client for S&S REST API (Phase 2) |
| `aiosqlite` | Async SQLite driver |
| `pydantic` | Data models and validation |
| `python-dotenv` | Loads `.env` credentials |
| `tenacity` | Retry logic for flaky API calls |

---

## Configuring Credentials (.env)

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Open `.env` in your editor:

```ini
# SanMar SOAP API credentials
SANMAR_CUSTOMER_NUMBER=12345
SANMAR_USERNAME=your-sanmar-username
SANMAR_PASSWORD=your-sanmar-password

# S&S Activewear REST API credentials (Phase 2)
SS_ACCOUNT_NUMBER=your-ss-account-number
SS_API_KEY=your-ss-api-key

# Database path (relative to project root)
DB_PATH=./data/apparel.db
```

### Where to find your credentials

**SanMar:**
1. Email [sanmarintegrations@sanmar.com](mailto:sanmarintegrations@sanmar.com) to request API access
2. Sign the integration agreement they send back
3. You'll receive your **customer number**, **username**, and **password**
4. These authenticate against the SOAP services at `ws.sanmar.com:8080`

**S&S Activewear:**
1. Log into your S&S dealer account at [ssactivewear.com](https://www.ssactivewear.com)
2. Navigate to your account/API settings to find your account number and API key
3. These authenticate via HTTP Basic Auth against `api.ssactivewear.com/v2/`

> **Security:** The `.env` file is in `.gitignore` and will never be committed. Do not share your credentials or commit them to version control.

---

## Database Setup

Initialize the SQLite database with all tables, indexes, and WAL mode:

```bash
python scripts/setup_db.py
```

Output:
```
Initializing database at: ./data/apparel.db
Database initialized successfully.
  - Tables: tracked_styles, products, inventory, price_history, sync_log
  - WAL mode enabled
  - Foreign keys enabled
```

The database is created at `data/apparel.db` (configurable via `DB_PATH` in `.env`). WAL mode allows concurrent reads during sync writes.

---

## Adding Styles to Track

Before syncing, tell the system which styles you care about. Only tracked styles are synced — this keeps the database focused and API calls minimal.

```bash
# Add a single style
python scripts/add_styles.py sanmar PC61 --brand "Port & Company"

# Add multiple styles at once (comma-separated)
python scripts/add_styles.py sanmar PC61,K420,ST350,PC54,DT6000 --brand "Port & Company"

# Add an S&S style (sync not yet active, but tracked for Phase 2)
python scripts/add_styles.py ssactivewear "5000" --brand "Gildan" --category "T-Shirts"
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `supplier` | Yes | `sanmar` or `ssactivewear` |
| `styles` | Yes | Style number(s), comma-separated for batch |
| `--brand` | No | Brand name (e.g., "Port & Company", "Sport-Tek") |
| `--category` | No | Category (e.g., "T-Shirts", "Polos") |

If a style is already tracked, it's skipped with a message — no duplicates.

---

## Running Sync

The sync script pulls product info, pricing, and inventory from supplier APIs and writes it to the local database. It detects price changes and logs them to `price_history` automatically.

### SanMar Sync

```bash
# Full sync — products, pricing, and inventory for all tracked SanMar styles
python scripts/run_sync.py --supplier sanmar

# Inventory-only refresh (faster, skips product/pricing data)
python scripts/run_sync.py --supplier sanmar --type inventory_only

# Incremental sync — only re-syncs pricing (catches sale price updates)
python scripts/run_sync.py --supplier sanmar --type incremental
```

### S&S Activewear Sync

```bash
# Not yet implemented — Phase 2
python scripts/run_sync.py --supplier ssactivewear
```

### Sync All Suppliers

```bash
# Runs both SanMar and S&S (skips S&S until Phase 2 is built)
python scripts/run_sync.py
```

### Sync Types

| Type | What It Does | When to Use |
|------|-------------|-------------|
| `full` (default) | Syncs products, pricing, and inventory | Daily sync, first-time setup |
| `incremental` | Pricing data only | Catching sale/promo price updates |
| `inventory_only` | Warehouse inventory counts only | Mid-day inventory refresh |

### Sync Output

```
2026-04-16 12:00:00 [sanmar.sync] INFO: Starting full sync for 5 active styles
2026-04-16 12:00:03 [sanmar.sync] INFO: Synced PC61: 24 SKUs, 2 price changes

SanMar sync completed:
  Styles synced: 5
  SKUs updated:  120
  Price changes: 2
  Errors:        0
```

---

## Starting the MCP Server

For testing or standalone use:

```bash
# stdio mode (default — for Claude Desktop)
python -m src.server.mcp_server

# streamable-http mode (for networked/container use)
python -m src.server.mcp_server --transport streamable-http --host 0.0.0.0 --port 8000
```

In stdio mode, the server reads JSON-RPC from stdin and writes to stdout — this is the protocol Claude Desktop expects. You don't need to run it manually if Claude Desktop is configured to launch it (see below).

In streamable-http mode, the server listens on a network port, which is what you want when running inside a container or serving multiple clients.

---

## Claude Desktop Configuration

Add this to your Claude Desktop config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "apparel": {
      "command": "python",
      "args": ["-m", "src.server.mcp_server"],
      "cwd": "/path/to/apparel-mcp",
      "env": {
        "DB_PATH": "./data/apparel.db",
        "SANMAR_CUSTOMER_NUMBER": "your-number",
        "SANMAR_USERNAME": "your-username",
        "SANMAR_PASSWORD": "your-password",
        "SS_ACCOUNT_NUMBER": "your-account",
        "SS_API_KEY": "your-key"
      }
    }
  }
}
```

> **Tip:** If you're using a virtual environment, point `command` to the venv Python binary:
> ```json
> "command": "/path/to/apparel-mcp/.venv/bin/python"
> ```

After saving, restart Claude Desktop. You should see "apparel" appear in the MCP tools list.

---

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `search_products` | Search by keyword, brand, category, or style number |
| `get_pricing` | All pricing tiers for a style (piece, case, dozen) |
| `check_inventory` | Cached warehouse-level stock from last sync |
| `check_live_inventory` | Real-time API call for exact counts at order time |
| `compare_pricing` | Side-by-side pricing across SanMar and S&S |
| `get_price_changes` | Recent price increases/decreases with timestamps |
| `list_tracked_styles` | Show all styles currently being tracked |
| `add_tracked_style` | Add a new style to track (via MCP, no CLI needed) |
| `get_product_details` | Full product card — colors, sizes, images, weight |
| `sync_status` | Check when the last sync ran and its results |

### Example Prompts (Claude Desktop)

Once configured, you can ask Claude:

- *"What's the current pricing on the PC61 in all colors?"*
- *"Check inventory on ST350 in Black, sizes S-XL"*
- *"Compare pricing between SanMar PC54 and the S&S equivalent"*
- *"Have any prices changed in the last week?"*
- *"Add style K500 from SanMar to our tracked list"*

---

## Automating Sync with Cron

Set up cron jobs to keep data fresh without manual runs:

```bash
# Edit your crontab
crontab -e
```

### Recommended Schedule

```cron
# Full sync daily at 5:00 AM ET (products + pricing + inventory)
0 9 * * * cd /path/to/apparel-mcp && /path/to/.venv/bin/python scripts/run_sync.py --type full >> /var/log/apparel-sync.log 2>&1

# Inventory refresh every 4 hours (quick stock level update)
0 */4 * * * cd /path/to/apparel-mcp && /path/to/.venv/bin/python scripts/run_sync.py --type inventory_only >> /var/log/apparel-sync.log 2>&1

# Price check Mon/Wed at 7:00 AM ET (catch mid-week promos)
0 11 * * 1,3 cd /path/to/apparel-mcp && /path/to/.venv/bin/python scripts/run_sync.py --supplier sanmar --type incremental >> /var/log/apparel-sync.log 2>&1
```

> **Note:** Cron times are in UTC. ET is UTC-4 (EDT) or UTC-5 (EST). Adjust accordingly.

---

## GitHub Actions (Automated Sync)

The repo includes a GitHub Actions workflow at `.github/workflows/sync.yml` that runs the sync on a schedule — no server or cron setup required.

### Schedule

| Time (ET) | UTC | Frequency | Sync Type |
|-----------|-----|-----------|-----------|
| 5:00 AM | 9:00 | Daily | Full (products + pricing + inventory) |
| Every 4h | Every 4h | 6x/day | Inventory only |
| 7:00 AM | 11:00 | Mon, Wed | Incremental (pricing check) |

### Setup

1. Go to your repo's **Settings > Secrets and variables > Actions**
2. Add these repository secrets:

| Secret | Value |
|--------|-------|
| `SANMAR_CUSTOMER_NUMBER` | Your SanMar customer number |
| `SANMAR_USERNAME` | Your SanMar API username |
| `SANMAR_PASSWORD` | Your SanMar API password |
| `SS_ACCOUNT_NUMBER` | Your S&S account number |
| `SS_API_KEY` | Your S&S API key |

3. The workflow is enabled automatically. You can also trigger it manually from the **Actions** tab with custom supplier/sync type inputs.

### How it works

- The database is persisted as a GitHub Actions artifact between runs (90-day retention), so `price_history` accumulates over time.
- Each run initializes the schema if the DB doesn't exist, then downloads the previous artifact before syncing.
- The workflow writes a summary to the GitHub Actions job summary so you can see results at a glance.

### Manual trigger

Go to **Actions > Apparel Data Sync > Run workflow** and choose the supplier and sync type from the dropdowns.

---

## Running with Podman

Running the MCP server in a rootless Podman container is a solid approach for production use. The container uses streamable-http transport so Claude Desktop connects over the network instead of stdio.

### Build the image

```bash
cd apparel-mcp
podman build -t apparel-mcp .
```

### Run the container

```bash
# Create a named volume for the SQLite database (persists across restarts)
podman volume create apparel-mcp-data

# Run the server
podman run -d \
  --name apparel-mcp \
  -p 127.0.0.1:8020:8000 \
  --env-file ~/.config/mcp-env/apparel-mcp.env \
  -v apparel-mcp-data:/app/data:Z \
  apparel-mcp
```

Create the env file at `~/.config/mcp-env/apparel-mcp.env`:

```ini
SANMAR_CUSTOMER_NUMBER=12345
SANMAR_USERNAME=your-username
SANMAR_PASSWORD=your-password
SS_ACCOUNT_NUMBER=your-account
SS_API_KEY=your-key
DB_PATH=/app/data/apparel.db
```

### Claude Desktop config (container mode)

When running via Podman, Claude Desktop connects over HTTP instead of launching a process:

```json
{
  "mcpServers": {
    "apparel": {
      "url": "http://127.0.0.1:8020/mcp"
    }
  }
}
```

### Run sync inside the container

```bash
# Full sync
podman exec apparel-mcp python scripts/run_sync.py --supplier sanmar

# Inventory-only
podman exec apparel-mcp python scripts/run_sync.py --type inventory_only
```

### Auto-start with systemd (Linux)

A systemd user service file is included at `contrib/apparel-mcp.service`. To install:

```bash
# Copy the service file
mkdir -p ~/.config/systemd/user
cp contrib/apparel-mcp.service ~/.config/systemd/user/

# Enable and start
systemctl --user daemon-reload
systemctl --user enable --now apparel-mcp

# Check status
systemctl --user status apparel-mcp

# View logs
journalctl --user -u apparel-mcp -f
```

The server will auto-start on login and restart on failure.

### Why Podman?

- **Rootless** — no daemon, no root access needed
- **Isolated credentials** — env file stays outside the container image
- **Persistent data** — named volume survives container rebuilds
- **Portable** — same Containerfile works with Docker if needed
- **systemd integration** — auto-start on login, restart on crash, proper logging

---

## Project Structure

```
apparel-mcp/
├── pyproject.toml                 # Package config, dependencies (hatchling build)
├── README.md                      # This file
├── .env.example                   # Credential template (copy to .env)
├── .gitignore                     # Excludes .env, *.db, __pycache__
│
├── data/
│   └── apparel.db                 # SQLite database (created by setup_db.py)
│
├── src/
│   ├── db.py                      # Schema, indexes, WAL pragmas, get_db() context manager
│   ├── models.py                  # Pydantic models (Product, InventoryLevel, etc.)
│   │
│   ├── shared/
│   │   └── formatters.py          # Output formatting for MCP tool responses
│   │
│   ├── sanmar/
│   │   ├── client.py              # SanMarClient — zeep SOAP client, retry logic, 3 WSDLs
│   │   ├── mapper.py              # Maps SOAP XML responses → Pydantic models
│   │   └── sync.py                # SanMarSync — sync engine, price change detection, UPSERT
│   │
│   ├── ssactivewear/              # Phase 2 — REST/JSON client via httpx
│   │
│   └── server/
│       └── mcp_server.py          # FastMCP server — 10 tools, stdio + HTTP transport
│
├── scripts/
│   ├── setup_db.py                # Initialize database (run once)
│   ├── add_styles.py              # CLI to add tracked styles
│   └── run_sync.py                # Manual or cron sync runner
│
├── .github/
│   └── workflows/
│       └── sync.yml               # GitHub Actions scheduled sync
│
├── Containerfile                  # Podman/Docker container build
├── .containerignore               # Build context exclusions
├── contrib/
│   └── apparel-mcp.service        # systemd user service for Podman
│
└── tests/                         # Test suite (pytest + pytest-asyncio)
```

---

## Roadmap

- [x] **Phase 1** — SanMar SOAP client, SQLite sync, 10 MCP tools
- [ ] **Phase 2** — S&S Activewear REST client and sync engine
- [ ] **Phase 3** — Automated cron sync with error notifications
- [ ] Unit tests and integration test suite
- [x] Podman/Docker container support
- [x] GitHub Actions automated sync

---

## Troubleshooting

**"SANMAR_CUSTOMER_NUMBER not set"**
Make sure your `.env` file exists in the project root and has all three SanMar credentials filled in. Run `cat .env` to verify (don't share the output).

**WSDL connection timeout**
SanMar's SOAP endpoints are at `ws.sanmar.com:8080`. Make sure port 8080 outbound is not blocked by your firewall/VPN.

**"Style already tracked" when adding styles**
This is normal — the script prevents duplicates. The style is already in your database and will sync on the next run.

**Database locked errors**
WAL mode should prevent this during normal use. If you see it, make sure only one sync process runs at a time (avoid overlapping cron schedules).

**Claude Desktop doesn't show apparel tools**
1. Verify the config JSON is valid (no trailing commas)
2. Make sure `cwd` points to the actual project directory
3. Restart Claude Desktop completely (quit and reopen)
4. Check Claude's MCP log for connection errors
