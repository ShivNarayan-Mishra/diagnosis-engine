"""
App wiring. This is the only file in the project allowed to name concrete
classes (PostgresTraceStore, StructuredRowAdapter, ...). Routes only ever
see request.app.state.store / .dispatcher, never the concrete class.

Swapping an implementation later (e.g. store -> a columnar store, engine ->
v2 logistic regression) means changing exactly the lines in this file.
"""
from __future__ import annotations

from fastapi import FastAPI

from src.adapters.dispatcher import AdapterDispatcher
from src.adapters.structured_row import StructuredRowAdapter
from src.api.routes.diagnose import router as diagnose_router
from src.api.routes.ingest import router as ingest_router
from src.store.postgres import PostgresTraceStore

app = FastAPI(title="AI Pipeline Regression Diagnosis Engine")

# --- Dependency injection: concrete classes named ONLY here ---
app.state.store = PostgresTraceStore()
app.state.dispatcher = AdapterDispatcher(adapters=[StructuredRowAdapter()])

app.include_router(ingest_router)
app.include_router(diagnose_router)


@app.get("/health")
def health():
    return {"status": "ok"}
