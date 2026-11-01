# Архитектурный обзор

## Назначение

Personal Expert AI — локально развёртываемая платформа, которая превращает загруженный комплект проектной документации в структурированную, версионируемую и доступную для вопросов базу знаний. На её основе работают документный помощник и специализированные инструменты инженерной проверки.

## Логические контуры

1. **Presentation** — на первом этапе исследуется AnythingLLM Docker. UI не содержит доменную и экспертную бизнес-логику.
2. **API и оркестрация** — собственный Python/FastAPI backend управляет пользователями, проектами, документами, заданиями, моделями и инструментами.
3. **LLM runtime** — LM Studio как первый локальный runtime за provider abstraction.
4. **Document Engine** — извлечение текста, структуры, таблиц, формул, изображений и геометрии чертежей с provenance.
5. **Knowledge Engine** — гибридный поиск, типизированные утверждения, связи и конфликты.
6. **Memory Engine** — отдельные области памяти пользователя, tenant, проекта, сессии и задачи.
7. **Skills/Tool Gateway** — контролируемое выполнение процедур и инструментов с allowlist и аудитом.
8. **Expert Review** — развитие проверенных механизмов Project Expert AI: нормативные проверки, межраздельная согласованность, доказательства и классификация замечаний.
9. **Persistence & Security** — PostgreSQL как источник истины для метаданных, файловое хранилище для оригиналов и артефактов, проверка доступа на каждом уровне.

## Комплект архитектурных документов

| Документ | Назначение |
|---|---|
| [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md) | Цели продукта, роли, пользовательские сценарии и критерии MVP |
| [DOMAIN_MODEL.md](DOMAIN_MODEL.md) | Доменные сущности, связи, владение, версии и статусы |
| [BACKEND_API.md](BACKEND_API.md) | Контракты UI/backend, маршруты, ошибки, streaming и авторизация |
| [DOCUMENT_LIFECYCLE.md](DOCUMENT_LIFECYCLE.md) | Загрузка, извлечение, контроль качества, индексация и удаление |
| [KNOWLEDGE_MODEL.md](KNOWLEDGE_MODEL.md) | Структура знаний, provenance, конфликты и retrieval |
| [MEMORY_ENGINE.md](MEMORY_ENGINE.md) | Области памяти, жизненный цикл записей, Skills и инструменты |
| [SECURITY_MODEL.md](SECURITY_MODEL.md) | Модель угроз, tenant isolation, local-only и аудит |
| [LLM_PROVIDER_ARCHITECTURE.md](LLM_PROVIDER_ARCHITECTURE.md) | Provider adapters, capabilities, manifests и LM Studio |
| [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) | Физическая схема PostgreSQL, ограничения и индексы |
| [erd.mmd](erd.mmd) | ERD начального реляционного ядра |

## Реализация слоя данных

Начальная реализация находится в app/storage: SQLAlchemy 2.x models, engine/session helpers и Alembic migrations. Она охватывает tenants/users/memberships, workspaces/projects, документы и версии, processing runs/artifacts, source fragments, knowledge items/assertions, conversations/messages, memory и audit events.

Это первый слой схемы, а не полная реализация всех доменных сущностей. Skills, инженерные проверки, нормативный каталог и graph relations добавляются следующими миграциями. До эксплуатации необходимо проверить миграции на чистой PostgreSQL, добавить tenant-consistency composite foreign keys и пройти тесты изоляции.

## Ключевые доменные сущности

Tenant, User, Membership, Workspace, Project, ProjectMembership, Document, DocumentVersion, ProcessingRun, ProcessingArtifact, SourceFragment, KnowledgeItem, KnowledgeAssertion, Relation, Conversation, Message, MemoryEntry, Skill/SkillVersion, SkillExecution, ReviewRun, Finding, EvidenceLink и AuditEvent.

## Обязательные архитектурные свойства

- Все сущности имеют проверяемую область доступа.
- Каждый инженерно значимый вывод хранит происхождение и доказательства.
- Результаты обработки воспроизводимы: фиксируются версии моделей, промптов, парсеров, Skills и нормативных источников.
- Новая редакция документа не перезаписывает старую.
- Память не является источником инженерной истины.
- Содержимое загруженных документов считается недоверенными данными, а не инструкциями для агента.
- Вызовы инструментов ограничиваются allowlist, правами проекта и аудитом.
- Local-only подтверждается сетевыми тестами.

## Поток обработки документа

1. Приём файла, проверка безопасности и регистрация DocumentVersion.
2. Сохранение неизменяемого оригинала и checksum.
3. Извлечение страниц, текста, изображений, таблиц и структуры.
4. Нормализация и создание SourceFragments с координатами.
5. Построение структурированного паспорта документа.
6. Контроль качества и фиксация неопределённости.
7. Индексация и публикация версии в контексте проекта.
8. Ответы и проверки с обязательным возвратом к источникам.

## Что пока не фиксируем

До прототипирования не выбираем окончательно: vector store, graph store, конкретные embeddings/reranker/vision модели, framework агентов и глубину интеграции AnythingLLM. Эти решения оформляются ADR после benchmark.
