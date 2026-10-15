# InsightForge

InsightForge is a local-first business data analysis workspace. Upload a CSV, inspect its quality, explore descriptive statistics and correlations, build interactive charts, and ask questions answered from real analysis tools. The optional AI layer uses an OpenAI-compatible Chat Completions endpoint; the app works without an API key using grounded local summaries.

## Quick start (Windows)

1. Install Python 3.11 or newer.
2. Open PowerShell in this folder and run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   Copy-Item .env.example .env
   uvicorn app.main:app --reload --env-file .env
   ```

3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

You can run `docker compose up --build -d` (Docker Desktop required). This starts PostgreSQL, InsightForge, and a local Ollama model server. It binds the web app to localhost at [http://127.0.0.1:8001](http://127.0.0.1:8001) and stores database, uploaded files, and model files in persistent Docker volumes. The default port is 8001 so the Docker app can run beside a local development server; set `INSIGHTFORGE_PORT=8000` in `.env` to use port 8000 instead.

Download the model once after the containers start:

```powershell
docker compose exec ollama ollama pull qwen3:4b
```

The default `.env.example` configures the local model with no paid API key. `LLM_TIMEOUT_SECONDS` bounds the response wait for cold model startup (default 120 seconds); `OLLAMA_KEEP_ALIVE` keeps the model resident after a request (default 10 minutes). To use a hosted OpenAI-compatible provider instead, change `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` in `.env`, then recreate the app container. Never commit `.env`.

## What it does

- CSV upload with size, row, and column limits; safe, generated dataset IDs
- Type-aware data profiling, missing-value and duplicate checks
- Optional missing-value imputation and duplicate removal, preserving the original upload
- Summary statistics, numeric correlations, categorical counts, and grouped metrics
- Isolation Forest anomaly detection over selected numeric columns
- Deterministic IQR and Z-score anomaly checks, plus Isolation Forest for multivariate outliers
- Named SciPy procedures (Shapiro-Wilk normality, Welch two-group comparison, and Spearman rank correlation) with sample sizes and interpretation caveats
- **Decision Radar:** compare recent and prior business periods, quantify KPI movement, and rank the regions/products contributing to the change
- Interactive Plotly charts for distributions, categories, and relationships
- Deterministic analysis tools the assistant can call (overview, columns, value counts, correlation, grouped metrics)
- Dataset catalog and flexible records stored in PostgreSQL (`JSONB` rows); SQLAlchemy models and Alembic migrations version the schema, while CSV originals and cleaned exports remain on disk
- Validated assistant response format with findings, computed evidence, recommendations, and follow-up questions; the model can only call predefined data-analysis tools (no arbitrary SQL execution)
- Responsive browser interface, readiness and Prometheus metrics endpoints, JSON logs, structured errors, and configurable limits

The landing page includes a synthetic sales scenario with a deliberately weakening region, so the Decision Radar can be explored immediately without preparing a file. It demonstrates how the tool attributes an observed change; it does not claim a real company result or prove a cause.

## API overview

Interactive OpenAPI docs are available at `/docs`.

- `GET /api/health`
- `GET /api/metrics` — Prometheus request count and latency metrics
- `GET /api/datasets`
- `POST /api/datasets` — multipart CSV upload
- `GET /api/datasets/{id}/profile`
- `POST /api/datasets/{id}/clean`
- `GET /api/datasets/{id}/analysis`
- `POST /api/datasets/{id}/chart`
- `POST /api/datasets/{id}/analysis/anomalies`
- `POST /api/datasets/{id}/analysis/statistical-test` (supported names: `normality_shapiro`, `two_group_ttest`, `spearman`)
- `POST /api/datasets/{id}/analysis/decision-brief`
- `POST /api/datasets/{id}/ask`
- `DELETE /api/datasets/{id}`

## Data and limitations

This is a single-user local application. Uploaded CSVs are stored on disk and are not sent to an LLM unless you enable the optional provider; only the question, column metadata, and compact tool results are sent. Docker Compose runs PostgreSQL and stores dataset records as JSONB so arbitrary CSV schemas can be supported. For a no-Docker quick start, the same storage layer uses local CSV and JSON files. The app is designed for localhost use and does not include user accounts or multi-tenant authorization.

## Verify the project

Run the fast analysis checks from the project folder:

```powershell
pytest -q
```

The tests cover statistics, anomaly methods, Decision Radar attribution, validated assistant output, and invalid-column handling. Database persistence is exercised by running the Docker stack and checking `/api/health`; PostgreSQL schema changes apply through Alembic at app startup. Existing unversioned InsightForge tables are preserved and recorded in the initial migration.

## Design notes

The analysis path is deterministic and computes all returned numeric evidence from the uploaded dataset. The LLM may phrase those results, but it cannot run generated SQL or access arbitrary files. Statistical tests report their sample size and avoid claiming causation. For a maintainable next iteration, the current FastAPI routes, analysis functions, assistant, and storage adapter are kept in separate modules; the browser app and backend are deployed together as one simple service.
