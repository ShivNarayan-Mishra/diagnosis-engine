"""
PostgresTraceStore — implements TraceStore against the Dockerized Postgres.

Two operations only, on purpose:
  write()        -> one parameterized INSERT
  query_window()  -> one parameterized SELECT on the (timestamp, branch) index

Uses %s placeholders everywhere. Never f-strings into SQL — that's a SQL
injection vector even in a solo dev project, and the habit matters more than
the specific risk here.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import datetime

import psycopg2
from dotenv import load_dotenv

from src.contracts.interfaces import TraceStore
from src.contracts.records import TraceRecord

load_dotenv()


class PostgresTraceStore(TraceStore):
    def __init__(self) -> None:
        self._conn_kwargs = dict(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.getenv("POSTGRES_DB", "diagnosisdb"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        )

    def _connect(self):
        return psycopg2.connect(**self._conn_kwargs)

    def write(self, trace: TraceRecord) -> None:
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO traces
                            (request_id, timestamp, outcome, branch,
                             latency_ms, factors, injected_fault_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            trace.request_id,
                            trace.timestamp,
                            trace.outcome,
                            trace.branch,
                            trace.latency_ms,
                            json.dumps(trace.factors),
                            trace.injected_fault_id,
                        ),
                    )
        finally:
            conn.close()

    def query_window(
        self, start: datetime, end: datetime, branch: str | None = None
    ) -> Iterable[TraceRecord]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if branch is None:
                    cur.execute(
                        """
                        SELECT request_id, timestamp, outcome, branch,
                               latency_ms, factors, injected_fault_id
                        FROM traces
                        WHERE timestamp BETWEEN %s AND %s
                        ORDER BY timestamp
                        """,
                        (start, end),
                    )
                else:
                    cur.execute(
                        """
                        SELECT request_id, timestamp, outcome, branch,
                               latency_ms, factors, injected_fault_id
                        FROM traces
                        WHERE timestamp BETWEEN %s AND %s AND branch = %s
                        ORDER BY timestamp
                        """,
                        (start, end, branch),
                    )
                rows = cur.fetchall()
        finally:
            conn.close()

        return [
            TraceRecord(
                request_id=r[0],
                timestamp=r[1],
                outcome=r[2],
                branch=r[3],
                latency_ms=r[4],
                factors=r[5] or {},
                injected_fault_id=r[6],
            )
            for r in rows
        ]
