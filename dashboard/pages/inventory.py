"""Inventory Dashboard — warehouse-level stock, low-stock highlighting."""

import streamlit as st
from dashboard.db_utils import query_df, load_settings


def render():
    st.header("Inventory Dashboard")

    settings = load_settings()
    low_stock_threshold = settings.get("low_stock_threshold", 50)

    # ── Filters ──────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)

    styles = query_df("SELECT DISTINCT style FROM inventory ORDER BY style")
    style_list = ["All"] + styles["style"].tolist() if not styles.empty else ["All"]
    style_filter = col1.selectbox("Style", style_list)

    warehouses = query_df("SELECT DISTINCT warehouse_name FROM inventory WHERE warehouse_name IS NOT NULL ORDER BY warehouse_name")
    wh_list = ["All"] + warehouses["warehouse_name"].tolist() if not warehouses.empty else ["All"]
    wh_filter = col2.selectbox("Warehouse", wh_list)

    low_stock_only = col3.checkbox(f"Low stock only (< {low_stock_threshold})")

    # ── Build query ──────────────────────────────────────────
    where_clauses = []
    params = []

    if style_filter != "All":
        where_clauses.append("style = ?")
        params.append(style_filter)
    if wh_filter != "All":
        where_clauses.append("warehouse_name = ?")
        params.append(wh_filter)
    if low_stock_only:
        where_clauses.append("quantity < ?")
        params.append(low_stock_threshold)

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    inventory = query_df(f"""
        SELECT
            supplier,
            style,
            color,
            size,
            warehouse,
            warehouse_name,
            quantity,
            is_closeout,
            last_synced
        FROM inventory
        {where}
        ORDER BY style, color, size, warehouse
        LIMIT 1000
    """, tuple(params))

    # ── Summary metrics ──────────────────────────────────────
    total_inv = query_df("SELECT SUM(quantity) AS total, COUNT(DISTINCT style) AS styles FROM inventory")

    col1, col2, col3 = st.columns(3)
    if not total_inv.empty:
        col1.metric("Total Units in Stock", f"{int(total_inv.iloc[0]['total'] or 0):,}")
        col2.metric("Styles with Inventory", int(total_inv.iloc[0]["styles"] or 0))

    low_stock_count = query_df(
        "SELECT COUNT(*) AS cnt FROM inventory WHERE quantity > 0 AND quantity < ?",
        (low_stock_threshold,),
    )
    col3.metric(f"Low Stock SKUs (< {low_stock_threshold})", int(low_stock_count.iloc[0]["cnt"]))

    # ── Warehouse summary ────────────────────────────────────
    st.subheader("Stock by Warehouse")

    wh_summary = query_df("""
        SELECT
            warehouse_name,
            warehouse,
            COUNT(DISTINCT style) AS styles,
            SUM(quantity) AS total_units,
            SUM(CASE WHEN quantity < ? THEN 1 ELSE 0 END) AS low_stock_skus
        FROM inventory
        WHERE warehouse_name IS NOT NULL
        GROUP BY warehouse_name
        ORDER BY total_units DESC
    """, (low_stock_threshold,))

    if not wh_summary.empty:
        st.dataframe(
            wh_summary,
            use_container_width=True,
            hide_index=True,
            column_config={
                "total_units": st.column_config.NumberColumn("Total Units", format="%d"),
            },
        )

    # ── Detail table ─────────────────────────────────────────
    st.subheader("Inventory Detail")

    if inventory.empty:
        st.info("No inventory data found. Adjust filters or run a sync first.")
    else:
        st.caption(f"Showing {len(inventory)} rows (limit 1,000)")

        def highlight_low_stock(row):
            if 0 < row["quantity"] < low_stock_threshold:
                return ["background-color: #fff3cd"] * len(row)
            elif row["quantity"] == 0:
                return ["background-color: #ffcccc"] * len(row)
            return [""] * len(row)

        st.dataframe(
            inventory.style.apply(highlight_low_stock, axis=1),
            use_container_width=True,
            hide_index=True,
        )
