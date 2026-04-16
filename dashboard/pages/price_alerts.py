"""Price Alerts — set thresholds, view triggered alerts."""

import streamlit as st
from dashboard.db_utils import query_df, execute


def render():
    st.header("Price Alerts")

    # ── Create new alert ─────────────────────────────────────
    st.subheader("Create Alert")

    styles = query_df("SELECT DISTINCT supplier, style FROM tracked_styles WHERE is_active = 1 ORDER BY supplier, style")

    if styles.empty:
        st.info("No active styles to set alerts for. Add and sync styles first.")
        return

    with st.form("create_alert"):
        col1, col2, col3, col4 = st.columns(4)

        style_options = [f"{r['supplier']}/{r['style']}" for _, r in styles.iterrows()]
        selected = col1.selectbox("Style", style_options)

        color_name = col2.text_input("Color (optional)", placeholder="All colors")
        min_price = col3.number_input("Min price alert ($)", min_value=0.0, value=0.0, step=0.25, format="%.2f")
        max_price = col4.number_input("Max price alert ($)", min_value=0.0, value=0.0, step=0.25, format="%.2f")

        submitted = st.form_submit_button("Create Alert")

        if submitted and selected:
            supplier, style = selected.split("/", 1)
            color_val = color_name if color_name else None
            min_val = min_price if min_price > 0 else None
            max_val = max_price if max_price > 0 else None

            if min_val is None and max_val is None:
                st.error("Set at least one threshold (min or max price).")
            else:
                try:
                    execute(
                        """INSERT INTO price_alerts (supplier, style, color_name, min_price, max_price)
                           VALUES (?, ?, ?, ?, ?)""",
                        (supplier, style, color_val, min_val, max_val),
                    )
                    st.success(f"Alert created for {selected}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to create alert: {e}")

    # ── Active alerts ────────────────────────────────────────
    st.subheader("Active Alerts")

    alerts = query_df("""
        SELECT
            id,
            supplier,
            style,
            color_name,
            size,
            min_price,
            max_price,
            is_active,
            created_at
        FROM price_alerts
        ORDER BY is_active DESC, created_at DESC
    """)

    if alerts.empty:
        st.info("No alerts configured yet.")
    else:
        st.dataframe(
            alerts,
            use_container_width=True,
            hide_index=True,
            column_config={
                "min_price": st.column_config.NumberColumn("Min $", format="%.2f"),
                "max_price": st.column_config.NumberColumn("Max $", format="%.2f"),
                "is_active": st.column_config.CheckboxColumn("Active"),
            },
        )

        # Toggle / delete
        col1, col2 = st.columns(2)
        with col1:
            alert_id = st.selectbox(
                "Select alert to toggle",
                alerts["id"].tolist(),
                format_func=lambda x: f"#{x} — {alerts[alerts['id']==x].iloc[0]['supplier']}/{alerts[alerts['id']==x].iloc[0]['style']}",
            )
            if st.button("Toggle Active/Inactive"):
                row = alerts[alerts["id"] == alert_id].iloc[0]
                new_val = 0 if row["is_active"] == 1 else 1
                execute("UPDATE price_alerts SET is_active = ? WHERE id = ?", (new_val, int(alert_id)))
                st.rerun()

        with col2:
            del_id = st.selectbox(
                "Select alert to delete",
                alerts["id"].tolist(),
                format_func=lambda x: f"#{x} — {alerts[alerts['id']==x].iloc[0]['supplier']}/{alerts[alerts['id']==x].iloc[0]['style']}",
                key="del_alert",
            )
            if st.button("Delete Alert", type="secondary"):
                execute("DELETE FROM price_alerts WHERE id = ?", (int(del_id),))
                st.warning("Alert deleted.")
                st.rerun()

    # ── Alert history ────────────────────────────────────────
    st.subheader("Triggered Alert History")

    history = query_df("""
        SELECT
            ah.triggered_at,
            ah.style,
            ah.color_name,
            ah.size,
            ah.direction,
            ah.old_price,
            ah.new_price,
            pa.min_price AS threshold_min,
            pa.max_price AS threshold_max
        FROM alert_history ah
        JOIN price_alerts pa ON pa.id = ah.alert_id
        ORDER BY ah.triggered_at DESC
        LIMIT 100
    """)

    if history.empty:
        st.info("No alerts have been triggered yet.")
    else:
        st.dataframe(
            history,
            use_container_width=True,
            hide_index=True,
            column_config={
                "old_price": st.column_config.NumberColumn("Old $", format="%.2f"),
                "new_price": st.column_config.NumberColumn("New $", format="%.2f"),
                "threshold_min": st.column_config.NumberColumn("Min $", format="%.2f"),
                "threshold_max": st.column_config.NumberColumn("Max $", format="%.2f"),
            },
        )
