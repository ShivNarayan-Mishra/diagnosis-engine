from __future__ import annotations

import os

import psycopg2
from dotenv import load_dotenv

from src.contracts.records import GroundTruth

load_dotenv()


def _connect():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "diagnosisdb"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )


def write_ground_truth(gt: GroundTruth) -> None:
    """Inserts one GroundTruth row into fault_scenarios. Idempotent on scenario_id —
    re-running the same scenario_id is a no-op rather than a duplicate-key error."""
    conn = _connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO fault_scenarios
                        (scenario_id, fault_type, injected_at, affected_factor, affected_value)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (scenario_id) DO NOTHING
                    """,
                    (
                        gt.scenario_id,
                        gt.fault_type,
                        gt.injected_at,
                        gt.affected_factor,
                        gt.affected_value,
                    ),
                )
    finally:
        conn.close()
