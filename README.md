# Personal Expert AI

Локальная AI-платформа для работы с проектной документацией: загрузка и структурирование файлов, поиск с доказательными ссылками на источники, диалог по содержимому проекта и инженерные проверки.

> **Статус:** базовая PostgreSQL/SQLAlchemy/Alembic-схема, tenant isolation, RLS и первые защищённые API-маршруты реализованы. GitHub Actions проверяет миграции и интеграционные тесты на PostgreSQL 16; актуальный статус см. в [Database Integrity workflow](https://github.com/Dach1980/Personal_Expert_AI/actions/workflows/database-ci.yml).

## Цели

- Локальная обработка данных и использование локальных LLM через LM Studio.
- Преобразование проектной документации в проверяемую структурированную базу знаний.
- Ответы с привязкой к исходному файлу, странице, листу, таблице или фрагменту.
- Постоянная память пользователя, проекта и диалогов.
- Изолированные проекты и подготовка архитектуры к многопользовательскому режиму.
- Отделение пользовательского интерфейса от экспертного ядра.

## Принципы

1. **Local-first:** документы и запросы не отправляются во внешние облачные модели без явного решения владельца.
2. **Evidence-first:** существенные ответы и выводы должны опираться на проверяемые источники.
3. **Модульность:** UI, backend, ingestion, память и LLM-провайдеры независимы.
4. **Изоляция:** данные каждого пользователя и проекта имеют явные границы доступа.
5. **Версионирование:** оригиналы, результаты обработки и выводы сохраняются с версиями.
6. **Human-in-the-loop:** критические инженерные решения и изменения памяти подтверждаются человеком.

## Архитектурные документы

Согласованная целевая архитектура продукта и границы ответственности компонентов: [Target Architecture](docs/architecture/TARGET_ARCHITECTURE.md). План backend/документного ядра: [Roadmap](docs/development/ROADMAP.md). Межрепозиторный план Web + Bionic + PEA: [Implementation Roadmap 2026-11-04](docs/development/IMPLEMENTATION_ROADMAP_2026-11-04.md). Текущий статус retrieval API и оставшихся Agent Runtime задач: [Implementation Status 2026-11-05](docs/development/IMPLEMENTATION_STATUS_2026-11-05.md).

Полный комплект целевых требований и спецификаций находится в [docs/architecture](docs/architecture/OVERVIEW.md):

- [Product Requirements](docs/architecture/PRODUCT_REQUIREMENTS.md)
- [Domain Model](docs/architecture/DOMAIN_MODEL.md)
- [Backend API](docs/architecture/BACKEND_API.md)
- [Document Lifecycle](docs/architecture/DOCUMENT_LIFECYCLE.md)
- [Document Storage Integrity](docs/architecture/DOCUMENT_STORAGE_INTEGRITY.md)
- [Document Upload and Recovery](docs/architecture/DOCUMENT_UPLOAD_AND_RECOVERY.md)
- [Knowledge Model](docs/architecture/KNOWLEDGE_MODEL.md)
- [Memory Engine](docs/architecture/MEMORY_ENGINE.md)
- [Security Model](docs/architecture/SECURITY_MODEL.md)
- [LLM Provider Architecture](docs/architecture/LLM_PROVIDER_ARCHITECTURE.md)
- [OCR Benchmark methodology](docs/research/OCR_BENCHMARK.md)
- [PostgreSQL Database Schema](docs/architecture/DATABASE_SCHEMA.md)
- [ERD](docs/architecture/erd.mmd)

## Database foundation

The relational layer includes SQLAlchemy 2.x models, versioned PostgreSQL migrations and Alembic configuration. Migration `0002_tenant_isolation` adds composite foreign keys for tenant/project parent consistency and enables PostgreSQL RLS. The runtime database role must be a dedicated non-owner role without SUPERUSER or BYPASSRLS; see [PostgreSQL runtime role setup](docs/development/POSTGRES_RUNTIME_ROLE.md).

Install and run locally:

    pip install -e ".[database,dev]"
    docker compose up -d postgres
    set DATABASE_URL=postgresql+psycopg://personal_expert:YOUR_PASSWORD@localhost:5432/personal_expert
    alembic upgrade head
    pytest

### Document upload and local storage

Authenticated multipart upload and checksum-verified download are implemented for PDF, DOCX, XLSX and PPTX. Configure `DOCUMENT_STORAGE_ROOT` (по умолчанию — локальная папка данных текущего пользователя) and `DOCUMENT_MAX_UPLOAD_BYTES` (default 100 MiB). The storage directory is private and ignored by Git. Upload operations are idempotent and recoverable; PostgreSQL migrations `0004_upload_operations` and `0005_upload_operation_integrity` store and constrain their state under tenant RLS.

Run tenant-scoped recovery/integrity checks after an interrupted process or as a scheduled local maintenance task:

    python -m app.storage.reconcile --tenant-id <TENANT_UUID>

The command resumes interrupted uploads, verifies registered originals, removes completed quarantine copies and reports orphan files. See [Document Upload and Recovery](docs/architecture/DOCUMENT_UPLOAD_AND_RECOVERY.md) for API examples and failure semantics.


### Local conversation API

Project conversations and messages are persisted under tenant/project RLS. The chat API streams deltas from the configured LM Studio model; it never falls back to a cloud provider. Install the optional OpenAI-compatible LM Studio SDK extra on the PEA API host:

    pip install -e ".[database,processing,llm]"

Set `LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1`, `LM_STUDIO_API_KEY=lm-studio` and `LM_STUDIO_MODEL` to the exact model identifier shown by LM Studio. The API also accepts `PEA_LLM_MODEL` as an explicit model override. If no model is configured, chat returns HTTP 503. The current conversation prompt does not yet include document retrieval; the UI states this explicitly and does not claim that documents have been checked.

### Public web client

The required user interface is maintained separately at [Personal_Expert_AI_Web](https://github.com/Dach1980/Personal_Expert_AI_Web) and deployed to [GitHub Pages](https://dach1980.github.io/Personal_Expert_AI_Web/). It uses the Bionic PEA Adapter as its only API origin. Configure Keycloak's public `pea-web` client with PKCE S256 by running `scripts/configure_keycloak_realm.py`; set `PEA_WEB_REDIRECT_URIS` and `PEA_WEB_ORIGINS` to exact deployment values first. Each user must still have an explicit PEA external identity and active membership provisioned. The frontend stores access tokens in memory only. See [Keycloak integration](docs/architecture/KEYCLOAK_INTEGRATION.md) and the [web API adapter contract](https://github.com/Dach1980/Personal_Expert_AI_Web/blob/main/docs/API_ADAPTER.md).

### Document extraction pipeline

The first local extraction worker and format adapters are implemented for PDF (PyMuPDF), DOCX (python-docx), XLSX (openpyxl) and PPTX (python-pptx). Install them with:

    pip install -e ".[database,processing]"

The worker verifies the original file checksum before parsing, writes extraction manifests and embedded images to local storage, and persists provenance-linked `SourceFragment` rows. Start one job or continuous polling with:

    personal-expert-ai-worker --tenant-id <TENANT_UUID> --worker-id local-worker-01 --watch

See [Document Extraction Pipeline](docs/architecture/DOCUMENT_EXTRACTION_PIPELINE.md) for adapter coverage, locator formats and current limitations. PDF pages are rendered locally and converted into structured page models. Optional Tesseract OCR is available through the OCR extra plus a separately installed Tesseract executable. OCR preserves word coordinates and avoids replacing native text. Embedded raster images can also be OCR-inspected. Semantic interpretation of engineering drawings by a local vision-language model, PDF vector extraction and full normalization of complex Office layouts remain future work.

The authenticated API accepts Keycloak RS256 access tokens and validates their signatures against the configured JWKS. Configure `OIDC_ISSUER`, `OIDC_AUDIENCE=pea-api` and `OIDC_JWKS_URL`. PEA resolves the verified `(iss, sub)` pair through `external_identities`, then checks the existing PEA user, active tenant membership and project membership. External identities are explicitly provisioned with `scripts/provision_oidc_identity.py`; PEA does not create users or grant tenant/project access from an email address or token claim. See [Keycloak integration](docs/architecture/KEYCLOAK_INTEGRATION.md) and [realm setup](infra/keycloak/README.md).

The CI workflow provisions PostgreSQL 16, applies and reverts migrations, checks ORM/schema parity, runs RLS tests using a restricted non-owner database role, and runs the unit test suite. Do not use the placeholder password in docker-compose for any exposed or shared environment.

## Предварительный технологический контур

- **UI и агентная среда:** отдельный форк Bionic с интерфейсом Personal Expert AI, серверным API Adapter и подключением реальных PEA проектов/документов; исходный код и CI проверены, локальный runtime с Keycloak ещё требует сквозной проверки.
- **LLM runtime:** LM Studio за собственной provider abstraction; облачный fallback запрещён.
- **Backend и доменная логика:** Python, FastAPI; Personal Expert AI владеет tenant/project/document lifecycle и инженерными проверками.
- **Документный и инженерный движок:** собственный Document Processing Pipeline и развитие наработок Project Expert AI.
- **Память:** собственный Memory Engine с идеями Hermes Agent.
- **Хранилище:** PostgreSQL Personal Expert AI как единственный источник истины; Bionic не получает прямой доступ к этой БД.

План форка и журнал испытаний: [Bionic POC](docs/integrations/bionic/POC_EXECUTION.md), [UI fork plan](docs/integrations/bionic/FORK_UI_PLAN.md).

## Безопасность

Не помещайте в репозиторий клиентскую документацию, персональные данные, секреты, ключи, внутренние базы, индексы или результаты проверок с конфиденциальным содержимым. Репозиторий публичный на момент подготовки документации; перед размещением коммерчески чувствительных материалов переведите его в Private.

## Важно

Документы описывают целевую архитектуру и проектные контракты. Они не означают, что все функции уже реализованы или проверены. Технологические решения, зависящие от runtime, производительности и качества, подтверждаются прототипами и тестами.


## Публичный рабочий сайт

Рабочая публичная web-версия Personal Expert AI разрабатывается отдельно в [Dach1980/Personal_Expert_AI_Web](https://github.com/Dach1980/Personal_Expert_AI_Web) и публикуется через [GitHub Pages](https://dach1980.github.io/Personal_Expert_AI_Web/). Это обязательный самостоятельный deliverable проекта. GitHub Pages размещает только статический frontend; FastAPI, Bionic runtime, Keycloak, PostgreSQL, workers, приватное хранилище и LM Studio работают отдельно и доступны только через защищённую backend boundary.

Актуальный сводный статус и этапы: [аудит проекта от 2026-11-04](docs/development/PROJECT_STATUS_AUDIT_2026-11-04.md). Архитектура публичного frontend: [GitHub Pages frontend](docs/integrations/bionic/GITHUB_PAGES_FRONTEND.md).
