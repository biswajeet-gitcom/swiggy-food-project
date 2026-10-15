from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import streamlit as st

# Matches the artifact's intended feature contract shown in the model-save code.
EXPECTED_FEATURES = [
    "LAST_QUARTER_VS_HISTORY",
    "LAST_2_QUARTER_CHANGE",
    "CITY_SIZE_LOG",
    "QUARTERS_OF_HISTORY",
    "QUARTER_NUMBER",
    "PREV_1Q_AOV",
    "PREV_1Q_CUSTOMERS_PER_ORDER",
    "PREV_1Q_AVG_ITEMS_PER_ORDER",
    "PREV_1Q_DISCOUNT_SHARE",
    "PREV_1Q_UPI_SHARE",
]

@st.cache_resource(show_spinner=False)
def load_artifact(path_string, modified_time):
    # mtime is part of cache key so replacing the joblib file reloads it.
    artifact = joblib.load(Path(path_string))
    if not isinstance(artifact, dict):
        raise TypeError("Expected joblib artifact dictionary with estimator and feature_columns.")
    if "estimator" not in artifact or "feature_columns" not in artifact:
        raise KeyError("Artifact must contain 'estimator' and 'feature_columns'.")
    return artifact

def make_forecast(history, model_path, city, horizon=4):
    path = Path(model_path)
    artifact = load_artifact(str(path), path.stat().st_mtime)
    estimator = artifact["estimator"]
    scaler = artifact.get("scaler")
    features = list(artifact["feature_columns"])
    formula = artifact.get("forecast_formula")
    target = artifact.get("target", "REVENUE_GROWTH_RATIO")

    df = history.copy()
    df["QUARTER"] = df["QUARTER"].astype(str)
    if city != "All cities":
        df = df[df["CITY"].astype(str) == str(city)]
    if df.empty:
        return pd.DataFrame()

    # If "All cities", forecast each city's revenue independently, then sum by quarter.
    outputs = []
    city_groups = [(str(name), group.copy()) for name, group in df.groupby("CITY")] if city == "All cities" else [(str(city), df.copy())]
    for city_name, group in city_groups:
        group = group.sort_values("QUARTER_START").copy()
        revenue_col = "QUARTER_REVENUE"
        if revenue_col not in group:
            raise KeyError(f"History requires {revenue_col}.")
        rev = pd.to_numeric(group[revenue_col], errors="coerce").fillna(0).to_numpy(dtype=float)
        if len(rev) < 2:
            continue
        qperiods = pd.PeriodIndex(group["QUARTER"].astype(str), freq="Q")
        qnums = [p.quarter for p in qperiods]
        last = group.iloc[-1]
        quarter_days = np.array([
            (period.end_time.normalize() - period.start_time).days + 1
            for period in qperiods
        ], dtype=float)

        # The model's revenue trend features use revenue per day.
        daily_revenue = rev / quarter_days
        daily_history = list(daily_revenue)

        quarter_orders = float(last.get("QUARTER_ORDERS", 0) or 0)
        prev_aov = float(rev[-1] / max(quarter_orders, 1))
        prev_customers_per_order = (
            float(last.get("UNIQUE_CUSTOMERS", 0) or 0)
            / max(quarter_orders, 1)
        )
        prev_items = float(last.get("AVG_ITEMS_PER_ORDER", 0) or 0)
        prev_discount_share = float(last.get("DISCOUNT_SHARE", 0) or 0)
        prev_upi_share = float(last.get("UPI_SHARE", 0) or 0)

        for step in range(1, int(horizon) + 1):
            next_period = qperiods[-1] + step
            days_in_forecast_quarter = (
                next_period.end_time.normalize() - next_period.start_time
            ).days + 1

            previous_average_per_day = float(np.mean(daily_history))
            last_quarter_per_day = daily_history[-1]
            prior_quarter_per_day = daily_history[-2]

            features_row = {
                "LAST_QUARTER_VS_HISTORY": (
                    last_quarter_per_day / max(previous_average_per_day, 1.0)
                ),
                "LAST_2_QUARTER_CHANGE": (
                    last_quarter_per_day / max(prior_quarter_per_day, 1.0)
                ),
                "CITY_SIZE_LOG": np.log1p(max(previous_average_per_day, 0)),
                "QUARTERS_OF_HISTORY": len(daily_history),
                "QUARTER_NUMBER": next_period.quarter,
                "PREV_1Q_AOV": prev_aov,
                "PREV_1Q_CUSTOMERS_PER_ORDER": prev_customers_per_order,
                "PREV_1Q_AVG_ITEMS_PER_ORDER": prev_items,
                "PREV_1Q_DISCOUNT_SHARE": prev_discount_share,
                "PREV_1Q_UPI_SHARE": prev_upi_share,
            }

            missing = [feature for feature in features if feature not in features_row]
            if missing:
                raise ValueError(
                    "Feature values unavailable for model columns: "
                    + ", ".join(missing)
                )

            X = pd.DataFrame(
                [[features_row[feature] for feature in features]],
                columns=features
            )

            if scaler is not None:
                X_input = scaler.transform(X)
            else:
                X_input = X

            growth = float(np.asarray(estimator.predict(X_input)).reshape(-1)[0])
            growth = max(0.0, growth)

            base_quarter_revenue = (
                previous_average_per_day * days_in_forecast_quarter
            )
            predicted = growth * base_quarter_revenue

            outputs.append({
                "CITY": city_name,
                "QUARTER": str(next_period),
                "PREDICTED_REVENUE": predicted,
                "PREDICTED_GROWTH_RATIO": growth,
                "ACTUAL_REVENUE": np.nan,
                "ROW_TYPE": "Forecast",
            })

            # Use the predicted daily revenue as history for the next forecast step.
            daily_history.append(predicted / days_in_forecast_quarter)

    forecasts = pd.DataFrame(outputs)
    # Add actual quarters for context. Limit history display to recent quarters for performance.
    actual = df.copy()
    actual = actual.sort_values("QUARTER_START").groupby(["CITY", "QUARTER"], as_index=False).tail(8)
    actual = actual.rename(columns={"QUARTER_REVENUE": "ACTUAL_REVENUE"})
    actual["PREDICTED_REVENUE"] = np.nan
    actual["PREDICTED_GROWTH_RATIO"] = np.nan
    actual["ROW_TYPE"] = "Actual"
    actual = actual[["CITY", "QUARTER", "ACTUAL_REVENUE", "PREDICTED_REVENUE", "PREDICTED_GROWTH_RATIO", "ROW_TYPE"]]
    if city == "All cities" and not forecasts.empty:
        forecasts = forecasts.groupby("QUARTER", as_index=False).agg(
            PREDICTED_REVENUE=("PREDICTED_REVENUE", "sum"),
            PREDICTED_GROWTH_RATIO=("PREDICTED_GROWTH_RATIO", "mean"))
        forecasts["CITY"] = "All cities"
        forecasts["ACTUAL_REVENUE"] = np.nan
        forecasts["ROW_TYPE"] = "Forecast"
        actual = actual.groupby("QUARTER", as_index=False).agg(ACTUAL_REVENUE=("ACTUAL_REVENUE", "sum"))
        actual["CITY"] = "All cities"
        actual["PREDICTED_REVENUE"] = np.nan
        actual["PREDICTED_GROWTH_RATIO"] = np.nan
        actual["ROW_TYPE"] = "Actual"
        actual = actual[["CITY", "QUARTER", "ACTUAL_REVENUE", "PREDICTED_REVENUE", "PREDICTED_GROWTH_RATIO", "ROW_TYPE"]]
    result = pd.concat([actual, forecasts], ignore_index=True, sort=False)
    result = result.sort_values("QUARTER")
    return result
