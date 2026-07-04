.PHONY: run test build format lint docker-build docker-run

run:
	fastapi dev app/main.py --port 8000

test:
	pytest -v

format:
	black app/
	isort app/

lint:
	flake8 app/
	mypy app/

docker-build:
	docker build -t do-interview-api .

docker-run:
	docker run -p 8000:8000 --env-file .env do-interview-api