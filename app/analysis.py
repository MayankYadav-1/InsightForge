from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import IsolationForest


def _json_value(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value.item() if isinstance(value, np.generic) else value


def profile(df: pd.DataFrame) -> dict:
    columns = []
    for name in df.columns:
        s = df[name]
        numeric = pd.api.types.is_numeric_dtype(s)
        sample = s.dropna().astype(str).head(3).tolist()
        item = {"name": str(name), "dtype": str(s.dtype), "kind": "numeric" if numeric else "categorical", "missing": int(s.isna().sum()), "missing_pct": round(float(s.isna().mean() * 100), 2), "unique": int(s.nunique(dropna=True)), "samples": sample}
        if numeric and s.notna().any():
            item["min"] = _json_value(s.min())
            item["max"] = _json_value(s.max())
            item["mean"] = _json_value(s.mean())
        columns.append(item)
    return {"rows": int(len(df)), "columns": int(len(df.columns)), "duplicate_rows": int(df.duplicated().sum()), "memory_bytes": int(df.memory_usage(deep=True).sum()), "column_details": columns}


def overview(df: pd.DataFrame) -> dict:
    numeric = df.select_dtypes(include="number")
    stats = {}
    if not numeric.empty:
        desc = numeric.describe(percentiles=[.25, .5, .75]).replace({np.nan: None})
        stats = {str(col): {str(k): _json_value(v) for k, v in desc[col].items()} for col in desc.columns}
    correlations = []
    if numeric.shape[1] >= 2:
        corr = numeric.corr(min_periods=2)
        for i, left in enumerate(corr.columns):
            for right in corr.columns[i + 1:]:
                value = corr.loc[left, right]
                if pd.notna(value):
                    correlations.append({"left": str(left), "right": str(right), "value": round(float(value), 4)})
    correlations.sort(key=lambda x: abs(x["value"]), reverse=True)
    categorical = {}
    for col in df.select_dtypes(exclude="number").columns:
        categorical[str(col)] = [{"value": str(k), "count": int(v)} for k, v in df[col].value_counts(dropna=False).head(10).items()]
    return {"summary": profile(df), "numeric_summary": stats, "correlations": correlations[:30], "categorical_counts": categorical}


def tool_overview(df: pd.DataFrame) -> dict:
    p = profile(df)
    return {"rows": p["rows"], "columns": p["columns"], "duplicate_rows": p["duplicate_rows"], "columns_detail": p["column_details"]}


def tool_value_counts(df: pd.DataFrame, column: str, limit: int = 10) -> dict:
    s = _column(df, column)
    limit = max(1, min(int(limit), 30))
    counts = s.value_counts(dropna=False).head(limit)
    return {"column": column, "values": [{"value": "(missing)" if pd.isna(k) else str(k), "count": int(v)} for k, v in counts.items()]}


def tool_correlation(df: pd.DataFrame, column: str) -> dict:
    s = _column(df, column)
    if not pd.api.types.is_numeric_dtype(s):
        raise ValueError(f"{column} is not numeric")
    others = df.select_dtypes(include="number").corrwith(s).drop(labels=[column], errors="ignore").dropna().sort_values(key=lambda x: x.abs(), ascending=False)
    return {"column": column, "correlations": [{"column": str(k), "correlation": round(float(v), 4)} for k, v in others.items()]}


def tool_grouped_metric(df: pd.DataFrame, group_by: str, metric: str, operation: str = "mean") -> dict:
    group, values = _column(df, group_by), _column(df, metric)
    if not pd.api.types.is_numeric_dtype(values):
        raise ValueError(f"{metric} must be numeric")
    if operation not in {"mean", "sum", "count", "median", "min", "max"}:
        raise ValueError("Unsupported operation")
    result = getattr(df.assign(**{"__group": group, "__metric": values}).groupby("__group", dropna=False)["__metric"], operation)().sort_values(ascending=False).head(30)
    return {"group_by": group_by, "metric": metric, "operation": operation, "values": [{"group": str(k), "value": _json_value(v)} for k, v in result.items()]}


def tool_metric(df: pd.DataFrame, column: str, operation: str = "sum") -> dict:
    """Calculate one safe aggregate directly from a numeric dataset column."""
    values = pd.to_numeric(_column(df, column), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if operation not in {"sum", "mean", "median", "min", "max", "count"}:
        raise ValueError("Unsupported metric operation")
    if operation != "count" and values.empty:
        raise ValueError(f"{column} has no numeric values")
    value = len(values) if operation == "count" else getattr(values, operation)()
    return {"column": column, "operation": operation, "value": _json_value(value), "sample_size": int(len(values))}


def _column(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        raise ValueError(f"Unknown column: {name}")
    return df[name]


def chart(df: pd.DataFrame, kind: str, x: str, y: str | None = None) -> dict:
    import plotly.express as px
    _column(df, x)
    if kind not in {"histogram", "bar", "scatter", "box"}:
        raise ValueError("Chart type must be histogram, bar, scatter, or box")
    if kind in {"scatter", "box"} and not y:
        raise ValueError(f"{kind} charts require a Y column")
    if y:
        _column(df, y)
    sample = df if len(df) <= 10000 else df.sample(10000, random_state=7)
    if kind == "histogram":
        fig = px.histogram(sample, x=x, title=f"Distribution of {x}", template="plotly_white")
    elif kind == "bar":
        counts = sample[x].astype(str).value_counts().head(30).rename_axis(x).reset_index(name="count")
        fig = px.bar(counts, x=x, y="count", title=f"Top values in {x}", template="plotly_white")
    elif kind == "scatter":
        fig = px.scatter(sample, x=x, y=y, title=f"{y} vs {x}", template="plotly_white", opacity=.72)
    else:
        fig = px.box(sample, x=x, y=y, title=f"{y} by {x}", template="plotly_white")
    return fig.to_json()


def clean_dataframe(df: pd.DataFrame, drop_duplicates: bool, impute: str) -> tuple[pd.DataFrame, dict]:
    result = df.copy()
    removed = int(result.duplicated().sum()) if drop_duplicates else 0
    if drop_duplicates:
        result = result.drop_duplicates()
    filled = {}
    if impute not in {"none", "median", "mean", "mode"}:
        raise ValueError("Imputation must be none, median, mean, or mode")
    for col in result.columns:
        missing = int(result[col].isna().sum())
        if not missing or impute == "none":
            continue
        if pd.api.types.is_numeric_dtype(result[col]) and impute in {"median", "mean"}:
            value = result[col].median() if impute == "median" else result[col].mean()
        else:
            mode = result[col].mode(dropna=True)
            if mode.empty:
                continue
            value = mode.iloc[0]
        result[col] = result[col].fillna(value)
        filled[str(col)] = {"count": missing, "strategy": impute}
    return result, {"duplicates_removed": removed, "missing_filled": filled, "rows": len(result)}


def detect_anomalies(df: pd.DataFrame, columns: list[str] | None = None, method: str = "isolation_forest") -> dict:
    numeric = df.select_dtypes(include="number")
    if columns:
        missing = [name for name in columns if name not in numeric.columns]
        if missing:
            raise ValueError(f"Unknown or non-numeric columns: {', '.join(missing)}")
        numeric = numeric[columns]
    if numeric.shape[1] == 0:
        raise ValueError("Choose at least one numeric column")
    working = numeric.replace([np.inf, -np.inf], np.nan)
    working = working.fillna(working.median()).fillna(0)
    if method in {"iqr", "zscore"}:
        flags = pd.DataFrame(False, index=working.index, columns=working.columns)
        for col in working:
            values = working[col].dropna()
            if values.empty:
                continue
            if method == "iqr":
                q1, q3 = values.quantile([.25, .75]); spread = q3 - q1
                flags[col] = (working[col] < q1 - 1.5 * spread) | (working[col] > q3 + 1.5 * spread)
            else:
                sd = values.std(ddof=0)
                if sd > 0:
                    flags[col] = ((working[col] - values.mean()).abs() / sd) > 3
        mask = flags.any(axis=1)
        rows = [{"row": int(df.index.get_loc(idx)) + 1,
                 "signals": [str(c) for c in flags.columns[flags.loc[idx]]],
                 "values": {str(k): _json_value(v) for k, v in df.loc[idx, numeric.columns].items()}}
                for idx in working.index[mask][:100]]
        return {"algorithm": "IQR" if method == "iqr" else "Z-score (|z| > 3)", "sampled_rows": len(working), "anomaly_count": int(mask.sum()), "anomalies": rows}
    if method != "isolation_forest":
        raise ValueError("method must be isolation_forest, iqr, or zscore")
    if len(working) < 10:
        raise ValueError("Isolation Forest needs at least 10 rows")
    sample = working if len(working) <= 50000 else working.sample(50000, random_state=17)
    model = IsolationForest(n_estimators=120, contamination="auto", random_state=17, n_jobs=-1)
    labels = model.fit_predict(sample)
    scores = model.decision_function(sample)
    anomaly_rows = []
    for position in np.flatnonzero(labels == -1)[:100]:
        idx = sample.index[position]
        anomaly_rows.append({"row": int(df.index.get_loc(idx)) + 1, "score": round(float(scores[position]), 5), "values": {str(k): _json_value(v) for k, v in df.loc[idx, numeric.columns].items()}})
    return {"algorithm": "Isolation Forest", "sampled_rows": len(sample), "anomaly_count": int((labels == -1).sum()), "anomalies": anomaly_rows}


def statistical_test(df: pd.DataFrame, test: str, column: str, group_column: str | None = None, group_a: str | None = None, group_b: str | None = None) -> dict:
    """Run a bounded, named SciPy test; never accept executable expressions."""
    values = pd.to_numeric(_column(df, column), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if test == "normality_shapiro":
        sample = values.sample(min(len(values), 5000), random_state=19) if len(values) else values
        if len(sample) < 3:
            raise ValueError("Shapiro-Wilk needs at least 3 numeric observations")
        statistic, p_value = stats.shapiro(sample)
        label = "Shapiro-Wilk normality test"
    elif test == "two_group_ttest":
        if not group_column or group_a is None or group_b is None:
            raise ValueError("Provide a group column and two group values")
        groups = _column(df, group_column).astype(str)
        left = pd.to_numeric(df.loc[groups == group_a, column], errors="coerce").dropna()
        right = pd.to_numeric(df.loc[groups == group_b, column], errors="coerce").dropna()
        if len(left) < 2 or len(right) < 2:
            raise ValueError("Each group needs at least 2 numeric observations")
        statistic, p_value = stats.ttest_ind(left, right, equal_var=False)
        label = "Welch two-sample t-test"
        return _test_result(label, statistic, p_value, len(left) + len(right), {"group_a": group_a, "n_a": len(left), "mean_a": float(left.mean()), "group_b": group_b, "n_b": len(right), "mean_b": float(right.mean())})
    elif test == "spearman":
        if not group_column:
            raise ValueError("Provide a second numeric column as group_column")
        paired = pd.DataFrame({"x": pd.to_numeric(df[column], errors="coerce"), "y": pd.to_numeric(df[group_column], errors="coerce")}).replace([np.inf, -np.inf], np.nan).dropna()
        if len(paired) < 3:
            raise ValueError("Spearman correlation needs at least 3 paired observations")
        statistic, p_value = stats.spearmanr(paired.x, paired.y)
        return _test_result("Spearman rank correlation", statistic, p_value, len(paired), {"columns": [column, group_column], "correlation": float(statistic)})
    else:
        raise ValueError("test must be normality_shapiro, two_group_ttest, or spearman")
    return _test_result(label, statistic, p_value, len(sample), {})


def _test_result(name: str, statistic: float, p_value: float, n: int, details: dict) -> dict:
    p = float(p_value)
    return {"test": name, "statistic": float(statistic), "p_value": p, "sample_size": int(n),
            "interpretation": "Evidence against the null hypothesis at alpha=0.05" if p < .05 else "Insufficient evidence against the null hypothesis at alpha=0.05",
            "alpha": .05, "details": details, "caveat": "Statistical significance does not establish practical importance or causation."}


def decision_brief(
    df: pd.DataFrame,
    date_column: str,
    metric_column: str,
    segment_column: str | None = None,
    aggregation: str = "sum",
    period: str = "auto",
) -> dict:
    """Compare the latest two populated periods and attribute movement to segments."""
    date_values = _column(df, date_column)
    metric_values = _column(df, metric_column)
    if not pd.api.types.is_numeric_dtype(metric_values):
        metric_values = pd.to_numeric(metric_values, errors="coerce")
    metric_values = metric_values.replace([np.inf, -np.inf], np.nan)
    if aggregation not in {"sum", "mean", "count"}:
        raise ValueError("Aggregation must be sum, mean, or count")
    if period not in {"auto", "day", "week", "month"}:
        raise ValueError("Period must be auto, day, week, or month")
    if segment_column:
        segment_values = _column(df, segment_column)
    else:
        segment_values = pd.Series("All records", index=df.index)

    dates = pd.to_datetime(date_values, errors="coerce", utc=True).dt.tz_convert(None)
    valid = dates.notna() & metric_values.notna()
    work = pd.DataFrame({"_date": dates[valid], "_metric": metric_values[valid], "_segment": segment_values[valid].fillna("(missing)").astype(str)})
    if len(work) < 2:
        raise ValueError("Need at least two rows with a valid date and numeric metric")

    span_days = int((work["_date"].max() - work["_date"].min()).days)
    resolved_period = period
    if resolved_period == "auto":
        resolved_period = "day" if span_days <= 45 else "week" if span_days <= 90 else "month"
    aliases = {"day": "D", "week": "W", "month": "M"}
    work["_period"] = pd.PeriodIndex(work["_date"], freq=aliases[resolved_period]).start_time
    grouped = work.groupby("_period")["_metric"].agg(aggregation).sort_index()
    if len(grouped) < 2:
        raise ValueError("The selected date range contains only one populated period; choose a shorter period or add more history")

    previous_period, current_period = grouped.index[-2], grouped.index[-1]
    previous_value, current_value = float(grouped.iloc[-2]), float(grouped.iloc[-1])
    change = current_value - previous_value
    percent_change = None if previous_value == 0 else (change / abs(previous_value)) * 100
    if previous_value == 0 and current_value != 0:
        status = "new_activity"
    elif percent_change is not None and percent_change <= -15:
        status = "decline"
    elif percent_change is not None and percent_change >= 15:
        status = "growth"
    else:
        status = "stable"

    segment_values_by_period = work.groupby(["_period", "_segment"])["_metric"].agg(aggregation).unstack(fill_value=0)
    previous_segments = segment_values_by_period.loc[previous_period] if previous_period in segment_values_by_period.index else pd.Series(dtype=float)
    current_segments = segment_values_by_period.loc[current_period] if current_period in segment_values_by_period.index else pd.Series(dtype=float)
    segment_deltas = current_segments.subtract(previous_segments, fill_value=0)
    segment_deltas = segment_deltas.reindex(segment_deltas.abs().sort_values(ascending=False).index).head(8)
    drivers = []
    for name, delta in segment_deltas.items():
        share = (float(delta) / change * 100) if change else None
        drivers.append({
            "segment": str(name),
            "previous": _json_value(previous_segments.get(name, 0)),
            "current": _json_value(current_segments.get(name, 0)),
            "change": _json_value(delta),
            "contribution_pct": round(share, 1) if share is not None else None,
        })

    label_format = "%Y-%m-%d" if resolved_period == "day" else "%Y-%m-%d"
    previous_label, current_label = previous_period.strftime(label_format), current_period.strftime(label_format)
    if status == "decline":
        main_driver = next((item for item in drivers if item["change"] < 0), None)
        if main_driver:
            share_text = f"about {abs(main_driver['contribution_pct']):.0f}% of the net movement" if aggregation != "mean" and main_driver["contribution_pct"] is not None else "a meaningful part of the movement"
            recommendation = f"Start by checking {main_driver['segment']}; it accounts for {share_text}. Compare stock availability, pricing, campaign activity, and source records across the two periods before changing spend."
        else:
            recommendation = "Check whether the change is broad-based, then review availability, pricing, campaign activity, and source records before changing spend."
    elif status in {"growth", "new_activity"}:
        recommendation = "Confirm the increase is present in source transactions and identify whether it is broad-based or concentrated in one segment before treating it as a new baseline."
    else:
        recommendation = "No large period-over-period movement was found at the 15% review threshold. Keep tracking the same metric and investigate any segment-level movement that matters to your business."

    return {
        "metric": metric_column,
        "aggregation": aggregation,
        "period": resolved_period,
        "current": {"label": current_label, "value": _json_value(current_value), "rows": int((work["_period"] == current_period).sum())},
        "previous": {"label": previous_label, "value": _json_value(previous_value), "rows": int((work["_period"] == previous_period).sum())},
        "change": _json_value(change),
        "percent_change": round(percent_change, 1) if percent_change is not None else None,
        "status": status,
        "segment_column": segment_column,
        "segment_drivers": drivers,
        "coverage": {"valid_rows": int(len(work)), "excluded_rows": int(len(df) - len(work)), "populated_periods": int(len(grouped)), "threshold_pct": 15},
        "recommendation": recommendation,
        "interpretation_note": "This is a descriptive comparison, not proof of cause. Segment contribution is additive for sums and counts; for means, it compares segment averages.",
    }
