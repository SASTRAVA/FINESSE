"""Rootless, review-only worker for explicitly authorized security scan plans."""
from __future__ import annotations

import asyncio
import logging

from ..db.storage import storage

logger = logging.getLogger("finesse.security.worker")


def process_review_queue() -> int:
    reviewed = 0
    for task in storage.list("scan_tasks", "default", limit=1000):
        if task.get("status") != "AUTHORIZED_DRY_RUN_PLAN":
            continue
        task["status"] = "DRY_RUN_REVIEW_REQUIRED"
        task["executed"] = False
        storage.put("scan_tasks", "default", task["id"], task)
        reviewed += 1
    return reviewed


async def run_forever() -> None:
    while True:
        reviewed = process_review_queue()
        if reviewed:
            logger.info("marked %d scan plan(s) for human review", reviewed)
        await asyncio.sleep(5)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
