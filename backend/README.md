# Ticketing backend MVP — phase 1

This directory contains the C++20 + Drogon + PostgreSQL foundation for the
ticketing MVP. Phase 1 intentionally exposes only `GET /health`; ticketing
controllers and workflows belong to later phases.

## Layout

```text
backend/
├── CMakeLists.txt
├── Dockerfile
├── docker-compose.yml
├── config/
│   ├── config.json
│   └── config.docker.json
├── db/
│   ├── migrations/001_initial_schema.sql
│   ├── seeds/001_demo_seed.sql
│   └── tests/001_verify_seed.sql
├── src/
│   ├── controllers/
│   │   ├── HealthController.cpp
│   │   └── HealthController.h
│   └── main.cpp
└── tests/schema_contract_test.py
```

Future business code should be added only when its phase starts. Controllers,
services, and repositories should be introduced as real behavior requires them,
instead of adding empty abstractions now.

## Run with Docker Compose

From `backend/`:

```bash
docker compose up --build
curl http://localhost:8080/health
```

Expected health response:

```json
{"database":"up","status":"ok"}
```

PostgreSQL listens on `localhost:5432` with local-only development credentials:

```text
database: ticketing
user:     ticketing
password: ticketing_dev
```

On the first creation of the named volume, PostgreSQL runs the migration, Seed,
and database verification SQL in order. To deliberately rebuild the local
database from scratch, remove the Compose volume and start again:

```bash
docker compose down --volumes
docker compose up --build
```

The first command deletes the local development database volume.

## Native build

Prerequisites are CMake 3.20+, a C++20 compiler, Drogon 1.9+ built with
PostgreSQL ORM support, libpq, and Python 3 for the schema contract test.

With an installed Drogon package:

```bash
cmake -S . -B build -DBUILD_TESTING=ON
cmake --build build --parallel
ctest --test-dir build --output-on-failure
./build/ticketing_backend config/config.json
```

Alternatively, CMake can fetch the pinned Drogon v1.9.13 source:

```bash
cmake -S . -B build -DBUILD_TESTING=ON -DTICKETING_FETCH_DROGON=ON
cmake --build build --parallel
```

The native configuration connects to PostgreSQL at `127.0.0.1:5432`. Apply the
database files in this order when PostgreSQL is not managed by Compose:

```bash
psql -v ON_ERROR_STOP=1 -U ticketing -d ticketing -f db/migrations/001_initial_schema.sql
psql -v ON_ERROR_STOP=1 -U ticketing -d ticketing -f db/seeds/001_demo_seed.sql
psql -v ON_ERROR_STOP=1 -U ticketing -d ticketing -f db/tests/001_verify_seed.sql
```

The checked-in password is for local development only and must not be reused in
any deployed environment.
