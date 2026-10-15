from pathlib import Path
import json
import os
import re
import decimal
import base64
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from openai import OpenAI

from data_access import (load_filter_data, load_kpis, load_monthly, load_city_revenue,
        load_payment_mix, load_restaurant_performance, load_cuisine_performance,
        load_customer_segments, load_quarterly_city_history, query_df
)
from forecasting import make_forecast
from styles import apply_styles

LOGO_BRAND = Path(__file__).resolve().parent / "assets" / "swiggy_logo.png"
LOGO_BRAND_ICON = Path(__file__).resolve().parent / "assets" / "swiggy_logo_icon.png"

LLM_MODEL_NAME = "openai/gpt-oss-120b"
GOLD_TABLE_COLUMNS = {
    "DIM_RESTAURANTS": ["RESTAURANT_ID", "RESTAURANT_NAME", "CITY", "CUISINE", "RATING", "RATING_COUNT", "COST"],
    "DIM_CUSTOMER": ["CUSTOMER_ID", "CUSTOMER_NAME", "EMAIL", "AGE", "AGE_SEGMENT", "GENDER", "MARITAL_STATUS", "OCCUPATION", "MONTHLY_INCOME", "EDUCATION", "FAMILY_SIZE"],
    "DIM_FOOD": ["F_ID", "FOOD_NAME", "VEG_OR_NON_VEG"],
    "DIM_DATE": ["DATE_DAY", "YEAR", "MONTH", "MONTH_NAME", "DAY_NAME", "IS_WEEKEND"],
    "MART_DAILY_CITY_REVENUE": ["ORDER_DATE", "CITY", "ORDERS", "DELIVERED_ORDERS", "CANCEL_RATE", "GMV", "AOV"],
    "MART_DELIVERY_SLA": ["CITY", "ORDER_HOUR", "DELIVERED_ORDERS", "P50", "P90"],
    "MART_RESTAURANT_PERFORMANCE": ["RESTAURANT_ID", "RESTAURANT_NAME", "CITY", "CUISINE", "ORDERS", "REVENUE", "AVG_CUSTOMER_RATING", "AVG_DELIVERY_MIN"],
    "FACT_ORDERS": ["ORDER_ID", "ORDER_TIMESTAMP", "ORDER_DATE", "CUSTOMER_ID", "RESTAURANT_ID", "CITY", "CUISINE", "PAYMENT_METHOD", "ORDER_STATUS", "IS_DELIVERED", "ITEMS_COUNT", "SALES_QTY", "SUBTOTAL", "DISCOUNT", "DELIVERY_FEE", "GST", "SALES_AMOUNT", "CUSTOMER_RATING", "DELIVERY_TIME_MIN"],
    "FACT_ORDER_ITEMS": ["ORDER_ITEM_ID", "ORDER_ID", "RESTAURANT_ID", "F_ID", "ORDER_TS", "ORDER_DATE", "CITY", "PRICE", "QUANTITY", "LINE_AMOUNT"],
}

GOLD_TABLE_JOINS = [
    ("FACT_ORDERS", "DIM_CUSTOMER", "CUSTOMER_ID"),
    ("FACT_ORDERS", "DIM_RESTAURANTS", "RESTAURANT_ID"),
    ("FACT_ORDERS", "DIM_DATE", "ORDER_DATE = DATE_DAY"),
    ("FACT_ORDER_ITEMS", "FACT_ORDERS", "ORDER_ID"),
    ("FACT_ORDER_ITEMS", "DIM_FOOD", "F_ID"),
    ("FACT_ORDER_ITEMS", "DIM_RESTAURANTS", "RESTAURANT_ID"),
    ("MART_RESTAURANT_PERFORMANCE", "DIM_RESTAURANTS", "RESTAURANT_ID"),
]

SCHEMA_TEXT = ""
for table_name in GOLD_TABLE_COLUMNS:
    SCHEMA_TEXT = SCHEMA_TEXT + table_name + "(" + ", ".join(GOLD_TABLE_COLUMNS[table_name]) + ")\n"

# lets write our own business notes here (what GMV means, what the ORDER_STATUS values are, etc.)
BUSINESS_NOTES = "In FACT_ORDERS always use TRY_TO_DATE(ORDER_DATE) when you filter or group by date.\n"

SYSTEM_PROMPT = """You are a Snowflake SQL assistant for a food delivery company.
You can only use the tables below. Use bare table names (no database or schema).

""" + SCHEMA_TEXT + """
""" + BUSINESS_NOTES + """
Reply with ONLY one JSON object, in this format:
{"show": "...", "sql": "...", "x": "...", "y": "...", "diagram_tables": [], "answer": "..."}

Rules for "show":
- "sql"     : the user asked for the SQL code / query. Write the SQL, do not explain much.
- "table"   : the user wants numbers or rows. Write the SQL.
- "bar"     : a comparison between categories. Write the SQL, "x" = category column, "y" = number column.
- "line"    : a trend over time. Write the SQL, "x" = date column, "y" = number column.
- "diagram" : the user asks for a schema / diagram / relationships. No SQL. Put the table names to draw in "diagram_tables" (empty list = all tables).
- "text"    : a question that needs no data (what a column means, etc). No SQL.

Rules for SQL:
- One SELECT query only, never change data. Do not use WITH, use subqueries instead.
- Add LIMIT 100 or less, unless the question asks for a single total.
- "answer" is short explaination sentence for the user.
"""

st.set_page_config(page_title="Swiggy", page_icon=str(LOGO_BRAND_ICON), layout="wide")
apply_styles()

# lets keep the colours and the numbers we use again and again in one place
ORANGE = "#FC8019"
DARK_BLUE = "#20283D"
DONUT_COLOURS = [ORANGE, "#F6B26B", "#6C83B5", "#63A88A", "#9A7BC2"]
CRORE = 10000000

# the same look for every chart (transparent background and dark text, so the text is easy to read)
CHART_LOOK = dict(height=350, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                  font_color=DARK_BLUE, font_size=13, margin=dict(t=30))


# ---------- sidebar: page and filters ----------
with st.sidebar:
    st.image(str(LOGO_BRAND), width=150)
    st.caption("FOOD INSIGHT INTELLIGENCE")
    page = st.radio("WORKSPACE", ["Executive Overview", "City & Restaurant Analysis",
                                  "Customer & Delivery Analysis", "Revenue Forecasting", "Ask Your Data"])

    st.subheader("Filters")
    date_table, city_table = load_filter_data()
    min_date = pd.to_datetime(date_table.iloc[0]["MIN_DATE"]).date()
    max_date = pd.to_datetime(date_table.iloc[0]["MAX_DATE"]).date()
    selected_dates = st.date_input("Order date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
    city_list = ["All cities"] + sorted(city_table["CITY"].dropna().astype(str).unique().tolist())
    city = st.selectbox("City", city_list)

# the date picker gives only one date until the user clicks the second date
if len(selected_dates) != 2:
    st.info("Choose a start date and an end date to continue.")
    st.stop()
start_date = selected_dates[0]
end_date = selected_dates[1]

# ---------- top banner ----------
logo_text = base64.b64encode(LOGO_BRAND_ICON.read_bytes()).decode()
logo_html = f'<img src="data:image/png;base64,{logo_text}" width="46" style="margin-right:12px; vertical-align:middle;">'

st.markdown(f"""
<div class="topbar">
  <div><div class="eyebrow">DATA & INSIGHTS • REVENUE FORECAST MODEL • RAG CHATBOT</div>
  <h1>{logo_html}Swiggy Data Intelligence</h1>
  <div class="subhead">Food delivery business intelligence · Snowflake + dbt + Python analysis + Rag chatbot</div></div>
  <div class="live-pill"><span class="live-dot"></span>LIVE DATA<br><small>Snowflake [DBT (Bronze • Silver • Gold)]</small></div>
</div>
""", unsafe_allow_html=True)
st.caption(f"{start_date:%d %b %Y} — {end_date:%d %b %Y}  ·  {city}")
st.subheader(page)


# ---------- page 1: executive overview ----------
if page == "Executive Overview":
    kpi_row = load_kpis(start_date, end_date, city).iloc[0]
    revenue = float(kpi_row["SALES_REVENUE"] or 0)
    orders = int(kpi_row["ORDERS"] or 0)
    if orders == 0:
        st.warning("There are no orders for this filter.")
        st.stop()

    # lets show the 5 numbers at the top
    column_1, column_2, column_3, column_4, column_5 = st.columns(5)
    column_1.metric("Sales revenue", f"₹{revenue / CRORE:,.2f} Cr")
    column_2.metric("Orders", f"{orders:,}")
    column_3.metric("Avg. order value", f"₹{revenue / orders:,.0f}")
    column_4.metric("Active restaurants", f"{int(kpi_row['RESTAURANTS'] or 0):,}")
    column_5.metric("Active cities", f"{int(kpi_row['CITIES'] or 0):,}")

    left_column, right_column = st.columns([1.6, 1])

    # lets draw the monthly revenue and orders
    with left_column:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Monthly trend</div>', unsafe_allow_html=True)
            st.caption("Months have 28 to 31 days, so a small difference between two months can come from the days only.")
            monthly_table = load_monthly(start_date, end_date, city)
            monthly_table["MONTH"] = pd.to_datetime(monthly_table["MONTH"])
            revenue_tab, orders_tab = st.tabs(["Revenue", "Orders"])
            with revenue_tab:
                revenue_figure = px.bar(monthly_table, x="MONTH", y="SALES_REVENUE", color_discrete_sequence=[ORANGE],
                                        labels={"SALES_REVENUE": "Revenue (₹)", "MONTH": "Month"})
                revenue_figure.update_layout(**CHART_LOOK)
                st.plotly_chart(revenue_figure, use_container_width=True, theme=None)
            with orders_tab:
                orders_figure = px.bar(monthly_table, x="MONTH", y="ORDERS", color_discrete_sequence=[DARK_BLUE],
                                       labels={"ORDERS": "Orders", "MONTH": "Month"})
                orders_figure.update_layout(**CHART_LOOK)
                st.plotly_chart(orders_figure, use_container_width=True, theme=None)

    # lets draw the payment method donut
    with right_column:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Payment method mix</div>', unsafe_allow_html=True)
            st.caption("Share of orders")
            payment_table = load_payment_mix(start_date, end_date, city)
            payment_figure = px.pie(payment_table, names="PAYMENT_METHOD", values="ORDERS", hole=0.6,
                                    color_discrete_sequence=DONUT_COLOURS)
            payment_figure.update_traces(textinfo="percent+label", textposition="outside")
            payment_figure.update_layout(**CHART_LOOK, showlegend=False)
            st.plotly_chart(payment_figure, use_container_width=True, theme=None)

    left_column, right_column = st.columns([1.1, 1])

    # lets draw the top 10 cities
    with left_column:
        with st.container(border=True):
            st.markdown('<div class="panel-title">City performance</div>', unsafe_allow_html=True)
            st.caption("Top 10 cities by sales revenue")
            city_revenue_table = load_city_revenue(start_date, end_date, city)
            top_10_cities = city_revenue_table.nlargest(10, "SALES_REVENUE").sort_values("SALES_REVENUE")
            city_figure = px.bar(top_10_cities, x="SALES_REVENUE", y="CITY", orientation="h", text_auto=".3s",
                                 color_discrete_sequence=[ORANGE], labels={"SALES_REVENUE": "Revenue (₹)", "CITY": ""})
            city_figure.update_traces(textposition="outside", cliponaxis=False)
            city_figure.update_layout(**CHART_LOOK)
            st.plotly_chart(city_figure, use_container_width=True, theme=None)

    # lets show the delivery, rating and discount numbers
    with right_column:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Operational pulse</div>', unsafe_allow_html=True)
            st.caption("Available data in the selected period")
            delivery_column, rating_column = st.columns(2)
            delivery_column.metric("Avg. delivery", f"{float(kpi_row['AVG_DELIVERY_MIN']):.1f} min")
            rating_column.metric("Avg. rating", f"{float(kpi_row['AVG_RATING']):.2f} / 5")
            st.metric("Discounts given", f"₹{float(kpi_row['DISCOUNTS'] or 0) / CRORE:,.2f} Cr")
            rated_orders = int(kpi_row["RATED_ORDERS"] or 0)
            st.caption(f"Only {rated_orders / orders:.1%} of the orders have a rating. Missing ratings are not counted as zero.")


# ---------- page 2: city and restaurant ----------
elif page == "City & Restaurant Analysis":
    left_column, right_column = st.columns(2)

    with left_column:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Top cities</div>', unsafe_allow_html=True)
            city_revenue_table = load_city_revenue(start_date, end_date, city)
            top_10_cities = city_revenue_table.nlargest(10, "SALES_REVENUE").sort_values("SALES_REVENUE")
            city_figure = px.bar(top_10_cities, x="SALES_REVENUE", y="CITY", orientation="h", text_auto=".3s",
                                 color_discrete_sequence=[ORANGE], labels={"SALES_REVENUE": "Revenue (₹)", "CITY": ""})
            city_figure.update_traces(textposition="outside", cliponaxis=False)
            city_figure.update_layout(**CHART_LOOK)
            st.plotly_chart(city_figure, use_container_width=True, theme=None)
            st.dataframe(city_revenue_table, use_container_width=True, hide_index=True)

    with right_column:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Cuisine performance</div>', unsafe_allow_html=True)
            cuisine_table = load_cuisine_performance(start_date, end_date, city)
            top_10_cuisines = cuisine_table.nlargest(10, "REVENUE").sort_values("REVENUE")
            cuisine_figure = px.bar(top_10_cuisines, x="REVENUE", y="CUISINE", orientation="h", text_auto=".3s",
                                    color_discrete_sequence=["#EAA15A"], labels={"REVENUE": "Revenue (₹)", "CUISINE": ""})
            cuisine_figure.update_traces(textposition="outside", cliponaxis=False)
            cuisine_figure.update_layout(**CHART_LOOK)
            st.plotly_chart(cuisine_figure, use_container_width=True, theme=None)
            st.dataframe(cuisine_table, use_container_width=True, hide_index=True)

    with st.container(border=True):
        st.markdown('<div class="panel-title">Top restaurants</div>', unsafe_allow_html=True)
        restaurant_table = load_restaurant_performance(start_date, end_date, city)
        st.dataframe(restaurant_table, use_container_width=True, hide_index=True)


# ---------- page 3: customer and delivery ----------
elif page == "Customer & Delivery Analysis":
    with st.container(border=True):
        st.markdown('<div class="panel-title">Customer segments</div>', unsafe_allow_html=True)
        segment_table = load_customer_segments(start_date, end_date, city)
        left_column, right_column = st.columns([1, 1.2])
        with left_column:
            segment_figure = px.pie(segment_table, names="AGE_SEGMENT", values="CUSTOMERS", hole=0.6,
                                    color_discrete_sequence=DONUT_COLOURS)
            segment_figure.update_traces(textinfo="percent+label", textposition="outside")
            segment_figure.update_layout(**CHART_LOOK, showlegend=False)
            st.plotly_chart(segment_figure, use_container_width=True, theme=None)
        with right_column:
            st.dataframe(segment_table, use_container_width=True, hide_index=True)

    with st.container(border=True):
        st.markdown('<div class="panel-title">Delivery and rating coverage</div>', unsafe_allow_html=True)
        kpi_row = load_kpis(start_date, end_date, city).iloc[0]
        orders = int(kpi_row["ORDERS"] or 0)
        rated_orders = int(kpi_row["RATED_ORDERS"] or 0)
        delivery_column, rating_column, coverage_column = st.columns(3)
        delivery_column.metric("Average delivery time", f"{float(kpi_row['AVG_DELIVERY_MIN']):.1f} min")
        rating_column.metric("Average customer rating", f"{float(kpi_row['AVG_RATING']):.2f} / 5")
        coverage_column.metric("Rating coverage", f"{rated_orders / orders:.1%}" if orders > 0 else "N/A")


# ---------- page 4: revenue forecasting ----------
elif page == "Revenue Forecasting":
    st.caption("Past quarters are actual revenue, future quarters are predictions of the saved city_revenue_forecast.joblib model.")
    model_path = Path(__file__).resolve().parent / "city_revenue_forecast.joblib"
    if not model_path.exists():
        st.error(f"Model file not found: {model_path}")
        st.stop()

    history = load_quarterly_city_history()
    city_values = sorted(history["CITY"].dropna().astype(str).unique())
    forecast_city = st.selectbox("Forecast city", ["All cities"] + city_values)
    horizon = st.select_slider("How many quarters to forecast", options=[1, 2, 3, 4], value=4)

    forecast = make_forecast(history, model_path, forecast_city, horizon)
    if forecast.empty:
        st.warning("The model could not make a forecast.")
        st.stop()
    if "ACTUAL_REVENUE" not in forecast:
        forecast["ACTUAL_REVENUE"] = None
    actual_rows = forecast.dropna(subset=["ACTUAL_REVENUE"])
    predicted_rows = forecast.dropna(subset=["PREDICTED_REVENUE"])

    # lets show the first and the last predicted quarter
    first_predicted = predicted_rows.iloc[0]
    last_predicted = predicted_rows.iloc[-1]
    column_1, column_2 = st.columns(2)
    column_1.metric(f"Next quarter ({first_predicted['QUARTER']})", f"₹{first_predicted['PREDICTED_REVENUE'] / CRORE:,.2f} Cr")
    column_2.metric(f"Last forecast quarter ({last_predicted['QUARTER']})", f"₹{last_predicted['PREDICTED_REVENUE'] / CRORE:,.2f} Cr")

    # lets draw the actual line (dark) and the forecast line (orange, dashed)
    forecast_figure = go.Figure()
    forecast_figure.add_scatter(x=actual_rows["QUARTER"], y=actual_rows["ACTUAL_REVENUE"],
                                name="Actual revenue", mode="lines+markers", line=dict(color=DARK_BLUE, width=3))
    forecast_figure.add_scatter(x=predicted_rows["QUARTER"], y=predicted_rows["PREDICTED_REVENUE"],
                                name="Forecast", mode="lines+markers", line=dict(color=ORANGE, width=3, dash="dash"))
    forecast_figure.update_layout(**CHART_LOOK, yaxis_title="Revenue (₹)")
    st.plotly_chart(forecast_figure, use_container_width=True, theme=None)
    st.dataframe(forecast, use_container_width=True, hide_index=True)


# ---------- page 5: chatbot (next step) ----------
elif page == "Ask Your Data":
    st.caption("Ask about the gold tables. Say 'give me the sql' for the query, or ask for a table, a bar chart, a line chart or a schema diagram.")

    # lets stop here with a clear message if the Groq key is missing in the .env file
    if not os.getenv("GROQ_API_KEY"):
        st.error("GROQ_API_KEY is missing in your .env file.")
        st.stop()

    # lets keep the chat history in session_state, so it stays after every click
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []

    user_question = st.chat_input("e.g. Top 10 cities by GMV")

    # ---------- step 1: a new question comes, lets build one answer ----------
    if user_question:
        new_answer = {"question": user_question, "show": "text", "text": "", "sql": "",
                      "table": None, "x": None, "y": None, "diagram_tables": []}

        try:
            # lets ask the LLM, it returns JSON text
            groq_client = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")
            llm_response = groq_client.chat.completions.create(
                model=LLM_MODEL_NAME,
                temperature=0,
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": user_question}])
            llm_text = llm_response.choices[0].message.content
            llm_json_text = llm_text[llm_text.find("{"): llm_text.rfind("}") + 1]
            llm_answer = json.loads(llm_json_text)

            new_answer["show"] = llm_answer.get("show", "text")
            new_answer["text"] = llm_answer.get("answer", "")
            new_answer["sql"] = str(llm_answer.get("sql", "")).strip().rstrip(";")
            new_answer["x"] = llm_answer.get("x")
            new_answer["y"] = llm_answer.get("y")
            new_answer["diagram_tables"] = llm_answer.get("diagram_tables", [])

            # lets run the SQL only when the user wants numbers (table, bar or line)
            if new_answer["show"] in ["table", "bar", "line"]:
                sql_text = new_answer["sql"]
                sql_words = re.findall(r"[a-z_]+", sql_text.lower())

                # lets check the SQL is safe: one select query and no changing words
                forbidden_words = ["drop", "delete", "truncate", "alter", "update", "insert", "create", "replace", "merge", "grant", "revoke", "call", "copy"]
                is_safe = True
                if len(sql_words) == 0 or sql_words[0] != "select":
                    is_safe = False
                if ";" in sql_text:
                    is_safe = False
                for forbidden_word in forbidden_words:
                    if forbidden_word in sql_words:
                        is_safe = False

                if is_safe == False:
                    new_answer["show"] = "text"
                    new_answer["text"] = "I did not run that query because it was not a safe SELECT query. Try asking in a different way."
                else:
                    # lets add a LIMIT when the LLM forgot it
                    if "limit" not in sql_words:
                        sql_text = sql_text + " LIMIT 100"
                        new_answer["sql"] = sql_text

                    # lets use query_df from data_access.py, it already connects to Snowflake
                    result_table = query_df(sql_text)

                    # lets change Decimal numbers to normal numbers, so the charts can read them
                    for column_name in result_table.columns:
                        if len(result_table) > 0 and isinstance(result_table[column_name].iloc[0], decimal.Decimal):
                            result_table[column_name] = result_table[column_name].astype(float)

                    new_answer["table"] = result_table

        except Exception as error:
            new_answer["show"] = "text"
            new_answer["text"] = "Sorry, something went wrong: " + str(error)

        st.session_state["chat_messages"].append(new_answer)

    # ---------- step 2: lets show the whole chat, old answers and the new one ----------
    for chat_message in st.session_state["chat_messages"]:
        with st.chat_message("user"):
            st.write(chat_message["question"])

        with st.chat_message("assistant"):
            if chat_message["text"] != "":
                st.write(chat_message["text"])

            if chat_message["show"] == "sql":
                st.code(chat_message["sql"], language="sql")

            elif chat_message["show"] in ["table", "bar", "line"]:
                result_table = chat_message["table"]

                if len(result_table) == 0:
                    st.info("The query ran but returned no rows.")
                elif len(result_table) == 1 and len(result_table.columns) == 1:
                    # lets show a single number as a sentence
                    st.markdown("**" + result_table.columns[0] + " : " + str(result_table.iloc[0, 0]) + "**")
                elif chat_message["show"] == "table":
                    st.dataframe(result_table, hide_index=True, use_container_width=True)
                else:
                    # lets pick the x and y columns, if the LLM named a wrong column we use the first two
                    x_column = chat_message["x"]
                    y_column = chat_message["y"]
                    if x_column not in result_table.columns:
                        x_column = result_table.columns[0]
                    if y_column not in result_table.columns:
                        y_column = result_table.columns[-1]

                    if chat_message["show"] == "bar":
                        chat_chart = px.bar(result_table, x=x_column, y=y_column, text_auto=".3s", color_discrete_sequence=[ORANGE])
                    else:
                        chat_chart = px.line(result_table, x=x_column, y=y_column, color_discrete_sequence=[ORANGE])
                    chat_chart.update_layout(**CHART_LOOK)
                    st.plotly_chart(chat_chart, use_container_width=True, theme=None)

                with st.expander("SQL used"):
                    st.code(chat_message["sql"], language="sql")

            elif chat_message["show"] == "diagram":
                # lets draw the diagram ourselves from the dictionary, not from the LLM
                tables_to_draw = [t for t in chat_message["diagram_tables"] if t in GOLD_TABLE_COLUMNS]
                if len(tables_to_draw) == 0:
                    tables_to_draw = list(GOLD_TABLE_COLUMNS.keys())

                diagram_text = "digraph G {\n rankdir=LR;\n node [shape=box, fontname=Helvetica, fontsize=10, style=filled, fillcolor=white];\n"
                for table_name in tables_to_draw:
                    box_label = table_name + "\\n--------------\\n" + "\\n".join(GOLD_TABLE_COLUMNS[table_name])
                    diagram_text = diagram_text + ' "' + table_name + '" [label="' + box_label + '"];\n'
                for first_table, second_table, join_column in GOLD_TABLE_JOINS:
                    if first_table in tables_to_draw and second_table in tables_to_draw:
                        diagram_text = diagram_text + ' "' + first_table + '" -> "' + second_table + '" [label="' + join_column + '", fontsize=9];\n'
                diagram_text = diagram_text + "}"
                st.graphviz_chart(diagram_text)