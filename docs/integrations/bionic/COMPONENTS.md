# Сравнительный аудит компонентов Bionic и Personal Expert AI

- Дата: 2026-11-03.
- Bionic tree: `8a9797c39680ae8421bfaef72f87eb90650e7a09`.
- Personal Expert AI commit: `7858c46eb4545efef7f78e4d3167b61266822484`.
- Метод: статический анализ исходников, миграций, SQL-запросов, README и Compose.
- Статус: аудит завершён; выводы предварительные до runtime POC.

## Итоговая матрица

| Направление | Что есть в Bionic | Что есть у нас | Предварительное решение |
|---|---|---|---|
| Хранение данных | PostgreSQL, документы/datasets, object storage adapter, virtual filesystem, generated outputs | Локальное файловое хранилище, SHA-256, immutable DocumentVersion, durable upload journal, reconciliation, ProcessingArtifact | **KEEP + ADAPT**: сохранить оригиналы и provenance; исследовать VFS как агентный workspace |
| RAG | Отдельный ingestion worker, chunking через Unstructured/Kreuzberg API, embeddings и pgvector, dataset retrieval | SourceFragments и Knowledge Model; полноценный production retrieval/embedding pipeline ещё не завершён | **ADAPT / POC**: проверить retrieval engine Bionic, но не передавать ему ownership источников |
| Пользователи и разрешения | OIDC boundary, users, teams, RBAC, roles/permissions, PostgreSQL RLS | tenants, users, memberships, projects, project memberships, JWT validation boundary, PostgreSQL RLS и integration tests | **ADAPT / POC**: сравнить policy model; не переносить team model без tenant/project mapping |
| Обработка запросов | Agent harness: prompt/context assembly, history, model calls, streaming, tools, moderation, limits, request recording, scheduled continuation | Provider contracts и LM Studio adapter; API и storage/processing worker; полноценный chat orchestrator пока не реализован | **POC с высоким приоритетом**: наиболее перспективный кандидат для повторного использования |
| Agent runtime | Tool runtime, MCP/OpenAPI integrations, Skills, VFS, lazy materialization, scheduled tasks, sandbox interface | Есть архитектурные заготовки; полноценный runtime и Skills execution отсутствуют | **ADAPT / POC**: лучший кандидат на повторное использование концепций и ограниченного кода |
| Audit и эксплуатация | Audit-related DB migrations/handlers, metrics, token usage, Docker/Kubernetes deployment | AuditEvent schema, CI и локальные процессы; production observability и operator tooling ограничены | **ADAPT**: перенять события/метрики и deployment-практики после security review |

## 1. Хранение данных и виртуальная файловая система

### Bionic

Изучены `crates/object-storage/src/lib.rs`, `crates/tool-runtime/lazy_fs.rs`, database queries и migrations. Object storage adapter содержит DB-backed вариант. Supabase backend объявлен, но операции upload/get возвращают ошибку «not implemented». DB upload сохраняет объект в БД и вычисляет MD5; это не эквивалент нашей схеме immutable original + SHA-256 + atomic filesystem publication. Lazy VFS позволяет показывать метаданные и каталоги, загружая bytes только при чтении; изменения фиксируются как changed files, есть read-only protected roots.

### Personal Expert AI

Есть потоковая загрузка, SHA-256, атомарная публикация без перезаписи, durable upload journal, checksum verification при чтении, immutable document version, recovery/reconciliation и artifacts с checksum/provenance.

### Вывод

Не заменять наш original storage Bionic object storage. Изучить и при необходимости адаптировать Bionic VFS/lazy loading как изолированное рабочее пространство агента, подключённое к нашим DocumentVersion/Artifact API. Важное условие — агент не должен напрямую менять оригиналы; результаты должны записываться как новые контролируемые artifacts.

## 2. RAG и поиск знаний

### Bionic

В `crates/rag-engine` есть worker, который выбирает необработанные документы, получает dataset settings, загружает bytes, отправляет документы во внешний Unstructured или Kreuzberg endpoint, создаёт chunks и запускает embedding flow. DB содержит pgvector/RAG схемы, chunks, datasets и retrieval queries. ChunkText в проверенном модуле хранит текст и необязательный номер страницы.

### Personal Expert AI

У нас уже реализованы более детальные extraction adapters для PDF/DOCX/XLSX/PPTX, structured pages, OCR, bbox/ячейки/слайды, ProcessingRun, SourceFragment и provenance. Однако end-to-end hybrid retrieval, embedding index, reranking и grounded Q&A ещё не завершены.

### Вывод

Bionic — сильный кандидат для POC общего RAG, но его chunk/page metadata недостаточно, чтобы считать доказанным сохранение наших инженерных локаторов. Нужен benchmark на одинаковом наборе документов: recall@k, precision@k, MRR/nDCG, latency, устойчивость к таблицам/формулам/обозначениям, точность ссылки до исходной страницы и bbox/cell. Вероятный вариант — использовать Bionic retrieval/runtime, но индексировать наши SourceFragments и возвращать их IDs/provenance.

**Риск:** Bionic ingestion вызывает внешние относительно RAG worker HTTP endpoints Unstructured/Kreuzberg. Для local-only режима нужно проверить размещение этих сервисов, сетевые правила и отсутствие внешнего egress.

## 3. Пользователи, авторизация и разрешения

### Bionic

В DB есть users, teams, team_users, roles, permissions, projects, datasets и RLS. `crates/db/authz.rs` формирует RBAC context и устанавливает user id в transaction-local PostgreSQL setting. OIDC endpoint создаёт/находит пользователя и настраивает его team.

Но `crates/agent-harness/jwt.rs` и `crates/web-server/jwt.rs` декодируют JWT payload и читают claims; криптографическая проверка подписи, issuer и audience в этих файлах не выполняется — они предполагают доверенную upstream authentication boundary. Нельзя выставлять такой endpoint напрямую в интернет без проверенного auth proxy/IdP. В agent-harness CORS настроен на Any; это требует ограничения origins и методов перед production.

### Personal Expert AI

У нас есть tenant/project UUID модель, membership, composite FKs, PostgreSQL RLS, transaction-local tenant context, JWT principal validation и integration tests на tenant isolation. Token issuance/refresh и полноценный IdP lifecycle остаются отдельной работой.

### Вывод

Не переносить Bionic auth как готовое решение «подключил и безопасно». Сравнить его RBAC и UI flows, использовать только за доверенной auth boundary. Необходимо явное отображение Bionic user/team IDs на наш tenant/project principal, проверка каждой операции и тесты IDOR/cross-tenant. Предпочтительно оставить identity и project membership source of truth у Personal Expert AI.

## 4. Обработка запросов и диалог

### Bionic

`agent-harness/chat_request.rs` и `ui_chat_orchestrator.rs` реализуют загрузку модели, чата, conversation history, model capabilities, сборку контекста, tool definitions, moderation/limits, streaming и сохранение результата. Также есть request recording и scheduled continuations. Это уже рабочая реализация, а не только спецификация.

### Personal Expert AI

У нас provider-neutral LLM contracts и LM Studio adapter с chat, streaming, embeddings, health/model listing и capability gating. Но полноценный conversational orchestrator, conversation lifecycle и tool loop ещё не соединены с API.

### Вывод

Один из приоритетных POC. Проверить, можно ли использовать Bionic orchestrator поверх наших API и provider boundary. Важны совместимость Rig/OpenAI-compatible adapter с LM Studio, корректное streaming, cancellation, tool calling, structured output, error mapping и отсутствие облачного fallback. Не подключать Bionic к нашей БД напрямую без отдельного решения по границе владения данными.

## 5. Agent runtime, инструменты, Skills и sandbox

### Bionic

В `crates/tool-runtime` есть tool catalog/dispatcher, MCP client, OpenAPI adapters, Skills, scheduled tasks, file tools и virtual filesystem. `lazy_fs.rs` поддерживает ленивую материализацию файлов, tracking изменений и protected roots. `crates/sandbox` задаёт интерфейсы файловой системы и сети, Bashkit execution adapter и ограничения запросов.

Это не следует автоматически считать полноценной изоляцией уровня отдельной VM/container. Проверить фактическую границу исполнения, CPU/memory/time limits, process isolation, filesystem roots, symlink/path traversal и network egress. Sandbox abstraction полезна, но её реальная безопасность зависит от concrete implementation и deployment.

### Вывод

Самый перспективный компонент для адаптации после orchestrator. Проводить POC в отдельном окружении с недоверенными fixtures. Tools должны быть allowlisted и получать tenant/project-scoped capabilities от нашего backend. Skills — версионируемые, с правами, provenance и approval для write/network операций.

## 6. Audit, наблюдаемость и deployment

Bionic содержит migrations/queries/handlers для audit, token usage, metrics, request records, scheduled tasks и Docker/Kubernetes deployment. Это шире наших текущих эксплуатационных возможностей и полезно как источник практик.

При этом Compose в репозитории прямо помечен как пример, не production-конфигурация; содержит тестовые credentials и `DANGER_JWT_OVERRIDE`, публикует несколько портов. Это запрещено переносить в production без переработки. Проверить CORS, auth boundary, secrets, network policies, backups, migrations, logs и resource limits.

### Вывод

ADAPT: перенять структуру telemetry/audit и deployment ideas, но не копировать example Compose как production deployment.

## Приоритет POC

1. **P0 — Chat orchestrator + LM Studio.** Наибольший разрыв в нашем продукте; быстрый тест ценности.
2. **P1 — Agent runtime + VFS + Skills.** Проверить tools, file access, sandbox и write journal.
3. **P2 — RAG retrieval.** Сравнить качество и точность provenance на нашем инженерном наборе.
4. **P3 — Authorization mapping.** Только после проектирования identity boundary и тестов изоляции.
5. **P4 — Audit/observability.** Сравнить полезность и стоимость адаптации.
6. **Не заменять** original storage и engineering extraction pipeline до появления доказательств превосходства Bionic по нашим acceptance criteria.

## Что не проверено

- Bionic не разворачивался и не тестировался в runtime.
- Не проведён penetration test и не подтверждена production security posture.
- Не измерялись качество RAG и latency.
- LM Studio не проверялся end-to-end с Bionic.
- Не подтверждена полная совместимость Bionic identity/permissions с tenant/project UUID моделью Personal Expert AI.
- Не подтверждена эквивалентность provenance на инженерных документах.
