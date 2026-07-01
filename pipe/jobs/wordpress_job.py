import logging
import os
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pipe.pipelines.gold.optimize_gold import run as optimize_gold
from pipe.pipelines.gold.silver_to_gold_refresh import run as silver_to_gold
from pipe.pipelines.silver.wordpress_historic_bronze_to_silver import run as bronze_to_silver


script_name = os.path.splitext(os.path.basename(__file__))[0]


def setup_logger():

    log_dir = os.path.join(PROJECT_ROOT, "logs", "jobs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(
        log_dir,
        f"{script_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )


def run_step(name, func):

    logging.info(f"Starting step: {name}")

    start = time.time()
    func()
    elapsed = time.time() - start

    logging.info(f"Finished step: {name} ({elapsed:.2f}s)")


def run_job():

    logging.info("WordPress job started")

    pipeline = [
        ("WordPress historic bronze to silver", bronze_to_silver),
        ("WordPress historic silver to gold", silver_to_gold),
        ("Optimize gold tables", optimize_gold),
    ]

    for name, func in pipeline:
        run_step(name, func)

    logging.info("Job finished successfully")


if __name__ == "__main__":

    setup_logger()

    start_total = time.time()

    try:
        run_job()
    except Exception:
        logging.exception("Job failed")
        raise

    total_time = time.time() - start_total

    logging.info(f"Total job time: {total_time:.2f}s")
