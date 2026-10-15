import os
import pandas as pd
import streamlit as st
import snowflake.connector
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
                "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError("Missing .env values: " + ", ".join(missing))
    cfg = dict(account=os.getenv("SNOWFLAKE_ACCOUNT"), user=os.getenv("SNOWFLAKE_USER"),
               password=os.getenv("SNOWFLAKE_PASSWORD"), warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
               database=os.getenv("SNOWFLAKE_DATABASE"), schema=os.getenv("SNOWFLAKE_SCHEMA", "MARTS"))
    if os.getenv("SNOWFLAKE_ROLE"):
        cfg["role"] = os.getenv("SNOWFLAKE_ROLE")
    return snowflake.connector.connect(**cfg)

@st.cache_data(ttl=600, show_spinner=False)
def query_df(sql, params=()):
    if not sql.lstrip().upper().startswith("SELECT"):
        raise ValueError("Only fixed read-only SELECT queries are permitted.")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return pd.DataFrame(cur.fetchall(), columns=[c[0] for c in cur.description])
    finally:
        conn.close()

@st.cache_data(ttl=600, show_spinner=False)
def load_filter_data():
    dates = query_df("""SELECT MIN(TRY_TO_DATE(ORDER_DATE)) MIN_DATE,
        MAX(TRY_TO_DATE(ORDER_DATE)) MAX_DATE FROM FACT_ORDERS
        WHERE TRY_TO_DATE(ORDER_DATE) IS NOT NULL""")
    cities = query_df("SELECT DISTINCT CITY FROM FACT_ORDERS WHERE CITY IS NOT NULL ORDER BY CITY")
    return dates, cities

def _filters(sql, start_date, end_date, city, params=None, alias=""):
    params = list(params or [])
    col = f"{alias}ORDER_DATE" if alias else "ORDER_DATE"
    sql += f" AND TRY_TO_DATE({col}) >= %s AND TRY_TO_DATE({col}) <= %s"
    params.extend([start_date, end_date])
    city_col = f"{alias}CITY" if alias else "CITY"
    if city != "All cities":
        sql += f" AND {city_col} = %s"
        params.append(city)
    return sql, tuple(params)

@st.cache_data(ttl=600, show_spinner=False)
def load_kpis(start_date, end_date, city):
    sql = """SELECT COALESCE(SUM(SALES_AMOUNT),0) SALES_REVENUE,
        COUNT(DISTINCT ORDER_ID) ORDERS, COUNT(DISTINCT RESTAURANT_ID) RESTAURANTS,
        COUNT(DISTINCT CITY) CITIES, COALESCE(SUM(DISCOUNT),0) DISCOUNTS,
        AVG(DELIVERY_TIME_MIN) AVG_DELIVERY_MIN, AVG(CUSTOMER_RATING) AVG_RATING,
        COUNT(CUSTOMER_RATING) RATED_ORDERS FROM FACT_ORDERS WHERE 1=1"""
    sql, params = _filters(sql, start_date, end_date, city)
    return query_df(sql, params)

@st.cache_data(ttl=600, show_spinner=False)
def load_monthly(start_date, end_date, city):
    sql = """SELECT DATE_TRUNC('MONTH', TRY_TO_DATE(ORDER_DATE)) MONTH,
        SUM(SALES_AMOUNT) SALES_REVENUE, COUNT(DISTINCT ORDER_ID) ORDERS
        FROM FACT_ORDERS WHERE TRY_TO_DATE(ORDER_DATE) IS NOT NULL"""
    sql, params = _filters(sql, start_date, end_date, city)
    return query_df(sql + " GROUP BY 1 ORDER BY 1", params)

@st.cache_data(ttl=600, show_spinner=False)
def load_city_revenue(start_date, end_date, city):
    sql = """SELECT CITY, SUM(SALES_AMOUNT) SALES_REVENUE,
        COUNT(DISTINCT ORDER_ID) ORDERS FROM FACT_ORDERS
        WHERE CITY IS NOT NULL AND TRY_TO_DATE(ORDER_DATE) IS NOT NULL"""
    sql, params = _filters(sql, start_date, end_date, city)
    return query_df(sql + " GROUP BY CITY ORDER BY SALES_REVENUE DESC LIMIT 12", params)

@st.cache_data(ttl=600, show_spinner=False)
def load_payment_mix(start_date, end_date, city):
    sql = """SELECT PAYMENT_METHOD, COUNT(DISTINCT ORDER_ID) ORDERS FROM FACT_ORDERS
        WHERE PAYMENT_METHOD IS NOT NULL AND TRY_TO_DATE(ORDER_DATE) IS NOT NULL"""
    sql, params = _filters(sql, start_date, end_date, city)
    return query_df(sql + " GROUP BY PAYMENT_METHOD ORDER BY ORDERS DESC", params)

@st.cache_data(ttl=600, show_spinner=False)
def load_restaurant_performance(start_date, end_date, city):
    sql = """SELECT f.RESTAURANT_ID, r.RESTAURANT_NAME, f.CITY, MAX(f.CUISINE) CUISINE,
        COUNT(DISTINCT f.ORDER_ID) ORDERS, SUM(f.SALES_AMOUNT) REVENUE,
        AVG(f.CUSTOMER_RATING) AVG_CUSTOMER_RATING, AVG(f.DELIVERY_TIME_MIN) AVG_DELIVERY_MIN
        FROM FACT_ORDERS f LEFT JOIN DIM_RESTAURANTS r ON f.RESTAURANT_ID=r.RESTAURANT_ID
        WHERE TRY_TO_DATE(f.ORDER_DATE) IS NOT NULL
        AND TRY_TO_DATE(f.ORDER_DATE) >= %s AND TRY_TO_DATE(f.ORDER_DATE) <= %s"""
    params = [start_date, end_date]
    if city != "All cities":
        sql += " AND f.CITY = %s"; params.append(city)
    sql += " GROUP BY f.RESTAURANT_ID, r.RESTAURANT_NAME, f.CITY ORDER BY REVENUE DESC LIMIT 10"
    return query_df(sql, tuple(params))

@st.cache_data(ttl=600, show_spinner=False)
def load_cuisine_performance(start_date, end_date, city):
    sql = """SELECT CUISINE, COUNT(DISTINCT ORDER_ID) ORDERS,
        SUM(SALES_AMOUNT) REVENUE, AVG(CUSTOMER_RATING) AVG_RATING
        FROM FACT_ORDERS WHERE CUISINE IS NOT NULL AND TRY_TO_DATE(ORDER_DATE) IS NOT NULL"""
    sql, params = _filters(sql, start_date, end_date, city)
    return query_df(sql + " GROUP BY CUISINE ORDER BY REVENUE DESC LIMIT 10", params)

@st.cache_data(ttl=600, show_spinner=False)
def load_customer_segments(start_date, end_date, city):
    sql = """SELECT COALESCE(c.AGE_SEGMENT, 'Unknown') AGE_SEGMENT,
        COUNT(DISTINCT f.CUSTOMER_ID) CUSTOMERS, COUNT(DISTINCT f.ORDER_ID) ORDERS,
        SUM(f.SALES_AMOUNT) REVENUE FROM FACT_ORDERS f
        LEFT JOIN DIM_CUSTOMER c ON f.CUSTOMER_ID=c.CUSTOMER_ID
        WHERE TRY_TO_DATE(f.ORDER_DATE) IS NOT NULL
        AND TRY_TO_DATE(f.ORDER_DATE) >= %s AND TRY_TO_DATE(f.ORDER_DATE) <= %s"""
    params = [start_date, end_date]
    if city != "All cities":
        sql += " AND f.CITY = %s"; params.append(city)
    return query_df(sql + " GROUP BY 1 ORDER BY REVENUE DESC", tuple(params))

@st.cache_data(ttl=1800, show_spinner=False)
def load_quarterly_city_history():
    # Transfer only compact city-quarter aggregates from Snowflake, never 10M raw rows.
    sql = """SELECT CITY,
        DATE_TRUNC('QUARTER', TRY_TO_DATE(ORDER_DATE)) QUARTER_START,
        SUM(IFF(IS_DELIVERED, SALES_AMOUNT, 0)) AS QUARTER_REVENUE,
        COUNT(DISTINCT ORDER_ID) QUARTER_ORDERS,
        COUNT(DISTINCT CUSTOMER_ID) UNIQUE_CUSTOMERS,
        AVG(ITEMS_COUNT) AVG_ITEMS_PER_ORDER,
        SUM(DISCOUNT) TOTAL_DISCOUNT,
        SUM(SUBTOTAL) TOTAL_SUBTOTAL,
        AVG(IFF(UPPER(PAYMENT_METHOD)='UPI',1.0,0.0)) UPI_SHARE
        FROM FACT_ORDERS
        WHERE TRY_TO_DATE(ORDER_DATE) IS NOT NULL AND CITY IS NOT NULL
        GROUP BY CITY, DATE_TRUNC('QUARTER', TRY_TO_DATE(ORDER_DATE))
        ORDER BY CITY, QUARTER_START"""
    df = query_df(sql)
    if df.empty:
        return df
    df["QUARTER_START"] = pd.to_datetime(df["QUARTER_START"], errors="coerce")
    df["QUARTER"] = df["QUARTER_START"].dt.to_period("Q")
    df["DISCOUNT_SHARE"] = df["TOTAL_DISCOUNT"] / df["TOTAL_SUBTOTAL"].replace(0, pd.NA)
    return df.dropna(subset=["QUARTER"]).sort_values(["CITY", "QUARTER"])
