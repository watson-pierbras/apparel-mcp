# Apparel MCP

SQLite-backed MCP server for wholesale apparel data from SanMar and S&S Activewear. Built for Compound Sportswear (CMP).

## What This Does

- Maintains a local SQLite database with pricing and inventory for tracked styles
- Exposes 10 MCP tools for Claude Desktop and Perplexity Computer
- Scheduled sync keeps data fresh without hitting APIs on every query
- Live API fallback for real-time inventory checks at order time

## Quick Start

```bash
# 1. Install dependencies
pip install -e .

# 2. Copy and fill in credentials
cp .env.example .env
# Edit .env with your SanMar and S&S API credentials

# 3. Initialize database
python scripts/setup_db.py

# 4. Add styles to track
python scripts/add_styles.py sanmar PC61 --brand "Port & Co"
python scripts/add_styles.py sanmar PC61,K420,ST350 --brand "Port & Co"

# 5. Run initial sync
python scripts/run_sync.py --supplier sanmar

# 6. Start MCP server (for testing)
python -m src.server.mcp_server
```

## Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

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

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `search_products` | Search by keyword, brand, or category |
| `get_pricing` | Get all pricing tiers for a style |
| `check_inventory` | Cached warehouse-level inventory |
| `check_live_inventory` | Real-time API inventory (order time) |
| `compare_pricing` | Cross-supplier price comparison |
| `get_price_changes` | Recent price change history |
| `list_tracked_styles` | Show all tracked styles |
| `add_tracked_style` | Add a new style to track |
| `get_product_details` | Full product card with images |
| `sync_status` | Check sync job history |

## Sync Schedule (Cron)

```bash
# Full sync daily at 5 AM ET
0 5 * * * cd /path/to/apparel-mcp && python scripts/run_sync.py --type full

# Inventory refresh every 4 hours
0 */4 * * * cd /path/to/apparel-mcp && python scripts/run_sync.py --type inventory_only

# SanMar sale price check Mon/Wed 7 AM ET
0 7 * * 1,3 cd /path/to/apparel-mcp && python scripts/run_sync.py --supplier sanmar --type incremental
```
