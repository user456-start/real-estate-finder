# real-estate-finder

## Python package management

This project uses `uv` for dependency management with a project-local `.venv`.

## Local development setup

1. Create the environment and sync dependencies from lockfile:

```bash
cd backend
uv sync
```

2. Install the local observability SDK (optional but recommended):

```bash
cd backend
uv pip install -e /root/electronics/sdk
```

3. Start infra services:

```bash
docker compose up -d
```

4. Run migrations and seed data:

```bash
cd backend
uv run alembic upgrade head
uv run python -m app.services.seeder
```

5. Run the API:

```bash
uv run --directory backend uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

## Dependency workflow

Add a package:

```bash
uv add --directory backend <package>
```

Add a dev package:

```bash
uv add --directory backend --dev <package>
```

Remove a package:

```bash
uv remove --directory backend <package>
```

Re-lock dependencies:

```bash
uv lock --directory backend
```

## Docker-friendly requirements export

Export runtime-only requirements from `uv.lock` for Docker builds:

```bash
cd backend
uv export --no-dev --no-emit-project --format requirements-txt --output-file requirements-docker.txt
```

Whenever dependencies change, run both:

```bash
uv lock --directory backend
cd backend
uv export --no-dev --no-emit-project --format requirements-txt --output-file requirements-docker.txt
```
