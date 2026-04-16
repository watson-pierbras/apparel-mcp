"""Price History — time-series charts of price changes."""

import streamlit as st
import plotly.express as px
from dashboard.db_utils import query_df


def render():
    st.header("Price History")

    # ── Style selector ───────────────────────────────────────
    styles = query_df("""
        SELECT DISTINCT supplier, style
        FROM price_history
        ORDER BY supplier, style
    """)

    if styles.empty:
        st.info("No price change history yet. Price changes are recorded during sync when a product's price changes.")
        return

    style_options = [f"{r['supplier']}/{r['style']}" for _, r in styles.iterrows()]
    selected = st.selectbox("Select style", style_options)
    supplier, style = selected.split("/", 1)

    # ── Price type filter ────────────────────────────────────
    price_types = query_df(
        "SELECT DISTINCT price_type FROM price_history WHERE supplier = ? AND style = ?",
        (supplier, style),
    )
    type_options = price_types["price_type"].tolist() if not price_types.empty else []
    selected_types = st.multiselect("Price types", type_options, default=type_options)

    if not selected_types:
        st.info("Select at least one price type.")
        return

    # ── Query history ────────────────────────────────────────
    placeholders = ",".join(["?"] * len(selected_types))
    history = query_df(f"""
        SELECT
            changed_at,
            color,
            size,
            price_type,
            old_price,
            new_price,
            (new_price - old_price) AS change
        FROM price_history
        WHERE supplier = ? AND style = ? AND price_type IN ({placeholders})
        ORDER BY changed_at DESC
    """, (supplier, style, *selected_types))

    if history.empty:
        st.info("No price changes found for this selection.")
        return

    # ── Chart ────────────────────────────────────────────────
    st.subheader("Price Change Timeline")

    chart_data = history.copy()
    chart_data["changed_at"] = chart_data["changed_at"].astype(str)
    chart_data["label"] = chart_data["color"] + " / " + chart_data["size"]

    fig = px.scatter(
        chart_data,
        x="changed_at",
        y="new_price",
        color="price_type",
        symbol="label",
        title=f"Price Changes — {selected}",
        labels={"changed_at": "Date", "new_price": "New Price ($)", "price_type": "Type"},
        hover_data=["old_price", "change", "color", "size"],
    )
    fig.update_layout(xaxis_title="Date", yaxis_title="Price ($)")
    st.plotly_chart(fig, use_container_width=True)

    # ── Table ────────────────────────────────────────────────
    st.subheader("Change Log")

    st.dataframe(
        history,
        use_container_width=True,
        hide_index=True,
        column_config={
            "old_price": st.column_config.NumberColumn("Old $", format="%.2f"),
            "new_price": st.column_config.NumberColumn("New $", format="%.2f"),
            "change": st.column_config.NumberColumn("Change $", format="%+.2f"),
        },
    )

    # ── Summary stats ────────────────────────────────────────
    st.subheader("Summary")

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Changes", len(history))
    increases = len(history[history["change"] > 0])
    decreases = len(history[history["change"] < 0])
    col2.metric("Price Increases", increases)
    col3.metric("Price Decreases", decreases)
