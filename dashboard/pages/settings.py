"""Settings page — dashboard preferences, thresholds, data export."""

import streamlit as st
from dashboard.db_utils import query_df, load_settings, save_settings


def render():
    st.header("Settings")

    settings = load_settings()

    # ── General settings ─────────────────────────────────────
    st.subheader("General")

    with st.form("settings_form"):
        default_supplier = st.selectbox(
            "Default supplier",
            ["sanmar", "ssactivewear"],
            index=0 if settings.get("default_supplier") == "sanmar" else 1,
        )

        low_stock_threshold = st.number_input(
            "Low stock threshold (units)",
            min_value=1,
            max_value=10000,
            value=settings.get("low_stock_threshold", 50),
            help="SKUs with stock below this level are highlighted on the Inventory page",
        )

        alert_check_on_sync = st.checkbox(
            "Check price alerts after every sync",
            value=settings.get("alert_check_on_sync", True),
        )

        if st.form_submit_button("Save Settings"):
            new_settings = {
                "default_supplier": default_supplier,
                "low_stock_threshold": low_stock_threshold,
                "alert_check_on_sync": alert_check_on_sync,
            }
            save_settings(new_settings)
            st.success("Settings saved.")

    # ── Database stats ───────────────────────────────────────
    st.subheader("Database Stats")

    stats = {
        "Tracked Styles": query_df("SELECT COUNT(*) AS cnt FROM tracked_styles").iloc[0]["cnt"],
        "Products (SKUs)": query_df("SELECT COUNT(*) AS cnt FROM products").iloc[0]["cnt"],
        "Inventory Records": query_df("SELECT COUNT(*) AS cnt FROM inventory").iloc[0]["cnt"],
        "Price History Entries": query_df("SELECT COUNT(*) AS cnt FROM price_history").iloc[0]["cnt"],
        "Sync Log Entries": query_df("SELECT COUNT(*) AS cnt FROM sync_log").iloc[0]["cnt"],
        "Price Alerts": query_df("SELECT COUNT(*) AS cnt FROM price_alerts").iloc[0]["cnt"],
    }

    for key, value in stats.items():
        st.metric(key, int(value))

    # ── Data export ──────────────────────────────────────────
    st.subheader("Data Export")

    export_table = st.selectbox(
        "Export table as CSV",
        ["products", "inventory", "price_history", "tracked_styles", "sync_log", "price_alerts"],
    )

    if st.button("Export"):
        df = query_df(f"SELECT * FROM {export_table}")
        if df.empty:
            st.warning(f"No data in {export_table}.")
        else:
            csv = df.to_csv(index=False)
            st.download_button(
                label=f"Download {export_table}.csv",
                data=csv,
                file_name=f"{export_table}.csv",
                mime="text/csv",
            )

    # ── Danger zone ──────────────────────────────────────────
    st.subheader("Danger Zone")

    st.warning("These actions cannot be undone.")

    if st.button("Clear all price history"):
        from dashboard.db_utils import execute
        execute("DELETE FROM price_history")
        st.info("Price history cleared.")

    if st.button("Clear all sync logs"):
        from dashboard.db_utils import execute
        execute("DELETE FROM sync_log")
        st.info("Sync logs cleared.")
