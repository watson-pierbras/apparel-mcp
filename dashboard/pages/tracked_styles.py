"""Tracked Styles page — add, remove, toggle styles."""

import streamlit as st
from dashboard.db_utils import query_df, execute


def render():
    st.header("Tracked Styles")

    # ── Add new style ────────────────────────────────────────
    st.subheader("Add Style")

    with st.form("add_style_form"):
        col1, col2, col3, col4 = st.columns([1, 2, 2, 1])
        supplier = col1.selectbox("Supplier", ["sanmar", "ssactivewear"])
        styles_input = col2.text_input("Style(s)", placeholder="PC61,K420,ST350")
        brand = col3.text_input("Brand", placeholder="Port & Company")
        category = col4.text_input("Category", placeholder="T-Shirts")
        submitted = st.form_submit_button("Add Styles")

        if submitted and styles_input:
            styles = [s.strip() for s in styles_input.split(",") if s.strip()]
            added = 0
            skipped = 0
            for style in styles:
                try:
                    execute(
                        "INSERT INTO tracked_styles (supplier, style, brand, category) VALUES (?, ?, ?, ?)",
                        (supplier, style, brand or None, category or None),
                    )
                    added += 1
                except Exception:
                    skipped += 1
            st.success(f"Added {added} style(s), skipped {skipped} (already tracked).")
            st.rerun()

    # ── Current tracked styles ───────────────────────────────
    st.subheader("All Tracked Styles")

    styles_df = query_df("""
        SELECT
            ts.id,
            ts.supplier,
            ts.style,
            ts.brand,
            ts.category,
            ts.is_active,
            ts.added_at,
            ts.last_synced,
            COUNT(p.id) AS product_count
        FROM tracked_styles ts
        LEFT JOIN products p ON p.tracked_style_id = ts.id
        GROUP BY ts.id
        ORDER BY ts.supplier, ts.style
    """)

    if styles_df.empty:
        st.info("No styles tracked yet. Add some above.")
        return

    # Filter
    col1, col2 = st.columns(2)
    supplier_filter = col1.selectbox(
        "Filter by supplier", ["All"] + sorted(styles_df["supplier"].unique().tolist())
    )
    active_filter = col2.selectbox("Filter by status", ["All", "Active", "Inactive"])

    filtered = styles_df.copy()
    if supplier_filter != "All":
        filtered = filtered[filtered["supplier"] == supplier_filter]
    if active_filter == "Active":
        filtered = filtered[filtered["is_active"] == 1]
    elif active_filter == "Inactive":
        filtered = filtered[filtered["is_active"] == 0]

    st.dataframe(
        filtered[["supplier", "style", "brand", "category", "is_active", "product_count", "last_synced"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "is_active": st.column_config.CheckboxColumn("Active", default=True),
        },
    )

    # ── Toggle / delete actions ──────────────────────────────
    st.subheader("Actions")

    col1, col2 = st.columns(2)

    with col1:
        style_to_toggle = st.selectbox(
            "Toggle active/inactive",
            filtered["style"].tolist(),
            key="toggle_select",
        )
        if st.button("Toggle Status"):
            row = filtered[filtered["style"] == style_to_toggle].iloc[0]
            new_status = 0 if row["is_active"] == 1 else 1
            execute(
                "UPDATE tracked_styles SET is_active = ? WHERE id = ?",
                (new_status, int(row["id"])),
            )
            st.success(f"{'Deactivated' if new_status == 0 else 'Activated'} {style_to_toggle}")
            st.rerun()

    with col2:
        style_to_delete = st.selectbox(
            "Remove style",
            filtered["style"].tolist(),
            key="delete_select",
        )
        if st.button("Delete Style", type="secondary"):
            row = filtered[filtered["style"] == style_to_delete].iloc[0]
            execute("DELETE FROM tracked_styles WHERE id = ?", (int(row["id"]),))
            st.warning(f"Deleted {style_to_delete} and all associated data.")
            st.rerun()
