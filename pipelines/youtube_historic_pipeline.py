import logging
import time
import os
import sys
from datetime import datetime

from pipelines.bronze.youtube_historic_source_to_bronze import run as source_to_bronze
from pipelines.silver.youtube_historic_bronze_to_silver import run as bronze_to_silver
from pipelines.gold.youtube_historic_silver_to_gold import run as silver_to_gold
from pipelines.gold.optimize_gold import run as optimize_gold


script_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]

LOG_FILE = f"logs/{script_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


PIPELINE = [
    #("WordPress historic source → bronze", source_to_bronze),
    ("WordPress historic bronze → silver", bronze_to_silver),
    ("WordPress historic silver → gold", silver_to_gold),
    ("Optimize gold tables", optimize_gold),
]


def setup_logger():

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler()
        ]
    )


def run_step(name, func):

    logging.info(f"Starting step: {name}")

    start = time.time()

    func()

    elapsed = time.time() - start

    logging.info(f"Finished step: {name} ({elapsed:.2f}s)")


def run_pipeline():

    logging.info("Pipeline started")

    for name, func in PIPELINE:
        run_step(name, func)

    logging.info("Pipeline finished successfully")


if __name__ == "__main__":

    setup_logger()

    start_total = time.time()

    try:
        run_pipeline()
    except Exception:
        logging.exception("Pipeline failed")
        raise

    total_time = time.time() - start_total

    logging.info(f"Total pipeline time: {total_time:.2f}s")
