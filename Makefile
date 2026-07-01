.PHONY: install pipeline api clean dev export quality optimize migrate-gold-postgres job-youtube-weekly job-youtube-historic job-wordpress-historic job-historic

install:
	pip install -r requirements.txt

api:
	uvicorn api.main:app --host $${ARCHIVE_API_HOST:-0.0.0.0} --port $${ARCHIVE_API_PORT:-8000}

clean:
	rm -rf __pycache__

dev:
	source venv/bin/activate

export:
	python pipe/scripts/export_tables_to_csv.py

quality:
	python pipe/scripts/sermon_data_quality.py

optimize:
	python -m pipe.pipelines.gold.optimize_gold

migrate-gold-postgres:
	python pipe/scripts/migrate_sqlite_to_postgres.py

job-youtube-weekly:
	python -m pipe.jobs.youtube_job --mode weekly

job-youtube-historic:
	python -m pipe.jobs.youtube_job --mode historic

job-wordpress-historic:
	python -m pipe.jobs.wordpress_job

job-historic:
	python -m pipe.jobs.youtube_job --mode historic
	python -m pipe.jobs.wordpress_job
