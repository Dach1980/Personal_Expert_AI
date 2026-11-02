# PostgreSQL Database Schema

- Версия: 0.1.0
- СУБД: PostgreSQL 16+
- ORM: SQLAlchemy 2.x
- Миграции: Alembic

## Назначение и соглашения

PostgreSQL — источник истины для метаданных, связей, статусов и истории. Бинарные оригиналы и большие производные файлы находятся в файловом/object storage; БД хранит непрозрачные storage_key, checksum, тип и размер.

- PK доменных сущностей — UUID, генерируемый приложением.
- Время — timestamptz в UTC; календарные даты применимости — DATE.
- Статусы и роли — VARCHAR с CHECK constraints, чтобы менять справочники без сложной миграции PostgreSQL ENUM.
- Гибкие метаданные — JSONB; поля фильтрации и связей остаются типизированными колонками.
- Все tenant-scoped таблицы содержат tenant_id; проектные — также project_id.
- Оригиналы DocumentVersion неизменяемы: новая редакция создаёт новую строку.
- Индексы retrieval — производные данные, не источник истины.
- Имена файлов пользователей никогда не становятся путями хранения.

## Таблицы начального ядра

| Таблица | Назначение | Ключевые ограничения |
|---|---|---|
| tenants, users | Граница установки и учётные записи | login UNIQUE |
| memberships | Членство в tenant | UNIQUE tenant/user; CHECK role |
| workspaces, projects | Организация проектов | FK tenant/workspace |
| project_memberships | Доступ к проекту | UNIQUE project/user; CHECK role |
| documents, document_versions | Логический документ и неизменяемые выпуски | SHA-256 CHECK, unique storage_key, size > 0, immutable source trigger |
| processing_runs | Запуски обработки | CHECK status; manifest |
| processing_artifacts | Производные файлы | storage_key UNIQUE |
| source_fragments | Локализованные участки | locator, content_hash, extractor metadata |
| knowledge_items | Канонические сущности знаний | kind/status |
| knowledge_assertions | Утверждения с provenance | FK item/fragment; confidence 0..1 |
| conversations, messages | История диалога | role CHECK; chronological index |
| memory_entries | Память с отдельной областью | scope/status CHECK |
| audit_events | Append-only аудит | actor/action/target/timestamp |
| upload_operations | Durable multipart upload journal | tenant/project/idempotency UNIQUE; state CHECK; tenant RLS |

ERD: [erd.mmd](erd.mmd).

## Основные поля

- projects: tenant_id, workspace_id, code, name, description, status, metadata.
- document_versions: tenant_id, project_id, document_id, version_label, original_filename, media_type, size_bytes, checksum_sha256, storage_key, status, uploaded_by, uploaded_at, metadata.
- upload_operations: tenant_id, project_id, document_id, idempotency_key, created_by, status, original_filename, media_type, size_bytes, checksum_sha256, quarantine_key, storage_key, document_version_id, error_code/message, completed_at.
- processing_runs: document_version_id, pipeline_name/version, status, manifest, started_at, finished_at, error_code/message.
- source_fragments: document_version_id, processing_run_id, fragment_type, locator JSONB, content, content_hash, extraction_method/version, quality JSONB.
- knowledge_assertions: knowledge_item_id, source_fragment_id, subject, predicate, value JSONB, unit, extractor/version, confidence, review_status, valid_from/to, reviewed_by/at.
- memory_entries: scope_type/scope_id, owner_user_id, project_id, kind, content, status, provenance, validity and confirmation fields.

## Индексы

Индексы первой миграции покрывают tenant/status для проектов; project/checksum и document/uploaded_at для версий; version/created_at и project/status для processing runs; version/run для source fragments; project/kind/status для knowledge items; item и fragment для assertions; project/owner/updated_at для conversations; conversation/created_at для messages; tenant/scope/status для memory; tenant/created_at и target для audit.

JSONB GIN и PostgreSQL FTS добавляются после проверки реальных query patterns. pgvector сравнивается с Qdrant на benchmark corpus. Отдельная graph DB пока не вводится.

## Целостность и безопасность

Composite foreign keys защищают tenant/project parent consistency; PostgreSQL RLS применяется к tenant-owned tables, включая upload_operations, через transaction-local tenant context. Сервисный слой дополнительно проверяет активное членство и project role при каждом запросе. UUID не является доказательством доступа. DocumentVersion source identity защищена CHECK constraints и PostgreSQL trigger; UploadOperation хранит durable state machine для согласования файловой системы и БД.

Не использовать широкие ON DELETE CASCADE для проектных данных. Сначала soft-delete/retention workflow, затем контролируемая очистка. Audit trail не удаляется обычным удалением проекта.

## Миграции после начального ядра

- `0003_document_integrity` — immutable source identity, SHA-256/size/name/MIME/storage key constraints и trigger.
- `0004_upload_operations` — журнал multipart upload, idempotency, composite FK и tenant RLS.

## Не входит в первую миграцию

Skill registry, review runs/findings/evidence, graph relations и нормативный каталог остаются следующими доменными миграциями. Authentication/session storage требует отдельного security design. Vector storage и embeddings выбираются после benchmark.

## Критерии приёмки

1. Alembic upgrade/downgrade проходит на чистой PostgreSQL 16.
2. SQLAlchemy metadata соответствует миграции.
3. FK, CHECK, UNIQUE и индексы покрыты тестами.
4. Сервисные тесты подтверждают tenant/project isolation.
5. PostgreSQL не содержит бинарные оригиналы документов.