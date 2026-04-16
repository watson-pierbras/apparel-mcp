"""Pricing Browser — browse products with pricing tiers, filter by supplier/brand/style."""

import streamlit as st
from dashboard.db_utils import query_df


def render():
    st.header("Pricing Browser")

    # ── Filters ──────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)

    suppliers = query_df("SELECT DISTINCT supplier FROM products ORDER BY supplier")
    supplier_list = ["All"] + suppliers["supplier"].tolist() if not suppliers.empty else ["All"]
    supplier = col1.selectbox("Supplier", supplier_list)

    brands = query_df("SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL ORDER BY brand")
    brand_list = ["All"] + brands["brand"].tolist() if not brands.empty else ["All"]
    brand = col2.selectbox("Brand", brand_list)

    style_search = col3.text_input("Style", placeholder="PC61")
    color_search = col4.text_input("Color", placeholder="Jet Black")

    # ── Build query ──────────────────────────────────────────
    where_clauses = []
    params = []

    if supplier != "All":
        where_clauses.append("supplier = ?")
        params.append(supplier)
    if brand != "All":
        where_clauses.append("brand = ?")
        params.append(brand)
    if style_search:
        where_clauses.append("style LIKE ?")
        params.append(f"%{style_search}%")
    if color_search:
        where_clauses.append("color LIKE ?")
        params.append(f"%{color_search}%")

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    products = query_df(f"""
        SELECT
            supplier,
            style,
            brand,
            color,
            size,
            piece_price,
            case_price,
            sale_price,
            sale_end_date,
            customer_price,
            case_qty,
            price_code,
            product_status,
            last_synced
        FROM products
        {where}
        ORDER BY supplier, style, color, size
        LIMIT 500
    """, tuple(params))

    # ── Results ──────────────────────────────────────────────
    if products.empty:
        st.info("No products found. Try adjusting your filters or sync some data first.")
        return

    st.caption(f"Showing {len(products)} products (limit 500)")

    st.dataframe(
        products,
        use_container_width=True,
        hide_index=True,
        column_config={
            "piece_price": st.column_config.NumberColumn("Piece $", format="%.2f"),
            "case_price": st.column_config.NumberColumn("Case $", format="%.2f"),
            "sale_price": st.column_config.NumberColumn("Sale $", format="%.2f"),
            "customer_price": st.column_config.NumberColumn("Cust $", format="%.2f"),
        },
    )

    # ── Quick stats ──────────────────────────────────────────
    st.subheader("Quick Stats")
    col1, col2, col3 = st.columns(3)
    col1.metric("Avg Piece Price", f"${products['piece_price'].mean():.2f}" if products['piece_price'].notna().any() else "N/A")
    col2.metric("Min Piece Price", f"${products['piece_price'].min():.2f}" if products['piece_price'].notna().any() else "N/A")
    col3.metric("Max Piece Price", f"${products['piece_price'].max():.2f}" if products['piece_price'].notna().any() else "N/A")
