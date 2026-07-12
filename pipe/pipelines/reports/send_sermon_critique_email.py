from __future__ import annotations

import argparse

from pipe.pipelines.reports.sermon_critique import run_generate, run_send_email


def run(preaching_date: str = ""):

    run_generate(preaching_date=preaching_date)
    run_send_email(preaching_date=preaching_date)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--preaching-date", default="")
    args = parser.parse_args()

    run(preaching_date=(args.preaching_date or "").strip())
