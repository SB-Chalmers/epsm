# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""One application-owned listener writes logs from spawned worker processes."""

import logging
import multiprocessing
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path

from epsm import configure_logging, reset_logging


def worker(queue, context):
    """Explicitly receive context and send records only to the parent's queue."""
    logger = logging.getLogger("epsm")
    logger.handlers = [QueueHandler(queue)]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.info(
        "Worker completed",
        extra={
            "epsm_event": "example.worker.completed",
            "epsm_context": context,
            "epsm_details": {"case_count": 1},
        },
    )


def run(directory):
    """Use spawn, join producers, drain the listener, then close output files."""
    configure_logging(directory=directory, console_level="OFF")
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    listener = QueueListener(
        queue, *logging.getLogger("epsm").handlers, respect_handler_level=True
    )
    listener.start()
    try:
        process = context.Process(
            target=worker, args=(queue, {"study_id": "queue-example"})
        )
        process.start()
        process.join(timeout=60)
        if process.is_alive():
            process.terminate()
            process.join()
            raise RuntimeError("Logging example worker timed out")
        if process.exitcode:
            raise RuntimeError(f"Logging example worker failed: {process.exitcode}")
    finally:
        listener.stop()
        queue.close()
        queue.join_thread()
        reset_logging()
    return Path(directory) / "logs/study.jsonl"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    print(run(parser.parse_args().directory))
