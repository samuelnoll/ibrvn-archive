import logging
import time
import os
import sys
import argparse
from datetime import datetime

from pipelines.bronze.youtube_source_to_bronze import run as source_to_bronze
from pipelines.silver.youtube_bronze_to_silver import run as bronze_to_silver
from pipelines.gold.youtube_silver_to_gold import run as silver_to_gold
from pipelines.gold.optimize_gold import run as optimize_gold


script_name = os.path.splitext(os.path.basename(__file__))[0]


def setup_logger(mode):

    os.makedirs("logs/jobs", exist_ok=True)

    log_file = f"logs/jobs/{script_name}_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )


def run_step(name, func, mode=None):

    logging.info(f"Starting step: {name}")

    start = time.time()

    if mode:
        func(mode)
    else:
        func()

    elapsed = time.time() - start

    logging.info(f"Finished step: {name} ({elapsed:.2f}s)")


def run_job(mode):

    logging.info(f"YouTube job started (mode={mode})")

    pipeline = [
        (f"YouTube {mode} source → bronze", source_to_bronze, mode),
        (f"YouTube {mode} bronze → silver", bronze_to_silver, mode),
        (f"YouTube {mode} silver → gold", silver_to_gold, mode),
        ("Optimize gold tables", optimize_gold, None),
    ]

    for name, func, step_mode in pipeline:
        run_step(name, func, step_mode)

    logging.info("Job finished successfully")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=["historic", "weekly"],
        default="historic"
    )

    args = parser.parse_args()

    setup_logger(args.mode)

    start_total = time.time()

    try:
        run_job(args.mode)
    except Exception:
        logging.exception("Job failed")
        raise

    total_time = time.time() - start_total

    logging.info(f"Total job time: {total_time:.2f}s")
