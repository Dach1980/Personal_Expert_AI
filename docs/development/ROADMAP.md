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

Архитектурные решения зафиксированы в [TARGET_ARCHITECTURE.md](../architecture/TARGET_ARCHITECTURE.md). Прототипы должны подтвердить совместимость компонентов и не переносить бизнес-логику в AnythingLLM или сторонний агент.

- [ ] P0 — LM Studio provider: chat, vision, embeddings, reranker, tool calling, streaming, auth, concurrency и загрузка/переключение моделей. Сначала контракт, adapter и mock-тесты; затем runtime smoke tests на локальной машине.
- [ ] P1 — AnythingLLM Docker как сменный UI: подключение к backend/LM Studio, workspace-to-project mapping, ACL, API, citations, deletion, container privileges и сетевой трафик.
- [ ] P2 — OCR Benchmark: Tesseract vs PaddleOCR vs EasyOCR на едином воспроизводимом наборе с Ground Truth; CER/WER, координаты, latency и RAM.
- [ ] P3 — ingestion benchmark на одном обезличенном комплекте документов: качество извлечения, полнота, provenance и устойчивость повторной обработки.
- [ ] P4 — Memory/Skills prototype: User/Project/Professional/Session scopes, FTS, semantic recall, approval, provenance, versioning и deletion.
- [ ] P5 — end-to-end интеграция одного проверочного кейса ВК с regression benchmark.
- [ ] P6 — multi-user isolation для документов, индексов, памяти, истории, логов, кэшей и артефактов.

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

## Фаза 3. Обработка документации — в работе

- [x] Durable ProcessingRun queue: идемпотентная постановка только завершённых DocumentVersion в очередь.
- [x] Версионирование pipeline/parser manifest в ProcessingRun.
- [x] Worker leases, heartbeat, параллельный claim через PostgreSQL SKIP LOCKED и retry policy.
- [x] Регистрация промежуточных ProcessingArtifact с checksum, размером и provenance metadata.
- [x] API постановки и просмотра ProcessingRun с tenant/project access checks.
- [x] Unit и PostgreSQL integration tests для upload gate, idempotency, leases, retries и artifacts.
- [ ] Реестр форматов и валидация загрузок.
- [x] PDF: PyMuPDF native text, страницы, размеры/поворот, текстовые блоки и bbox в PDF points, извлечение встроенных изображений.
- [x] DOCX: абзацы/стили, ячейки таблиц, извлечение встроенных изображений.
- [x] XLSX: листы, значения и формулы, координаты ячеек, объединённые диапазоны и изображения.
- [x] PPTX: слайды, текстовые блоки с геометрией, ячейки таблиц и изображения.
- [x] Локальное сохранение extraction manifest и изображений с SHA-256/size и ProcessingArtifact.
- [x] SourceFragment с locator, content hash, версией парсера и ссылкой на DocumentVersion/ProcessingRun.
- [x] Идемпотентная запись фрагментов при retry и heartbeat worker lease.
- [x] PDF page rendering через PyMuPDF с разрешением, геометрией, SHA-256 и локальным сохранением PNG-артефактов.
- [x] Диагностика отсутствующего/недостаточного native text по количеству символов и плотности.
- [x] Опциональный локальный Tesseract OCR с координатами слов, конвертацией в PDF points и фильтрацией дубликатов.
- [x] OCR-инспекция встроенных растровых изображений с сохранением исходного locator.
- [x] Единая structured page model, объединяющая native text, OCR, геометрию и render provenance.
- [ ] Семантическое понимание схем и чертежей через локальную vision-language model после benchmark.
- [ ] PDF vector drawings / paths and CAD-aware geometry.
- [ ] Полная нормализация сложных таблиц, вложенных структур и координат.
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

## Ближайшая последовательность работ

Порядок ниже учитывает уже реализованный backend и Document Processing Pipeline. Это рабочая последовательность, а не требование закончить всю обработку документов до начала интеграции моделей.

1. **Закрепить архитектуру и границы компонентов.** Целевая схема описана в [TARGET_ARCHITECTURE.md](../architecture/TARGET_ARCHITECTURE.md). Сохранять AnythingLLM как сменный UI, Python как управляющий слой, Project Expert Engine как инженерное ядро, LM Studio за provider abstraction.
2. **Довести текущий OCR до измеримого качества.** Создать синтетический и публично допустимый тестовый набор с Ground Truth; проверить Tesseract, координаты, повороты, разные DPI, качество распознавания и ресурсы; исправить геометрическую дедупликацию. Не загружать конфиденциальные проектные документы в публичный CI.
3. **Сделать сменные OCR adapters и сравнить движки.** Tesseract остаётся текущей реализацией; PaddleOCR и EasyOCR подключаются сначала только к benchmark harness. Выбор production движка — отдельное ADR после результатов.
4. **Параллельно подготовить LM Studio provider.** Реализовать единый контракт провайдера и mock-тесты без запущенного LM Studio. Затем проверить chat, streaming, tool calling, embeddings, vision, reranker, concurrency и загрузку моделей на целевой локальной машине. Не заявлять runtime-совместимость до реального smoke test.
5. **Проверить AnythingLLM как UI, а не как backend.** Исследовать API, авторизацию, связь workspace с project, citations, ACL, удаление, контейнерные права и сетевые обращения. Не передавать ему владение документами, памятью и инженерными workflow.
6. **Завершить Document/Page Model.** Добавить vector drawing extraction, нормализацию таблиц, формулы, image/Vision enrichment и quality/completeness scoring. Каждый элемент сохраняет locator, координаты и provenance.
7. **Построить Knowledge Engine.** Сначала типизированные сущности, утверждения, связи, provenance и hybrid retrieval; затем сравнить pgvector/Qdrant и варианты графового хранения. PostgreSQL остаётся источником истины.
8. **Реализовать Memory Engine и Skills.** Разделить User Memory, Project Memory и Professional Memory; добавить scopes, подтверждение фактов, актуальность, происхождение, версионирование Skills, журнал исполнений и удаление.
9. **Развить Python AI Orchestrator и Tool Gateway.** Управление workflow, контекстом, маршрутизацией моделей, памятью, Skills и MCP-инструментами; централизованные ACL, allowlist, подтверждения и аудит.
10. **Интегрировать Project Expert Engine.** Переносить проверенные модули Project Expert AI поэтапно, не переписывая рабочие алгоритмы; начать с одного сквозного кейса ВК.
11. **Собрать end-to-end MVP.** Пользователь через AnythingLLM задаёт вопрос по проекту; Orchestrator получает контекст из Memory/Knowledge Engine, вызывает локальную модель и/или Expert Engine и возвращает ответ с точными доказательными ссылками.
12. **Подготовить multi-user и эксплуатацию.** Проверить изоляцию всех данных и производных индексов, роли, лимиты, backup/restore, аудит, мониторинг и local-only network policy.

**Что можно делать без LM Studio:** пункты OCR Benchmark, дедупликация, extraction adapters, геометрия, таблицы/формулы/vector extraction, модель страницы, storage/provenance, Knowledge/Memory schema и API-контракты; provider adapter можно разработать и покрыть mock-тестами. Реальное качество inference, совместимость выбранных моделей, VRAM/RAM, скорость и concurrency требуют запуска LM Studio на целевой машине.

## Правило принятия решений

Не фиксировать технологию только по популярности или маркетинговым заявлениям. Для существенного выбора создать ADR с альтернативами, benchmark, рисками и критериями пересмотра. Пункт roadmap считается выполненным только после реализации и проверок, а не после написания документации.
