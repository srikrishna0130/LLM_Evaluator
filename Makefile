.PHONY: run worker test docker

run:
	uvicorn app.main:app --reload --port 8000

worker:
	python -m app.worker

test:
	pytest -q

docker:
	docker compose up --build
