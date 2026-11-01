# Personal Expert AI

Локальная AI-платформа для работы с проектной документацией: загрузка и структурирование файлов, поиск с доказательными ссылками на источники, диалог по содержимому проекта и инженерные проверки.

> **Статус:** архитектурное исследование и базовый комплект спецификаций подготовлены 2026-11-01. Создан начальный слой PostgreSQL/SQLAlchemy/Alembic; runtime-проверки и интеграции ещё не выполнены.

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
- [Knowledge Model](docs/architecture/KNOWLEDGE_MODEL.md)
- [Memory Engine](docs/architecture/MEMORY_ENGINE.md)
- [Security Model](docs/architecture/SECURITY_MODEL.md)
- [LLM Provider Architecture](docs/architecture/LLM_PROVIDER_ARCHITECTURE.md)
- [PostgreSQL Database Schema](docs/architecture/DATABASE_SCHEMA.md)
- [ERD](docs/architecture/erd.mmd)

## Database foundation

The initial relational layer includes SQLAlchemy 2.x models, PostgreSQL DDL migration and Alembic configuration. It covers tenant/user membership, workspaces/projects, document versions, processing runs and artifacts, source fragments, knowledge assertions, conversations/messages, memory entries and audit events.

Install and run locally:

    pip install -e ".[database,dev]"
    docker compose up -d postgres
    alembic upgrade head
    pytest

Set DATABASE_URL to the local PostgreSQL connection string before running Alembic. Do not use the placeholder password in docker-compose for any exposed or shared environment. These commands are documented setup instructions; they have not yet been executed in the current development environment.

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
