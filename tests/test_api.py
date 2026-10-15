from fastapi.testclient import TestClient

from app import storage
from app.main import app


def test_upload_profile_and_statistical_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/datasets", files={"file": ("sales.csv", "region,sales\neast,10\nwest,12\neast,11\nwest,14\neast,12\nwest,15\n", "text/csv")})
        assert response.status_code == 200, response.text
        dataset_id = response.json()["dataset"]["id"]
        assert client.get(f"/api/datasets/{dataset_id}/profile").json()["rows"] == 6
        result = client.post(f"/api/datasets/{dataset_id}/analysis/statistical-test", json={"test": "normality_shapiro", "column": "sales"})
        assert result.status_code == 200, result.text
        assert result.json()["sample_size"] == 6
        assert client.post(f"/api/datasets/{dataset_id}/analysis/anomalies", json={"method": "zscore"}).status_code == 200
        assert client.delete(f"/api/datasets/{dataset_id}").status_code == 204


def test_upload_rejects_non_csv():
    with TestClient(app) as client:
        response = client.post("/api/datasets", files={"file": ("data.xlsx", b"not csv", "application/octet-stream")})
        assert response.status_code == 400
