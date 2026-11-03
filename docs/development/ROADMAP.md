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

- [x] P0a — provider-neutral contracts и начальный LM Studio OpenAI-compatible adapter: chat, streaming, embeddings, model listing, health check, loopback-only endpoint validation, explicit capability gating и mock-тесты.
- [ ] P0b — LM Studio runtime smoke tests: Native REST vs OpenAI-compatible API, structured output, tool calling, Vision, cancellation, auth, concurrency, model load/unload, VRAM и network capture. Reranker adapter — отдельная задача.
- [ ] P1 — Bionic fork как сменный UI/agent runtime: baseline build, branding/navigation, read-only Personal Expert API adapter, project/document mapping, citations, ACL, streaming, Skills и sandbox security. LM Studio runtime tests остаются отдельным blocked gate до появления локального runtime.
- [x] P2a — общий OCR benchmark runner, Tesseract adapter, CER/WER, опциональные box Precision/Recall/IoU, latency и RSS snapshots; методика и формат Ground Truth описаны в docs/research/OCR_BENCHMARK.md.
- [ ] P2b — подключить PaddleOCR и EasyOCR adapters и сравнить все движки на одном размеченном русскоязычном инженерном наборе; зафиксировать production выбор отдельным ADR.
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
- [x] OCR benchmark runner и синтетический Tesseract smoke test; CER/WER, box metrics, latency и RSS snapshots при наличии psutil.
- [ ] Измерить OCR accuracy на реальном русскоязычном инженерном наборе с Ground Truth; synthetic smoke test не считается таким измерением.
- [x] Исправить базовую OCR-дедупликацию: совпадение токена проверяется по пересечению локальных native/OCR word boxes, а не по наличию слова где-либо на странице.
- [x] Учитывать поворот PDF при переводе OCR pixel boxes в unrotated PDF points; система координат явно записывается в structured page.
- [ ] Проверить качество spatial dedup на размеченных реальных страницах, поворотах, масштабах и сложных шрифтах.
- [ ] Сравнить OCR providers (Tesseract, PaddleOCR, EasyOCR) через изолированные adapters; выбрать production default по результатам benchmark.
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

## Фаза 0.7. Сравнительный аудит и оценка интеграции Bionic — в работе

Цель: определить, какие общеплатформенные компоненты Bionic выгоднее повторно использовать, а какие части Personal Expert AI необходимо сохранить как собственное инженерное ядро. Полная замена допускается только после POC и проверок безопасности, совместимости и качества.

Исходные точки аудита:
- Personal Expert AI: `main`, commit `7858c46eb4545efef7f78e4d3167b61266822484`.
- Bionic: `main`, commit/tree `8a9797c39680ae8421bfaef72f87eb90650e7a09`.
- Метод: статический анализ исходного кода, SQL migrations, запросов и deployment-конфигурации. Runtime, penetration и performance tests не проводились.

Документы:
- [Сводный аудит компонентов](../integrations/bionic/COMPONENTS.md).
- [Архитектура отдельного frontend на GitHub Pages](../integrations/bionic/GITHUB_PAGES_FRONTEND.md).

### Направления и задачи

- [x] BIONIC-AUDIT-01 — сравнить хранилище и жизненный цикл данных.
- [x] BIONIC-AUDIT-02 — сравнить RAG ingestion, chunking, embeddings и retrieval.
- [x] BIONIC-AUDIT-03 — сравнить users, teams, roles, permissions и RLS.
- [x] BIONIC-AUDIT-04 — сравнить обработку запросов, историю, streaming и контекст.
- [x] BIONIC-AUDIT-05 — сравнить agent runtime, tools, Skills, VFS и sandbox.
- [x] BIONIC-AUDIT-06 — сравнить audit, observability и deployment.
- [ ] BIONIC-POC-01 — развернуть Bionic в изолированной тестовой среде; проверить версии, миграции, health, базовые сценарии и восстановление.
- [ ] BIONIC-POC-02 — проверить LM Studio как chat и embedding provider, включая streaming, tool calling, отмену, ошибки и local-only network capture.
- [ ] BIONIC-POC-03 — провести сравнительный RAG benchmark на одном русскоязычном инженерном наборе с измерением retrieval quality и сохранения точных source locators.
- [ ] BIONIC-POC-04 — проверить передачу identity и project/tenant authorization без второго источника истины и без обхода Personal Expert AI access checks.
- [ ] BIONIC-POC-05 — проверить sandbox isolation, filesystem permissions, network egress, prompt injection и межпользовательскую изоляцию.
- [ ] BIONIC-POC-06 — проверить возможность отдельного frontend на GitHub Pages и интеграцию с self-hosted Bionic backend.
- [ ] BIONIC-DECISION-01 — по результатам POC утвердить для каждого компонента REUSE / ADAPT / KEEP / REPLACE отдельным ADR.

Критерии допуска к замене:
1. Нет регрессии по tenant/project isolation и защите документов.
2. Все ответы и производные данные сохраняют проверяемую связь с immutable DocumentVersion и исходным SourceFragment.
3. LM Studio работает без скрытого fallback на облачные модели.
4. Измеримые показатели качества, latency и устойчивости не хуже согласованных порогов.
5. Есть миграция данных, план отката, backup/restore и проверенные тесты.
6. Bionic не становится параллельным владельцем проектов, документов и идентичности без отдельного архитектурного решения.
