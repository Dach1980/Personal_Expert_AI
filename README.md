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

### Document extraction pipeline

The first local extraction worker and format adapters are implemented for PDF (PyMuPDF), DOCX (python-docx), XLSX (openpyxl) and PPTX (python-pptx). Install them with:

    pip install -e ".[database,processing]"

The worker verifies the original file checksum before parsing, writes extraction manifests and embedded images to local storage, and persists provenance-linked `SourceFragment` rows. Start one job or continuous polling with:

    personal-expert-ai-worker --tenant-id <TENANT_UUID> --worker-id local-worker-01 --watch

See [Document Extraction Pipeline](docs/architecture/DOCUMENT_EXTRACTION_PIPELINE.md) for adapter coverage, locator formats and current limitations. OCR, PDF page rendering, complete vector extraction and full normalization of complex Office layouts remain future work.

The authenticated API accepts signed HS256 JWTs issued by a trusted identity provider. Configure `JWT_SECRET` (at least 32 characters), `JWT_ISSUER` and `JWT_AUDIENCE`. Tokens must carry user UUID in `sub` and tenant UUID in `tenant_id`. The application does not issue tokens or manage passwords yet.

The CI workflow provisions PostgreSQL 16, applies and reverts migrations, checks ORM/schema parity, runs RLS tests using a restricted non-owner database role, and runs the unit test suite. Do not use the placeholder password in docker-compose for any exposed or shared environment.

## Предварительный технологический контур

- **UI:** AnythingLLM Docker — кандидат на прототип; собственный frontend остаётся возможным.
- **LLM runtime:** LM Studio за собственной provider abstraction.
- **Backend:** Python, FastAPI.
- **Документный и инженерный движок:** развитие наработок Project Expert AI.
- **Память:** собственный Memory Engine с идеями Hermes Agent.
- **Агентная среда:** Bionic — экспериментальная desktop-среда, не production backend.
- **Хранилище:** PostgreSQL как источник истины; vector/graph технологии выбираются после benchmark.

## Безопасность

Не помещайте в репозиторий клиентскую документацию, персональные данные, секреты, ключи, внутренние базы, индексы или результаты проверок с конфиденциальным содержимым. Репозиторий публичный на момент подготовки документации; перед размещением коммерчески чувствительных материалов переведите его в Private.

## Важно

Документы описывают целевую архитектуру и проектные контракты. Они не означают, что все функции уже реализованы или проверены. Технологические решения, зависящие от runtime, производительности и качества, подтверждаются прототипами и тестами.
