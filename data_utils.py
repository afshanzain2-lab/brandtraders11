"""Data loading, joining and metric helpers for the Brand Traders dashboard.

Kept free of Streamlit imports so it can be unit-tested on its own.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED_FILES = [
    "orders", "order_details", "products", "categories",
    "customers", "employees", "shippers",
]

ISO_FIX = {"UK": "United Kingdom", "USA": "United States"}  # for plotly maps


def _read_csv(src) -> pd.DataFrame:
    """Read a path or an uploaded file, tolerating Latin-1 encoded files."""
    if isinstance(src, (str, Path)):
        raw = Path(src).read_bytes()
    else:  # Streamlit UploadedFile / file-like
        raw = src.getvalue() if hasattr(src, "getvalue") else src.read()
    for enc in ("utf-8", "latin-1"):
        try:
            return pd.read_csv(io.StringIO(raw.decode(enc)))
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode CSV file")


def load_tables(sources: dict) -> dict[str, pd.DataFrame]:
    """sources: {table_name: path_or_uploaded_file}"""
    missing = [t for t in REQUIRED_FILES if t not in sources]
    if missing:
        raise FileNotFoundError(f"Missing tables: {', '.join(missing)}")
    return {name: _read_csv(sources[name]) for name in REQUIRED_FILES}


def build_model(t: dict[str, pd.DataFrame]):
    """Join all seven tables.

    Returns
    -------
    lines  : one row per order line (orders + details + product + category
             + customer + employee + shipper) with revenue columns
    """
    orders = t["orders"].copy()
    for c in ("orderDate", "requiredDate", "shippedDate"):
        orders[c] = pd.to_datetime(orders[c], errors="coerce")

    customers = t["customers"].rename(columns={
        "companyName": "customerName", "city": "customerCity",
        "country": "customerCountry"})
    employees = t["employees"].rename(columns={
        "city": "employeeCity", "country": "employeeCountry",
        "title": "employeeTitle"})
    shippers = t["shippers"].rename(columns={"companyName": "shipperName"})
    products = t["products"].rename(columns={"unitPrice": "listPrice"})
    categories = t["categories"].rename(columns={
        "description": "categoryDescription"})

    lines = (
        t["order_details"]
        .merge(orders, on="orderID", how="left", validate="m:1")
        .merge(products, on="productID", how="left", validate="m:1")
        .merge(categories, on="categoryID", how="left", validate="m:1")
        .merge(customers, on="customerID", how="left", validate="m:1")
        .merge(employees[["employeeID", "employeeName", "employeeTitle",
                          "employeeCity", "employeeCountry"]],
               on="employeeID", how="left", validate="m:1")
        .merge(shippers, on="shipperID", how="left", validate="m:1")
    )

    lines["grossSales"] = lines["unitPrice"] * lines["quantity"]
    lines["discountAmt"] = lines["grossSales"] * lines["discount"]
    lines["revenue"] = lines["grossSales"] - lines["discountAmt"]

    lines["orderMonth"] = lines["orderDate"].dt.to_period("M").dt.to_timestamp()
    lines["orderYear"] = lines["orderDate"].dt.year
    lines["orderQuarter"] = lines["orderDate"].dt.to_period("Q").astype(str)
    lines["orderWeekday"] = lines["orderDate"].dt.day_name()
    lines["shipDays"] = (lines["shippedDate"] - lines["orderDate"]).dt.days
    # 1.0 = shipped late, 0.0 = on time, NaN = not shipped yet
    lines["isLate"] = (lines["shippedDate"] > lines["requiredDate"]).astype(float)
    lines["isLate"] = lines["isLate"].where(lines["shippedDate"].notna())
    lines["isShipped"] = lines["shippedDate"].notna()
    lines["mapCountry"] = lines["customerCountry"].replace(ISO_FIX)
    return lines


def order_level(lines: pd.DataFrame) -> pd.DataFrame:
    """Collapse the line-level frame to one row per order.

    Freight lives on the order, so it must be taken once per order
    (summing it from line level would double count it).
    """
    keys = ["orderID", "customerID", "customerName", "customerCountry",
            "customerCity", "mapCountry", "employeeID", "employeeName",
            "shipperID", "shipperName", "orderDate", "requiredDate",
            "shippedDate", "orderMonth", "shipDays", "isLate", "isShipped",
            "freight"]
    g = lines.groupby(keys, dropna=False, as_index=False).agg(
        revenue=("revenue", "sum"),
        grossSales=("grossSales", "sum"),
        discountAmt=("discountAmt", "sum"),
        units=("quantity", "sum"),
        lineItems=("productID", "count"),
    )
    return g


def kpis(lines: pd.DataFrame) -> dict:
    o = order_level(lines)
    if o.empty:
        return {}
    shipped = o[o["isShipped"]]
    return {
        "revenue": o["revenue"].sum(),
        "orders": o["orderID"].nunique(),
        "customers": o["customerID"].nunique(),
        "units": int(o["units"].sum()),
        "aov": o["revenue"].mean(),
        "discount_given": o["discountAmt"].sum(),
        "discount_rate": o["discountAmt"].sum() / o["grossSales"].sum()
        if o["grossSales"].sum() else 0,
        "freight": o["freight"].sum(),
        "avg_ship_days": shipped["shipDays"].mean(),
        "late_rate": shipped["isLate"].astype(float).mean()
        if len(shipped) else np.nan,
        "unshipped": int((~o["isShipped"]).sum()),
    }


def rfm(orders: pd.DataFrame) -> pd.DataFrame:
    """Simple RFM segmentation at customer level."""
    if orders.empty:
        return pd.DataFrame()
    ref = orders["orderDate"].max() + pd.Timedelta(days=1)
    r = orders.groupby(["customerID", "customerName", "customerCountry"]).agg(
        recency=("orderDate", lambda s: (ref - s.max()).days),
        frequency=("orderID", "nunique"),
        monetary=("revenue", "sum"),
    ).reset_index()

    def score(s, ascending=True):
        # rank first so qcut never fails on duplicate edges
        return pd.qcut(s.rank(method="first", ascending=ascending),
                       4, labels=[1, 2, 3, 4]).astype(int)

    if len(r) >= 4:
        r["R"] = score(r["recency"], ascending=False)  # recent = high
        r["F"] = score(r["frequency"])
        r["M"] = score(r["monetary"])
    else:
        r["R"] = r["F"] = r["M"] = 2
    total = r["R"] + r["F"] + r["M"]

    def seg(row, tot):
        if tot >= 11:
            return "Champions"
        if tot >= 9:
            return "Loyal"
        if row["R"] >= 3 and row["F"] <= 2:
            return "Promising"
        if row["R"] <= 2 and tot >= 7:
            return "At Risk"
        if row["R"] <= 2:
            return "Lost / Hibernating"
        return "Needs Attention"

    r["segment"] = [seg(row, tot) for (_, row), tot in zip(r.iterrows(), total)]
    return r


def basket_pairs(lines: pd.DataFrame, top: int = 15) -> pd.DataFrame:
    """Products most often bought together (co-occurrence in an order)."""
    from itertools import combinations
    from collections import Counter

    cnt = Counter()
    for _, grp in lines.groupby("orderID")["productName"]:
        items = sorted(set(grp))
        for a, b in combinations(items, 2):
            cnt[(a, b)] += 1
    df = pd.DataFrame(
        [(a, b, n) for (a, b), n in cnt.items()],
        columns=["Product A", "Product B", "Orders together"])
    return df.sort_values("Orders together", ascending=False).head(top)
