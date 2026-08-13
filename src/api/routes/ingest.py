from __future__ import annotations

from fastapi import APIRouter, Request

from src.api.models.ingest_request import IngestRequest

router = APIRouter()


@router.post("/ingest")
def ingest(body: IngestRequest, request: Request):
    dispatcher = request.app.state.dispatcher
    store = request.app.state.store

    record = dispatcher.normalize(body.model_dump())
    store.write(record)
    return {"status": "ok"}
