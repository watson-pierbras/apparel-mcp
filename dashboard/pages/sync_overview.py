"""Sync Overview page — last sync status, history log, health metrics."""

import streamlit as st
import pandas as pd
from dashboard.db_utils import query_df


def render():
    st.header("Sync Overview")

    # ── Key metrics ──────────────────────────────────────────
    last_syncs = query_df("""
        SELECT supplier,
               MAX(completed_at) AS last_completed,
               status
        FROM sync_log
        GROUP BY supplier
        ORDER BY supplier
    """)

    totals = query_df("""
        SELECT
            COUNT(*) AS total_runs,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS successes,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failures,
            SUM(price_changes) AS total_price_changes
        FROM sync_log
    """)

    col1, col2, col3, col4 = st.columns(4)

    if not totals.empty:
        row = totals.iloc[0]
        col1.metric("Total Sync Runs", int(row["total_runs"]))
        col2.metric("Successful", int(row["successes"]))
        col3.metric("Failed", int(row["failures"]))
        col4.metric("Price Changes Detected", int(row["total_price_changes"] or 0))
    else:
        col1.metric("Total Sync Runs", 0)
        col2.metric("Successful", 0)
        col3.metric("Failed", 0)
        col4.metric("Price Changes Detected", 0)

    # ── Last sync per supplier ───────────────────────────────
    st.subheader("Last Sync by Supplier")

    if last_syncs.empty:
        st.info("No sync runs recorded yet. Run your first sync with: python scripts/run_sync.py")
    else:
        st.dataframe(last_syncs, use_container_width=True, hide_index=True)

    # ── Full sync history ────────────────────────────────────
    st.subheader("Sync History")

    limit = st.selectbox("Show last", [10, 25, 50, 100], index=0)

    history = query_df(f"""
        SELECT
            id,
            supplier,
            sync_type,
            styles_synced,
            skus_updated,
            price_changes,
            errors,
            status,
            started_at,
            completed_at
        FROM sync_log
        ORDER BY started_at DESC
        LIMIT {limit}
    """)

    if history.empty:
        st.info("No sync history yet.")
    else:
        # Color-code status
        def highlight_status(row):
            if row["status"] == "failed":
                return ["background-color: #ffcccc"] * len(row)
            elif row["status"] == "completed":
                return ["background-color: #ccffcc"] * len(row)
            return [""] * len(row)

        st.dataframe(
            history.style.apply(highlight_status, axis=1),
            use_container_width=True,
            hide_index=True,
        )
