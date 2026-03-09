install:
	pip install -r requirements.txt

pipeline:
	python pipelines/run_pipeline.py

api:
	uvicorn api.main:app --host 0.0.0.0 --port 8000

clean:
	rm -rf __pycache__
