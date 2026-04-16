"""Database connection management and schema setup for apparel-mcp."""

import os
import sqlite3
import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "./data/apparel.db")

SCHEMA_SQL = """
-- ============================================================
-- TRACKED STYLES
-- ============================================================
CREATE TABLE IF NOT EXISTS tracked_styles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier    TEXT NOT NULL CHECK(supplier IN ('sanmar', 'ssactivewear')),
    style       TEXT NOT NULL,
    brand       TEXT,
    title       TEXT,
    description TEXT,
    category    TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT 1,
    added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_synced TIMESTAMP,
    UNIQUE(supplier, style)
);

-- ============================================================
-- PRODUCTS (SKU-level with pricing)
-- ============================================================
CREATE TABLE IF NOT EXISTS products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tracked_style_id    INTEGER REFERENCES tracked_styles(id) ON DELETE CASCADE,
    supplier            TEXT NOT NULL CHECK(supplier IN ('sanmar', 'ssactivewear')),
    style               TEXT NOT NULL,
    brand               TEXT,
    color               TEXT NOT NULL,
    catalog_color       TEXT,
    size                TEXT NOT NULL,
    sku                 TEXT,
    gtin                TEXT,
    piece_price         REAL,
    case_price          REAL,
    sale_price          REAL,
    sale_end_date       TEXT,
    customer_price      REAL,
    map_price           REAL,
    case_qty            INTEGER,
    price_code          TEXT,
    price_text          TEXT,
    size_price_code     TEXT,
    weight              REAL,
    product_status      TEXT,
    country_of_origin   TEXT,
    front_image_url     TEXT,
    back_image_url      TEXT,
    swatch_image_url    TEXT,
    spec_sheet_url      TEXT,
    noe_retailing       BOOLEAN DEFAULT 0,
    last_synced         TIMESTAMP,
    UNIQUE(supplier, style, color, size)
);

-- ============================================================
-- INVENTORY (warehouse-level)
-- ============================================================
CREATE TABLE IF NOT EXISTS inventory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER REFERENCES products(id) ON DELETE CASCADE,
    supplier        TEXT NOT NULL CHECK(supplier IN ('sanmar', 'ssactivewear')),
    style           TEXT NOT NULL,
    color           TEXT NOT NULL,
    size            TEXT NOT NULL,
    warehouse       TEXT NOT NULL,
    warehouse_name  TEXT,
    quantity        INTEGER NOT NULL DEFAULT 0,
    is_closeout     BOOLEAN NOT NULL DEFAULT 0,
    is_dropship     BOOLEAN NOT NULL DEFAULT 0,
    last_synced     TIMESTAMP,
    UNIQUE(supplier, style, color, size, warehouse)
);

-- ============================================================
-- PRICE HISTORY (append-only change log)
-- ============================================================
CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier    TEXT NOT NULL,
    style       TEXT NOT NULL,
    color       TEXT NOT NULL,
    size        TEXT NOT NULL,
    price_type  TEXT NOT NULL CHECK(price_type IN ('piece', 'case', 'sale', 'customer', 'map')),
    old_price   REAL,
    new_price   REAL,
    changed_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- PRICE ALERTS
-- ============================================================
CREATE TABLE IF NOT EXISTS price_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier        TEXT NOT NULL,
    style           TEXT NOT NULL,
    color_name      TEXT,
    size            TEXT,
    min_price       REAL,
    max_price       REAL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(supplier, style, color_name, size)
);

-- ============================================================
-- ALERT HISTORY
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id        INTEGER NOT NULL REFERENCES price_alerts(id),
    triggered_at    TEXT NOT NULL DEFAULT (datetime('now')),
    old_price       REAL NOT NULL,
    new_price       REAL NOT NULL,
    direction       TEXT NOT NULL,
    style           TEXT NOT NULL,
    color_name      TEXT,
    size            TEXT
);

-- ============================================================
-- SYNC LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier        TEXT NOT NULL,
    sync_type       TEXT NOT NULL CHECK(sync_type IN ('full', 'incremental', 'inventory_only')),
    styles_synced   INTEGER NOT NULL DEFAULT 0,
    skus_updated    INTEGER NOT NULL DEFAULT 0,
    price_changes   INTEGER NOT NULL DEFAULT 0,
    errors          INTEGER NOT NULL DEFAULT 0,
    error_details   TEXT,
    started_at      TIMESTAMP NOT NULL,
    completed_at    TIMESTAMP,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK(status IN ('running', 'completed', 'failed'))
);
"""

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_products_supplier_style
    ON products(supplier, style);
CREATE INDEX IF NOT EXISTS idx_products_style_color_size
    ON products(style, color, size);
CREATE INDEX IF NOT EXISTS idx_products_sku
    ON products(sku) WHERE sku IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_gtin
    ON products(gtin) WHERE gtin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_piece_price
    ON products(supplier, piece_price) WHERE piece_price IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_inventory_supplier_style_warehouse
    ON inventory(supplier, style, warehouse);
CREATE INDEX IF NOT EXISTS idx_inventory_product_id
    ON inventory(product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_style_color_size
    ON inventory(style, color, size);
CREATE INDEX IF NOT EXISTS idx_price_history_changed_at
    ON price_history(changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_price_history_supplier_style
    ON price_history(supplier, style, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_log_supplier_completed
    ON sync_log(supplier, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_styles_supplier_active
    ON tracked_styles(supplier, is_active);
CREATE INDEX IF NOT EXISTS idx_price_alerts_supplier_style
    ON price_alerts(supplier, style);
CREATE INDEX IF NOT EXISTS idx_alert_history_triggered
    ON alert_history(triggered_at DESC);
"""

PRAGMAS_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
"""


def get_db_path() -> str:
    """Resolve the database path, creating parent directories if needed."""
    path = os.getenv("DB_PATH", DB_PATH)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def init_db_sync(db_path: str | None = None) -> None:
    """Initialize database synchronously (for setup scripts)."""
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    try:
        for pragma in PRAGMAS_SQL.strip().split("\n"):
            pragma = pragma.strip()
            if pragma and not pragma.startswith("--"):
                conn.execute(pragma)
        conn.executescript(SCHEMA_SQL)
        conn.executescript(INDEXES_SQL)
        conn.commit()
    finally:
        conn.close()


async def init_db(db_path: str | None = None) -> None:
    """Initialize database asynchronously."""
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        for pragma in PRAGMAS_SQL.strip().split("\n"):
            pragma = pragma.strip()
            if pragma and not pragma.startswith("--"):
                await db.execute(pragma)
        await db.executescript(SCHEMA_SQL)
        await db.executescript(INDEXES_SQL)
        await db.commit()


@asynccontextmanager
async def get_db(db_path: str | None = None):
    """Async context manager for database connections."""
    path = db_path or get_db_path()
    db = await aiosqlite.connect(path)
    try:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        yield db
    finally:
        await db.close()
