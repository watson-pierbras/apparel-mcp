"""Apparel MCP Admin Dashboard — main entry point."""

import streamlit as st

st.set_page_config(
    page_title="Apparel MCP Dashboard",
    page_icon="👕",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar navigation ──────────────────────────────────────────
st.sidebar.title("Apparel MCP")
st.sidebar.caption("Compound Sportswear")

page = st.sidebar.radio(
    "Navigate",
    [
        "Sync Overview",
        "Tracked Styles",
        "Pricing Browser",
        "Price Alerts",
        "Inventory",
        "Price History",
        "Settings",
    ],
    label_visibility="collapsed",
)

# ── Route to pages ──────────────────────────────────────────────
if page == "Sync Overview":
    from pages import sync_overview
    sync_overview.render()
elif page == "Tracked Styles":
    from pages import tracked_styles
    tracked_styles.render()
elif page == "Pricing Browser":
    from pages import pricing_browser
    pricing_browser.render()
elif page == "Price Alerts":
    from pages import price_alerts
    price_alerts.render()
elif page == "Inventory":
    from pages import inventory
    inventory.render()
elif page == "Price History":
    from pages import price_history
    price_history.render()
elif page == "Settings":
    from pages import settings
    settings.render()
