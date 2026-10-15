import asyncio

import pandas as pd
import pytest

from app import analysis, assistant


def test_profile_and_overview_return_real_dataset_statistics():
    data = pd.DataFrame({"region": ["east", "west", "east"], "revenue": [10, 30, 20], "orders": [1, 3, 2]})
    result = analysis.overview(data)
    assert result["summary"]["rows"] == 3
    assert result["numeric_summary"]["revenue"]["mean"] == 20
    assert result["correlations"][0]["value"] == 1


def test_decision_brief_attributes_decline_to_segment():
    data = pd.DataFrame({"date": ["2026-01-01", "2026-01-05", "2026-02-01", "2026-02-05"],
                         "sales": [100, 100, 30, 70], "region": ["west", "east", "west", "east"]})
    result = analysis.decision_brief(data, "date", "sales", "region", "sum", "month")
    assert result["status"] == "decline"
    assert result["percent_change"] == -50
    assert result["segment_drivers"][0]["segment"] == "west"


@pytest.mark.parametrize("method", ["iqr", "zscore"])
def test_deterministic_anomaly_methods(method):
    values = list(range(20)) + [1000]
    result = analysis.detect_anomalies(pd.DataFrame({"value": values}), method=method)
    assert result["anomaly_count"] >= 1
    assert result["anomalies"][0]["row"] == 21


def test_statistical_test_reports_sample_and_caveat():
    data = pd.DataFrame({"value": [1, 2, 3, 4, 5, 6, 7, 8]})
    result = analysis.statistical_test(data, "normality_shapiro", "value")
    assert result["sample_size"] == 8
    assert 0 <= result["p_value"] <= 1
    assert "causation" in result["caveat"]


def test_ai_response_has_a_stable_validated_shape():
    result = assistant.local_answer("summarize", pd.DataFrame({"sales": [2, 4, 6]}))
    assert {"answer", "key_findings", "evidence", "charts", "recommendations", "follow_up_questions", "source"} <= result.keys()


def test_total_metric_is_computed_from_numeric_rows():
    result = analysis.tool_metric(pd.DataFrame({"revenue": [10, 20, None, "30"]}), "revenue", "sum")
    assert result == {"column": "revenue", "operation": "sum", "value": 60.0, "sample_size": 3}


def test_simple_total_revenue_uses_dataset_metric_without_llm(monkeypatch):
    monkeypatch.setattr(assistant, "LLM_API_KEY", "configured")
    result = asyncio.run(assistant.answer("What is the total revenue in the dataset?", pd.DataFrame({"revenue": [514_000.00, 911.16]})))
    assert result["answer"] == "The total revenue is 514911.16, calculated from 2 numeric rows."
    assert result["evidence"][0] == {"column": "revenue", "operation": "sum", "value": 514911.16, "sample_size": 2}
    assert result["source"] == "analysis tool"


def test_decision_brief_rejects_unknown_columns():
    with pytest.raises(ValueError, match="Unknown column"):
        analysis.decision_brief(pd.DataFrame({"date": ["2026-01-01"]}), "missing", "sales")
