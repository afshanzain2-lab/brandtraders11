"""Brand Traders – Sales Analytics Dashboard (Streamlit).

Run:  streamlit run app.py
Data: put the 7 CSVs in ./data (or next to this file), or upload them in the sidebar.
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import data_utils as du

st.set_page_config(page_title="Brand Traders Analytics", page_icon="📊", layout="wide")

APP_DIR = Path(__file__).parent
PALETTE = px.colors.qualitative.Set2
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ------------------------------------------------------------------ data
@st.cache_data(show_spinner="Loading and joining tables…")
def get_data(file_blobs: dict):
    """file_blobs: {table: path string OR (name, bytes)}. Hashable/cacheable."""
    import io
    src = {}
    for k, v in file_blobs.items():
        src[k] = v if isinstance(v, str) else io.BytesIO(v[1])
    tables = du.load_tables(src)
    return tables, du.build_model(tables)


def discover_local() -> dict:
    for folder in (APP_DIR / "data", APP_DIR, Path.cwd() / "data", Path.cwd()):
        found = {n: str(folder / f"{n}.csv") for n in du.REQUIRED_FILES
                 if (folder / f"{n}.csv").exists()}
        if len(found) == len(du.REQUIRED_FILES):
            return found
    return {}


def money(x):
    return f"${x:,.0f}"


st.sidebar.title("📊 Brand Traders")
uploads = st.sidebar.file_uploader(
    "Upload the 7 CSV files (optional if they sit in ./data)",
    type="csv", accept_multiple_files=True)

blobs = discover_local()
if uploads:
    up = {Path(f.name).stem: (f.name, f.getvalue()) for f in uploads}
    blobs = {**blobs, **up}

missing = [n for n in du.REQUIRED_FILES if n not in blobs]
if missing:
    st.title("Brand Traders – Sales Analytics")
    st.info("Upload all seven files: " + ", ".join(f"`{n}.csv`" for n in du.REQUIRED_FILES)
            + f"\n\nStill missing: {', '.join(missing)}")
    st.stop()

tables, lines_all = get_data(blobs)

# --------------------------------------------------------------- filters
st.sidebar.header("Filters")
dmin, dmax = lines_all["orderDate"].min().date(), lines_all["orderDate"].max().date()
date_rng = st.sidebar.date_input("Order date", (dmin, dmax), min_value=dmin, max_value=dmax)
if isinstance(date_rng, tuple) and len(date_rng) == 2:
    d0, d1 = date_rng
else:
    d0, d1 = dmin, dmax


def multi(label, col):
    opts = sorted(lines_all[col].dropna().unique())
    return st.sidebar.multiselect(label, opts, placeholder="All")


f_country = multi("Customer country", "customerCountry")
f_cat = multi("Category", "categoryName")
f_emp = multi("Employee", "employeeName")
f_ship = multi("Shipper", "shipperName")

lines = lines_all[(lines_all["orderDate"].dt.date >= d0) & (lines_all["orderDate"].dt.date <= d1)]
for col, sel in (("customerCountry", f_country), ("categoryName", f_cat),
                 ("employeeName", f_emp), ("shipperName", f_ship)):
    if sel:
        lines = lines[lines[col].isin(sel)]

if lines.empty:
    st.warning("No data for the selected filters.")
    st.stop()

orders = du.order_level(lines)
K = du.kpis(lines)

st.sidebar.caption(
    "Revenue = unitPrice × quantity × (1 − discount). Freight is counted once per order. "
    "Note: data runs 2013‑07 → 2015‑05, so 2013 and 2015 are partial years.")

# ----------------------------------------------------------------- header
st.title("Brand Traders – Sales Analytics")
st.caption(f"{d0:%d %b %Y} → {d1:%d %b %Y}  |  {K['orders']:,} orders  |  "
           f"{len(lines):,} order lines  |  7 tables joined")

tabs = st.tabs(["🏠 Overview", "📈 Sales Trends", "📦 Products & Categories",
                "👥 Customers", "🧑‍💼 Employees", "🚚 Shipping", "🗂 Data Explorer"])

# ================================================================ OVERVIEW
with tabs[0]:
    c = st.columns(5)
    c[0].metric("Revenue", money(K["revenue"]))
    c[1].metric("Orders", f"{K['orders']:,}")
    c[2].metric("Customers", f"{K['customers']:,}")
    c[3].metric("Avg order value", money(K["aov"]))
    c[4].metric("Units sold", f"{K['units']:,}")
    c = st.columns(5)
    c[0].metric("Discounts given", money(K["discount_given"]), f"{K['discount_rate']:.1%} of gross", delta_color="off")
    c[1].metric("Freight cost", money(K["freight"]))
    c[2].metric("Avg days to ship", f"{K['avg_ship_days']:.1f}")
    c[3].metric("Late shipments", f"{K['late_rate']:.1%}")
    c[4].metric("Not yet shipped", f"{K['unshipped']:,}")

    st.divider()
    l, r = st.columns([3, 2])
    monthly = lines.groupby("orderMonth", as_index=False).agg(revenue=("revenue", "sum"))
    fig = px.area(monthly, x="orderMonth", y="revenue", title="Monthly revenue",
                  labels={"orderMonth": "", "revenue": "Revenue ($)"})
    fig.update_traces(line_color=PALETTE[0])
    l.plotly_chart(fig, use_container_width=True)

    cat = lines.groupby("categoryName", as_index=False)["revenue"].sum()
    fig = px.pie(cat, names="categoryName", values="revenue", hole=0.5,
                 title="Revenue by category", color_discrete_sequence=PALETTE)
    r.plotly_chart(fig, use_container_width=True)

    # automatic insights
    st.subheader("Key insights")
    top_prod = lines.groupby("productName")["revenue"].sum().nlargest(1)
    top_cat = cat.nlargest(1, "revenue").iloc[0]
    top_cty = lines.groupby("customerCountry")["revenue"].sum().nlargest(1)
    top_emp = lines.groupby("employeeName")["revenue"].sum().nlargest(1)
    top_cus = lines.groupby("customerName")["revenue"].sum().nlargest(1)
    best_m = monthly.nlargest(1, "revenue").iloc[0]
    cust_rev = lines.groupby("customerID")["revenue"].sum().sort_values(ascending=False)
    top10_share = cust_rev.head(10).sum() / cust_rev.sum()
    st.markdown(
        f"- 🏆 **Top product:** {top_prod.index[0]} ({money(top_prod.iloc[0])}).\n"
        f"- 🗂 **Top category:** {top_cat.categoryName} – {top_cat.revenue / K['revenue']:.0%} of revenue.\n"
        f"- 🌍 **Top market:** {top_cty.index[0]} ({money(top_cty.iloc[0])}, "
        f"{top_cty.iloc[0] / K['revenue']:.0%} of revenue).\n"
        f"- 👤 **Top customer:** {top_cus.index[0]} ({money(top_cus.iloc[0])}); "
        f"the top 10 customers generate {top10_share:.0%} of revenue.\n"
        f"- 🧑‍💼 **Top salesperson:** {top_emp.index[0]} ({money(top_emp.iloc[0])}).\n"
        f"- 📅 **Best month:** {best_m.orderMonth:%b %Y} ({money(best_m.revenue)})."
    )

# ============================================================ SALES TRENDS
with tabs[1]:
    grain = st.radio("Time grain", ["Month", "Quarter", "Week"], horizontal=True)
    if grain == "Month":
        key = "orderMonth"
    elif grain == "Quarter":
        key = "orderQuarter"
    else:
        key = "orderWeek"
    ln = lines.assign(orderWeek=lines["orderDate"].dt.to_period("W").dt.start_time)
    ts = ln.groupby(key, as_index=False).agg(
        revenue=("revenue", "sum"), orders=("orderID", "nunique"), units=("quantity", "sum"))
    ts["aov"] = ts["revenue"] / ts["orders"]

    fig = go.Figure()
    fig.add_bar(x=ts[key], y=ts["revenue"], name="Revenue", marker_color=PALETTE[0])
    fig.add_scatter(x=ts[key], y=ts["orders"], name="Orders", yaxis="y2",
                    mode="lines+markers", line=dict(color=PALETTE[1]))
    fig.update_layout(title=f"Revenue and orders by {grain.lower()}",
                      yaxis=dict(title="Revenue ($)"),
                      yaxis2=dict(title="Orders", overlaying="y", side="right"),
                      legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)
    if grain == "Month" and len(ts) > 1:
        st.caption("⚠️ The first and last months in the data may be partial; read their bars with care.")

    a, b = st.columns(2)
    m = lines.assign(month=lines["orderDate"].dt.month, year=lines["orderYear"].astype(str))
    ym = m.groupby(["year", "month"], as_index=False)["revenue"].sum()
    fig = px.line(ym, x="month", y="revenue", color="year", markers=True,
                  title="Seasonality: revenue by calendar month, per year",
                  color_discrete_sequence=PALETTE)
    fig.update_xaxes(dtick=1)
    a.plotly_chart(fig, use_container_width=True)

    wd = (lines.groupby("orderWeekday")["orderID"].nunique().reindex(WEEKDAYS).fillna(0).reset_index())
    wd.columns = ["Weekday", "Orders"]
    fig = px.bar(wd, x="Weekday", y="Orders", title="Orders by weekday",
                 color_discrete_sequence=[PALETTE[2]])
    b.plotly_chart(fig, use_container_width=True)

    a, b = st.columns(2)
    cum = ts.assign(cumulative=ts["revenue"].cumsum())
    fig = px.line(cum, x=key, y="cumulative", title="Cumulative revenue",
                  labels={"cumulative": "Revenue ($)", key: ""})
    a.plotly_chart(fig, use_container_width=True)

    mom = lines.groupby("orderMonth")["revenue"].sum().pct_change().dropna().reset_index()
    mom.columns = ["Month", "Growth"]
    mom["Direction"] = mom["Growth"].apply(lambda g: "Up" if g > 0 else "Down")
    fig = px.bar(mom, x="Month", y="Growth", title="Month-over-month revenue growth",
                 color="Direction",
                 color_discrete_map={"Up": "#2e9e6b", "Down": "#d9534f"})
    fig.update_layout(showlegend=False, yaxis_tickformat=".0%")
    b.plotly_chart(fig, use_container_width=True)

# ================================================ PRODUCTS & CATEGORIES
with tabs[2]:
    n = st.slider("Top N products", 5, 30, 10)
    metric = st.radio("Rank by", ["revenue", "quantity"], horizontal=True)
    prod = lines.groupby(["productName", "categoryName"], as_index=False).agg(
        revenue=("revenue", "sum"), quantity=("quantity", "sum"),
        orders=("orderID", "nunique"), avg_discount=("discount", "mean"))
    top = prod.nlargest(n, metric).sort_values(metric)
    fig = px.bar(top, x=metric, y="productName", color="categoryName", orientation="h",
                 title=f"Top {n} products by {metric}", color_discrete_sequence=PALETTE,
                 height=max(380, 28 * n))
    fig.update_layout(yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)

    a, b = st.columns(2)
    tm = prod[prod["revenue"] > 0]
    fig = px.treemap(tm, path=["categoryName", "productName"], values="revenue",
                     title="Revenue treemap (category → product)",
                     color_discrete_sequence=PALETTE)
    a.plotly_chart(fig, use_container_width=True)

    cm = lines.groupby(["orderMonth", "categoryName"], as_index=False)["revenue"].sum()
    fig = px.area(cm, x="orderMonth", y="revenue", color="categoryName",
                  title="Category revenue over time", color_discrete_sequence=PALETTE,
                  labels={"orderMonth": ""})
    b.plotly_chart(fig, use_container_width=True)

    a, b = st.columns(2)
    dsc = lines.assign(
        band=pd.cut(lines["discount"], [-0.001, 0, 0.05, 0.10, 0.15, 1.0],
                    labels=["None", "≤5%", "5–10%", "10–15%", ">15%"]))
    dd = dsc.groupby("band", observed=True).agg(
        lines=("productID", "count"), avg_qty=("quantity", "mean")).reset_index()
    fig = px.bar(dd, x="band", y="avg_qty", text=dd["avg_qty"].round(1),
                 title="Does discounting lift quantity? (avg qty per line)",
                 labels={"band": "Discount band", "avg_qty": "Avg quantity"},
                 color_discrete_sequence=[PALETTE[3]])
    a.plotly_chart(fig, use_container_width=True)

    disc = lines.assign(status=lines["discontinued"].map({0: "Active", 1: "Discontinued"}))
    ds = disc.groupby("status", as_index=False)["revenue"].sum()
    fig = px.pie(ds, names="status", values="revenue", hole=0.5,
                 title="Revenue: active vs discontinued products",
                 color_discrete_sequence=PALETTE)
    b.plotly_chart(fig, use_container_width=True)

    st.subheader("Products frequently bought together")
    pairs = du.basket_pairs(lines, 15)
    st.dataframe(pairs, use_container_width=True, hide_index=True)

    st.subheader("Product table")
    st.dataframe(prod.sort_values("revenue", ascending=False).round(2),
                 use_container_width=True, hide_index=True)

# ================================================================ CUSTOMERS
with tabs[3]:
    a, b = st.columns(2)
    geo = lines.groupby(["customerCountry", "mapCountry"], as_index=False).agg(
        revenue=("revenue", "sum"), customers=("customerID", "nunique"))
    fig = px.choropleth(geo, locations="mapCountry", locationmode="country names",
                        color="revenue", hover_name="customerCountry",
                        hover_data={"mapCountry": False, "customers": True},
                        title="Revenue by customer country",
                        color_continuous_scale="Blues")
    a.plotly_chart(fig, use_container_width=True)

    gs = geo.sort_values("revenue").tail(15)
    fig = px.bar(gs, x="revenue", y="customerCountry", orientation="h",
                 title="Top countries by revenue", color_discrete_sequence=[PALETTE[0]])
    fig.update_layout(yaxis_title="")
    b.plotly_chart(fig, use_container_width=True)

    a, b = st.columns(2)
    cust = orders.groupby(["customerID", "customerName", "customerCountry"], as_index=False).agg(
        revenue=("revenue", "sum"), orders=("orderID", "nunique"), freight=("freight", "sum"))
    cust["aov"] = cust["revenue"] / cust["orders"]
    topc = cust.nlargest(10, "revenue").sort_values("revenue")
    fig = px.bar(topc, x="revenue", y="customerName", orientation="h",
                 title="Top 10 customers", color_discrete_sequence=[PALETTE[1]])
    fig.update_layout(yaxis_title="")
    a.plotly_chart(fig, use_container_width=True)

    par = cust.sort_values("revenue", ascending=False).reset_index(drop=True)
    par["cum_share"] = par["revenue"].cumsum() / par["revenue"].sum()
    par["rank_pct"] = (par.index + 1) / len(par)
    fig = px.area(par, x="rank_pct", y="cum_share", title="Pareto: customer concentration",
                  labels={"rank_pct": "% of customers (ranked)", "cum_share": "% of revenue"})
    fig.update_layout(xaxis_tickformat=".0%", yaxis_tickformat=".0%")
    fig.add_hline(y=0.8, line_dash="dot")
    b.plotly_chart(fig, use_container_width=True)

    st.subheader("Customer segmentation (RFM)")
    st.caption("Recency / Frequency / Monetary quartile scores, computed on the filtered data.")
    rf = du.rfm(orders)
    a, b = st.columns([2, 3])
    sg = rf.groupby("segment", as_index=False).agg(
        customers=("customerID", "count"), revenue=("monetary", "sum"))
    fig = px.bar(sg.sort_values("customers"), x="customers", y="segment", orientation="h",
                 text="customers", title="Customers per segment",
                 color_discrete_sequence=[PALETTE[4]])
    fig.update_layout(yaxis_title="")
    a.plotly_chart(fig, use_container_width=True)
    fig = px.scatter(rf, x="recency", y="monetary", size="frequency", color="segment",
                     hover_name="customerName", title="Recency vs spend (bubble = # orders)",
                     labels={"recency": "Days since last order", "monetary": "Revenue ($)"},
                     color_discrete_sequence=PALETTE)
    b.plotly_chart(fig, use_container_width=True)
    st.dataframe(rf.sort_values("monetary", ascending=False).round(1),
                 use_container_width=True, hide_index=True)

# =============================================================== EMPLOYEES
with tabs[4]:
    emp = orders.groupby("employeeName", as_index=False).agg(
        revenue=("revenue", "sum"), orders=("orderID", "nunique"),
        customers=("customerID", "nunique"))
    emp["aov"] = emp["revenue"] / emp["orders"]
    a, b = st.columns(2)
    fig = px.bar(emp.sort_values("revenue"), x="revenue", y="employeeName", orientation="h",
                 title="Revenue by salesperson", color_discrete_sequence=[PALETTE[0]])
    fig.update_layout(yaxis_title="")
    a.plotly_chart(fig, use_container_width=True)
    fig = px.scatter(emp, x="orders", y="aov", size="revenue", text="employeeName",
                     title="Volume vs order value (bubble = revenue)",
                     labels={"orders": "Orders handled", "aov": "Avg order value ($)"},
                     color_discrete_sequence=[PALETTE[2]])
    fig.update_traces(textposition="top center")
    b.plotly_chart(fig, use_container_width=True)

    em = lines.groupby(["orderMonth", "employeeName"], as_index=False)["revenue"].sum()
    fig = px.line(em, x="orderMonth", y="revenue", color="employeeName",
                  title="Monthly revenue by salesperson", color_discrete_sequence=PALETTE,
                  labels={"orderMonth": ""})
    st.plotly_chart(fig, use_container_width=True)

    ec = lines.groupby(["employeeName", "categoryName"], as_index=False)["revenue"].sum()
    pv = ec.pivot(index="employeeName", columns="categoryName", values="revenue").fillna(0)
    fig = px.imshow(pv, aspect="auto", color_continuous_scale="Blues",
                    title="Salesperson × category revenue")
    st.plotly_chart(fig, use_container_width=True)

    team = tables["employees"].merge(
        tables["employees"][["employeeID", "employeeName"]].rename(
            columns={"employeeID": "reportsTo", "employeeName": "manager"}),
        on="reportsTo", how="left")
    st.subheader("Team directory")
    st.dataframe(team[["employeeName", "title", "city", "country", "manager"]],
                 use_container_width=True, hide_index=True)

# ================================================================= SHIPPING
with tabs[5]:
    ship = orders[orders["isShipped"]]
    a, b = st.columns(2)
    sh = orders.groupby("shipperName", as_index=False).agg(
        orders=("orderID", "nunique"), freight=("freight", "sum"),
        avg_freight=("freight", "mean"))
    fig = px.pie(sh, names="shipperName", values="orders", hole=0.5,
                 title="Order share by shipper", color_discrete_sequence=PALETTE)
    a.plotly_chart(fig, use_container_width=True)
    perf = ship.groupby("shipperName", as_index=False).agg(
        avg_days=("shipDays", "mean"), late_rate=("isLate", "mean"))
    fig = px.bar(perf, x="shipperName", y="avg_days", text=perf["avg_days"].round(1),
                 title="Avg days from order to shipment",
                 labels={"shipperName": "", "avg_days": "Days"},
                 color_discrete_sequence=[PALETTE[1]])
    b.plotly_chart(fig, use_container_width=True)

    a, b = st.columns(2)
    fig = px.bar(perf, x="shipperName", y="late_rate", text=perf["late_rate"].map("{:.1%}".format),
                 title="Late-shipment rate by shipper",
                 labels={"shipperName": "", "late_rate": "Late rate"},
                 color_discrete_sequence=[PALETTE[3]])
    fig.update_layout(yaxis_tickformat=".0%")
    a.plotly_chart(fig, use_container_width=True)
    fig = px.bar(sh, x="shipperName", y="avg_freight", text=sh["avg_freight"].round(1),
                 title="Avg freight cost per order",
                 labels={"shipperName": "", "avg_freight": "$ / order"},
                 color_discrete_sequence=[PALETTE[4]])
    b.plotly_chart(fig, use_container_width=True)

    fig = px.histogram(ship, x="shipDays", nbins=25, title="Distribution of days to ship",
                       labels={"shipDays": "Days to ship"}, color_discrete_sequence=[PALETTE[0]])
    st.plotly_chart(fig, use_container_width=True)

    fc = orders.groupby("customerCountry", as_index=False).agg(
        freight=("freight", "sum"), revenue=("revenue", "sum"))
    fc["freight_pct"] = fc["freight"] / fc["revenue"]
    fig = px.bar(fc.sort_values("freight_pct", ascending=False).head(15),
                 x="customerCountry", y="freight_pct",
                 title="Freight as % of revenue – top 15 countries",
                 labels={"customerCountry": "", "freight_pct": "Freight / revenue"},
                 color_discrete_sequence=[PALETTE[5]])
    fig.update_layout(yaxis_tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Late shipments")
    late = orders[orders["isLate"] == 1][
        ["orderID", "customerName", "shipperName", "orderDate", "requiredDate", "shippedDate", "revenue"]]
    st.dataframe(late.round(2), use_container_width=True, hide_index=True)
    pending = orders[~orders["isShipped"]][
        ["orderID", "customerName", "shipperName", "orderDate", "requiredDate", "revenue"]]
    st.subheader("Orders not yet shipped")
    st.dataframe(pending.round(2), use_container_width=True, hide_index=True)

# =========================================================== DATA EXPLORER
with tabs[6]:
    st.subheader("Joined dataset (one row per order line)")
    st.caption("orders ⟶ order_details ⟶ products ⟶ categories · customers · employees · shippers")
    cols = ["orderID", "orderDate", "customerName", "customerCountry", "employeeName",
            "shipperName", "categoryName", "productName", "unitPrice", "quantity",
            "discount", "revenue", "freight", "shippedDate", "shipDays"]
    show = lines[cols]
    st.dataframe(show, use_container_width=True, hide_index=True, height=450)
    st.download_button("⬇️ Download joined data (CSV)", show.to_csv(index=False).encode(),
                       "brand_traders_joined.csv", "text/csv")

    with st.expander("Table relationships"):
        st.code(
            "orders.customerID      → customers.customerID\n"
            "orders.employeeID      → employees.employeeID\n"
            "orders.shipperID       → shippers.shipperID\n"
            "order_details.orderID  → orders.orderID\n"
            "order_details.productID→ products.productID\n"
            "products.categoryID    → categories.categoryID\n"
            "employees.reportsTo    → employees.employeeID (self-join)")
    with st.expander("Raw table sizes"):
        st.write({k: v.shape for k, v in tables.items()})
