# Backend API Skeleton

A production-ready FastAPI boilerplate designed specifically for a 3-hour technical build interview at Generic for a Senior Software Engineer (IC3) role.

## Features Included out of the Box
- **Configuration Management**: 12-factor app compliance using `pydantic-settings`. Zero hardcoded secrets.
- **Structured Logging**: JSON logging for production, readable logs for development.
- **Graceful Shutdown**: Hooks included to cleanly close DB connections and finish in-flight requests.
- **Separation of Concerns**: Pre-configured directory structure (`api`, `core`, `services`).
- **Developer Experience**: Includes `Makefile`, `Dockerfile`, and `docker-compose.yml`.

## Quickstart

### Local Development
```bash
# 1. Setup virtual environment
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup environment variables
cp .env.example .env

# 4. Run the server
make run
```

### Docker
```bash
make docker-build
make docker-run
```

## Running Tests
```bash
make test
```

## Trade-offs & Future Improvements
*(Note to self: Fill this section out during the last 15 minutes of the interview!)*
- **Data Storage**: Used `[Insert DB]` for speed of implementation during the 3-hour window. In production, I would use Managed PostgreSQL.
- **Message Queue**: Used background tasks / in-memory queues for async processing. In production, I would use Redis/RabbitMQ to prevent job loss on pod restarts.
- **CI/CD**: Skipped full automated pipeline due to time constraints, deployed via CLI instead.
