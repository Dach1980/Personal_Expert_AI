# Local development environment — 2026-11-07

## Scope and evidence

This record captures the first successful preparation of the Personal Expert AI local workstation. It records only verified setup results from the user's Windows 11 / WSL2 machine. It is not a runtime acceptance of the PEA API, Keycloak, Bionic Agent Runtime, document processing or chat.

## Repositories

- Backend: [Dach1980/Personal_Expert_AI](https://github.com/Dach1980/Personal_Expert_AI)
- Local clone: `D:\Projects\Personal_Expert_AI`
- WSL path: `/mnt/d/Projects/Personal_Expert_AI`
- Branch at clone: `main`
- HEAD at clone: `78f8cc1` — `docs(acceptance): record successful web deployment verification`
- Git working tree at clone: clean; local branch was up to date with `origin/main`.

The Web frontend remains a separate repository: [Dach1980/Personal_Expert_AI_Web](https://github.com/Dach1980/Personal_Expert_AI_Web).

## Host and Linux environment

- Host: Windows 11.
- WSL distribution: Ubuntu 26.04.1 LTS.
- Kernel: `6.18.54.1-microsoft-standard-WSL2`, x86_64.
- Linux user: `dchpo`.
- Git: `2.53.0`.
- System Python: `3.14.4`.
- pip: `25.1.1` (system Python 3.14).
- uv: `0.13.7`, installed in `~/.local/bin`; shell activation: `source "$HOME/.local/bin/env"`.

Python 3.11 and 3.12 were not found in PATH or the currently configured Ubuntu apt package indexes. The project declares Python `>=3.11`, while Ruff and mypy are configured for Python 3.11. Next setup step is to use uv to install a project-local Python 3.12 runtime and create `.venv`; do not replace Ubuntu's system Python.

## Docker and PostgreSQL

- Docker Desktop: `4.98.0`.
- Docker Engine: `29.9.2`.
- Docker Compose: `v5.6.1`.
- Docker Desktop WSL2 integration is enabled for Ubuntu.
- Docker CLI works from Ubuntu without sudo.
- User `dchpo` belongs to the `docker` group. Membership in this group grants root-equivalent control over the Docker host.
- `docker run --rm hello-world` completed successfully.
- `docker compose config --quiet` passed.
- Compose service `postgres` uses PostgreSQL 16.
- Container: `personal-expert-postgres`.
- Database: `personal_expert`; role: `personal_expert`.
- Container status at the end of this session: `Up (healthy)`.
- `pg_isready -U personal_expert -d personal_expert` returned `accepting connections`.
- Host port binding: `127.0.0.1:5432`.
- Persistent Docker volume: `personal_expert_ai_postgres_data`.

The PostgreSQL container was started, but Alembic migrations have not yet been applied and the PEA API has not yet been started. Preserve the named volume; do not use `docker compose down -v`.

## Local LLM endpoint

- LM Studio is running on Windows with its OpenAI-compatible API on port `1234`.
- The API endpoint was reachable from PowerShell at `http://127.0.0.1:1234/v1`.
- LM Studio's **Serve on Local Network** option was enabled.
- Ubuntu WSL successfully reached the Windows host endpoint at `http://172.30.128.1:1234/v1/models` and received HTTP 200.
- Chat completions were tested successfully in Russian and English.
- A model used in the test was `qwen/qwen3.5-9b`; the LM Studio model list also included other Qwen models and `text-embedding-nomic-embed-text-v1.5`.

The WSL host address is environment-specific and must be rechecked if the network changes. Docker-container-to-host connectivity has not yet been tested. Do not assume that `172.30.128.1` is the correct address from inside a container.

## Local configuration and secret handling

- A local `.env` was created from `.env.example`.
- A random PostgreSQL password was generated locally and used consistently in `POSTGRES_PASSWORD` and `DATABASE_URL`.
- The local LM Studio base URL was set to the WSL-reachable Windows host address.
- File permissions were restricted with `chmod 600 .env`.
- `git check-ignore .env` confirmed that `.env` is ignored by Git.
- No password, API credential, document, model output or private runtime data is recorded in this document or committed to the repository.

## Verified / not yet verified

| Item | Result |
|---|---|
| Repository clone and clean main branch | Verified |
| Docker Desktop ↔ WSL2 integration | Verified |
| Docker image pull and hello-world | Verified |
| Compose configuration validation | Verified |
| PostgreSQL 16 container health | Verified |
| PostgreSQL accepts connections | Verified |
| uv installation | Verified |
| LM Studio Windows API | Verified |
| Ubuntu WSL → LM Studio API | Verified |
| Python 3.12 project runtime and virtual environment | Pending |
| PEA dependencies installation | Pending |
| Alembic upgrade and schema checks on local PostgreSQL | Pending |
| PEA API startup and health endpoint | Pending |
| LM Studio connection from PEA process | Pending |
| Document upload, worker and extraction | Pending |
| Keycloak / Bionic deployment and OIDC | Pending |
| Interactive Bionic `pea_search`, grounded chat and citations | Pending |
| Full browser-to-model runtime E2E and isolation acceptance | Pending |

## Resume instructions

Continue from the backend repository in Ubuntu:

```bash
cd /mnt/d/Projects/Personal_Expert_AI
source "$HOME/.local/bin/env"
uv --version
docker compose ps
```

Then install Python 3.12 with uv, create `.venv`, install the project's database/processing/LLM/dev extras, and only then run migrations and tests. Follow the staged plan in the Web Admin Roadmap. Never commit `.env` or local document data.
