from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

try:
    from analysis.llm_context import build_llm_context
    from app_config import APP_NAME, EXPORT_DIR
    from llm_client import analyze_strategy_context
    from performance import build_performance_summary
    from storage import StorageManager
except ImportError:  # pragma: no cover - package import path
    from .analysis.llm_context import build_llm_context
    from .app_config import APP_NAME, EXPORT_DIR
    from .llm_client import analyze_strategy_context
    from .performance import build_performance_summary
    from .storage import StorageManager


SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

app = FastAPI(title=f"{APP_NAME} Local Readonly API", version="1.0")
storage: StorageManager | None = None


def _storage() -> StorageManager:
    global storage
    if storage is None:
        storage = StorageManager()
    return storage


def _validate_session_id(session_id: str) -> str:
    if not SESSION_ID_RE.fullmatch(session_id or ""):
        raise HTTPException(status_code=400, detail="invalid session_id")
    return session_id


def _df_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _row_counts(session_id: str) -> dict[str, int]:
    database = _storage()
    return {
        "trades": len(database.fetch_table("trades", "session_id=?", (session_id,))),
        "trade_events": len(database.fetch_table("trade_events", "session_id=?", (session_id,))),
        "event_windows": len(database.fetch_table("event_windows", "session_id=?", (session_id,))),
        "event_features": len(database.fetch_table("event_features", "session_id=?", (session_id,))),
        "account_equity": len(database.fetch_table("account_equity", "session_id=?", (session_id,))),
    }


def _export_dir_for_session(session_id: str) -> Path | None:
    path = EXPORT_DIR / f"session_{session_id}"
    return path if path.exists() else None


@app.get("/health")
def health():
    return {"status": "ok", "app": APP_NAME}


@app.get("/api/sessions")
def list_sessions():
    rows = _storage().fetch_table("sessions")
    rows.sort(key=lambda r: str(r.get("last_saved_at") or ""), reverse=True)
    allowed = ["session_id", "symbol", "interval", "start_date_bjt", "end_date_bjt", "last_saved_at"]
    return [{k: row.get(k) for k in allowed} for row in rows[:50]]


@app.get("/api/session/{session_id}/summary")
def session_summary(session_id: str):
    session_id = _validate_session_id(session_id)
    database = _storage()
    sessions = database.fetch_table("sessions", "session_id=?", (session_id,))
    if not sessions:
        raise HTTPException(status_code=404, detail="session not found")
    trades = database.fetch_table("trades", "session_id=?", (session_id,))
    equity = database.fetch_table("account_equity", "session_id=?", (session_id,))
    return {
        "session_info": {k: v for k, v in sessions[0].items() if "path" not in str(k).lower()},
        "performance_summary": build_performance_summary(trades, equity, sessions[0].get("initial_equity")),
        "row_counts": _row_counts(session_id),
    }


@app.get("/api/session/{session_id}/llm-context")
def llm_context(session_id: str, max_rows: int = 20):
    session_id = _validate_session_id(session_id)
    database = _storage()
    if not database.fetch_table("sessions", "session_id=?", (session_id,)):
        raise HTTPException(status_code=404, detail="session not found")
    context = build_llm_context(session_id, database, _export_dir_for_session(session_id), max_rows=max_rows)
    return JSONResponse(context)


@app.post("/api/session/{session_id}/llm-analysis/mock")
def mock_llm_analysis(session_id: str):
    session_id = _validate_session_id(session_id)
    database = _storage()
    if not database.fetch_table("sessions", "session_id=?", (session_id,)):
        raise HTTPException(status_code=404, detail="session not found")
    context = build_llm_context(session_id, database, _export_dir_for_session(session_id), max_rows=20)
    return analyze_strategy_context(context, provider="mock")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="127.0.0.1", port=8765, reload=False)
