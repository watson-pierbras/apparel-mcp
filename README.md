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
python -m src.server.mcp_server
```

The server uses **stdio transport** (reads JSON-RPC from stdin, writes to stdout). This is the protocol Claude Desktop expects — you don't need to run it manually if Claude Desktop is configured to launch it (see below).

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
│       └── mcp_server.py          # FastMCP server — 10 tools, stdio transport
│
├── scripts/
│   ├── setup_db.py                # Initialize database (run once)
│   ├── add_styles.py              # CLI to add tracked styles
│   └── run_sync.py                # Manual or cron sync runner
│
└── tests/                         # Test suite (pytest + pytest-asyncio)
```

---

## Roadmap

- [x] **Phase 1** — SanMar SOAP client, SQLite sync, 10 MCP tools
- [ ] **Phase 2** — S&S Activewear REST client and sync engine
- [ ] **Phase 3** — Automated cron sync with error notifications
- [ ] Unit tests and integration test suite
- [ ] Docker container for deployment

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
