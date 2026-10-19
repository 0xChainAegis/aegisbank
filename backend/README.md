# AegisBank API

FastAPI service for the AegisBank trusted-agent MVP.

```powershell
uv sync
uv run uvicorn aegisbank_api.main:app --reload --port 8000
```

The API is local-first and uses SQLite. All banking tool results are simulated.
