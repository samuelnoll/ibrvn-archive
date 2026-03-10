.PHONY: install pipeline api clean dev

install:
	pip install -r requirements.txt

pipeline:
	python -m pipelines.wordpress_historic_pipeline

api:
	uvicorn api.main:app --host 0.0.0.0 --port 8000

clean:
	rm -rf __pycache__

dev:
	source venv/bin/activate

export:
	python scripts/export_tables_to_csv.py

quality:
	python scripts/sermon_data_quality.py
