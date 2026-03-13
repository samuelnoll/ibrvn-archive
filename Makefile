.PHONY: install pipeline api clean dev export quality youtube-weekly youtube-historic wordpress-historic

install:
	pip install -r requirements.txt

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

youtube-weekly:
	python -m jobs.youtube_job --mode weekly

youtube-historic:
	python -m jobs.youtube_job --mode historic

wordpress-historic:
	python -m jobs.wordpress_job
