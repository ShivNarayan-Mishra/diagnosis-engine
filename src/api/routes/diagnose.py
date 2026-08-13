from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request

router = APIRouter()


@router.get("/diagnose")
def diagnose(
    request: Request,
    start: datetime = Query(...),
    end: datetime = Query(...),
    branch: str | None = Query(None),
):
    store = request.app.state.store
    # Phase 1: just prove the round-trip works. No detection/diagnosis yet —
    # that's Phase 3 (ChangepointDetector) and Phase 4 (DiagnosisEngine).
    traces = list(store.query_window(start, end, branch))
    return {
        "trace_count": len(traces),
        "hypotheses": [],  # always empty until Phase 4
    }
