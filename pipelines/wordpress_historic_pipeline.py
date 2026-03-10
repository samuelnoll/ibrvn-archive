from pipelines.silver.wordpress_historic_bronze_to_silver import run as silver
from pipelines.gold.wordpress_historic_silver_to_gold.py import run as gold
from pipelines.gold.optimize_gold.py import run as gold_optimize


def run():

    print("Running Bronze → Silver")
    silver()

    print("Running Silver → Gold")
    gold()

    print("Running Gold Optimization")
    gold_optimize()

    print("Pipeline finished")


if __name__ == "__main__":
    run()

