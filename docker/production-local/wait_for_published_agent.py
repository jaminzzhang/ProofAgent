"""Keep the Executor container alive until the sole production Agent is active."""

from __future__ import annotations

import os
import time

from sqlalchemy import create_engine, text


def main() -> None:
    dsn = os.environ["PROOF_AGENT_POSTGRES_DSN"]
    engine = create_engine(dsn, pool_pre_ping=True)
    try:
        while True:
            with engine.connect() as connection:
                count = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM active_agent_versions "
                        "WHERE agent_id = :agent_id"
                    ),
                    {"agent_id": "agent_management_insurance_specialist"},
                ).scalar_one()
            if int(count) == 1:
                break
            print("waiting for the sole production Agent publication", flush=True)
            time.sleep(5)
    finally:
        engine.dispose()
    os.execvp(
        "proof-agent",
        [
            "proof-agent",
            "run-executor",
            "--slot",
            os.environ.get("PROOF_AGENT_EXECUTOR_SLOT", "1"),
            "--concurrency",
            os.environ.get("PROOF_AGENT_EXECUTOR_CONCURRENCY", "5"),
        ],
    )


if __name__ == "__main__":
    main()
