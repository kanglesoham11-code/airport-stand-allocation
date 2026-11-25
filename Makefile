install:
	pip install -r requirements.txt -r requirements-dev.txt

data:
	python -m stand_allocation.generate_data

run:
	uvicorn stand_allocation.api:app --host 127.0.0.1 --timeout-keep-alive 5 --limit-concurrency 100

test:
	python -m pytest -q

check:
	ruff check .
	mypy stand_allocation
	python -m pytest -q
