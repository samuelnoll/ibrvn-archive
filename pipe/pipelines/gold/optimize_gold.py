import os
import sys

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.db import get_backend_name, initialize_database


def run():

    initialize_database()

    print(f"Gold database optimized for {get_backend_name()}")


if __name__ == "__main__":
    run()
