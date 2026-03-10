from pipelines.silver.wordpress_to_silver import run as silver
from pipelines.gold.silver_to_gold import run as gold


def run():

    print("Running Bronze → Silver")
    silver()

    print("Running Silver → Gold")
    gold()

    print("Pipeline finished")


if __name__ == "__main__":
    run()

