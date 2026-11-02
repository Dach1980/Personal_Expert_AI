# План разработки Personal Expert AI

## Фаза 0. Архитектурное исследование — выполнено

- [x] Исследовать AnythingLLM, LM Studio, Hermes Agent, Bionic и Project Expert AI.
- [x] Сформировать архитектуру и план прототипов.
- [x] Подготовить сравнительное исследование и ADR 0002.

## Фаза 0.5. Архитектурные спецификации — выполнено

- [x] PRODUCT_REQUIREMENTS.md.
- [x] DOMAIN_MODEL.md.
- [x] BACKEND_API.md.
- [x] DOCUMENT_LIFECYCLE.md.
- [x] KNOWLEDGE_MODEL.md.
- [x] MEMORY_ENGINE.md.
- [x] SECURITY_MODEL.md.
- [x] LLM_PROVIDER_ARCHITECTURE.md.
- [x] Связать спецификации с архитектурным обзором и README.

Результат: согласованная целевая архитектура. Документация сама по себе не означает, что все описанные функции реализованы.

## Фаза 0.6. Реляционное ядро и tenant isolation — выполнено

- [x] ERD и физическая спецификация PostgreSQL.
- [x] SQLAlchemy 2.x модели базовых доменных сущностей.
- [x] Alembic migrations.
- [x] Composite foreign keys для tenant/project consistency.
- [x] PostgreSQL RLS и transaction-local tenant context.
- [x] Repository/Service Layer для Tenant, Project и Document.
- [x] JWT principal validation и защищённые базовые API routes.
- [x] PostgreSQL 16 CI: upgrade, alembic check, integration tests, downgrade/re-upgrade, full pytest и Ruff.

Результат подтверждён GitHub Actions. Production identity provider, выдача/отзыв токенов и эксплуатационная конфигурация runtime DB role остаются отдельными задачами.

## Фаза 1. Проверочные прототипы — запланировано

- [ ] P0 — LM Studio: chat, vision, embeddings, tool calling, streaming, auth, concurrency, model loading.
- [ ] P1 — AnythingLLM Docker: LM Studio connection, workspace ACL, API, citations, deletion, container privileges, network traffic.
- [ ] P2 — сравнение ingestion на одном обезличенном комплекте документов.
- [ ] P3 — Memory/Skills: user/project/session scopes, FTS, semantic recall, approval, versioning, deletion.
- [ ] P4 — end-to-end интеграция одного проверочного кейса ВК с regression benchmark.
- [ ] P5 — multi-user isolation для документов, индексов, памяти, истории, логов, кэшей и артефактов.

## Фаза 2. Backend и управление документами — в работе

- [x] FastAPI backend и health endpoint.
- [x] PostgreSQL, SQLAlchemy, Alembic.
- [x] Tenant/Project/Document repository и service layer.
- [x] Проверка tenant/project access.
- [x] Локальный файловый storage primitive с потоковым SHA-256, лимитом размера, staging и атомарной публикацией без перезаписи.
- [x] DB constraints для размера, SHA-256, имени, MIME и storage key.
- [x] Durable UploadOperation journal с RLS, idempotency и composite FK (migration 0004).
- [x] DB constraints для idempotency key, checksum, метаданных и terminal state consistency (migration 0005).
- [x] PostgreSQL trigger, запрещающий изменение source identity у зарегистрированной DocumentVersion.
- [x] Unit и PostgreSQL integration tests на checksum, подмену файла и неизменяемость источника.
- [x] Конфигурация локального storage root, owner-only permissions и исключение локальных данных из Git.
- [x] Multipart upload API с JWT, tenant/project/document access checks, request/file size limits.
- [x] Idempotency keys и durable UploadOperation state machine в PostgreSQL под RLS.
- [x] Quarantine и content-based validation PDF/DOCX/XLSX/PPTX.
- [x] Согласование файловой операции с PostgreSQL через durable phases и crash recovery.
- [x] Tenant-scoped reconciliation для interrupted uploads, missing/corrupt originals и orphan objects.
- [x] Authenticated original download с повторной проверкой SHA-256 и размера на открытом file handle.
- [x] Unit и PostgreSQL integration tests для идемпотентности, восстановления после сбоя, ACL, MIME/package validation и download integrity.

Результат: первый законченный upload/download lifecycle реализован. Reconciliation запускается локальной командой по каждому tenant; автоматическое расписание и операторский мониторинг остаются эксплуатационной настройкой. Parsing/indexing ещё не подключены и должны запускаться только после статуса upload operation = completed.

## Фаза 3. Обработка документации — запланировано

- [ ] Реестр форматов и валидация загрузок.
- [ ] PDF: native text/vector extraction, страницы, рендеринг и OCR fallback.
- [ ] DOCX/XLSX/PPTX adapters.
- [ ] Извлечение таблиц и сохранение координат.
- [ ] Формулы и математические выражения.
- [ ] Изображения и чертежи.
- [ ] Структурированное описание документа и паспорт проекта.
- [ ] Проверка качества и полноты извлечения.
- [ ] Индексация и поиск с точными ссылками на источники.
- [ ] Сравнение редакций.

## Фаза 4. Диалог по проекту — запланировано

- [ ] Контекст проекта и выбор релевантных источников.
- [ ] Цитирование файла, страницы, листа и фрагмента.
- [ ] История диалога и streaming.
- [ ] Уточняющие вопросы при недостатке доказательств.
- [ ] Тесты точности ответов и устойчивости к prompt injection.

## Фаза 5. Постоянная память и Skills — запланировано

- [ ] Профиль пользователя и память проекта.
- [ ] Поиск по прошлым сессиям.
- [ ] Skills Registry с immutable versions.
- [ ] Подтверждение важных фактов/решений.
- [ ] Provenance, срок актуальности и удаление записей памяти.
- [ ] Tool Gateway с allowlist и аудитом.

## Фаза 6. Инженерная экспертиза — запланировано

- [ ] Интеграция выбранных модулей Project Expert AI.
- [ ] Проверки внутри раздела.
- [ ] Межраздельная согласованность.
- [ ] Нормативные проверки с редакцией норм на дату проектирования.
- [ ] Замечания с доказательствами и уровнем уверенности.
- [ ] Отчёт и трассировка каждого вывода.

## Фаза 7. Multi-user и эксплуатационная готовность — запланировано

- [ ] Production identity provider и управление сессиями.
- [ ] Проверка изоляции пользователей, проектов, файлов и индексов.
- [ ] Роли и разрешения.
- [ ] Квоты и лимиты ресурсов.
- [ ] Аудит доступа и действий.
- [ ] Резервное копирование и проверенное восстановление.
- [ ] Тестирование модели угроз и local-only network policy.

## Правило принятия решений

Не фиксировать технологию только по популярности или маркетинговым заявлениям. Для существенного выбора создать ADR с альтернативами, benchmark, рисками и критериями пересмотра. Пункт roadmap считается выполненным только после реализации и проверок, а не после написания документации.
