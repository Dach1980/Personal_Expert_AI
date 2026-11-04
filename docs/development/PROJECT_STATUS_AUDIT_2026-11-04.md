# Сводный аудит состояния и план разработки Personal Expert AI

- Дата фиксации: 2026-11-04.
- Основной репозиторий: https://github.com/Dach1980/Personal_Expert_AI
- UI/agent runtime fork: https://github.com/Dach1980/bionic-personal-expert-ai
- Публичный репозиторий рабочего сайта: https://github.com/Dach1980/Personal_Expert_AI_Web
- Публичный адрес сайта: https://dach1980.github.io/Personal_Expert_AI_Web/
- Ветка ведения разработки: `main`.

> Этот документ фиксирует состояние по коду и документации репозиториев на дату аудита. Отметка «реализовано» означает наличие соответствующего кода/миграций/тестов; runtime-функция считается подтверждённой только после фактического запуска и прохождения описанных проверок. Этот аудит не заменяет CI и не объявляет непроверенные интеграции готовыми.

## 1. Принятые архитектурные решения

- [x] Personal Expert AI — отдельный продукт и владелец доменной логики, пользователей, tenant/project access, документов, версий, SourceFragment и результатов инженерной проверки.
- [x] Bionic — отдельный fork для адаптации интерфейса и проверки agent runtime; не является источником истины для доменных данных PEA.
- [x] PEA и Bionic взаимодействуют через серверный API Adapter; Bionic не получает прямые credentials к PostgreSQL PEA.
- [x] PostgreSQL PEA — источник истины; оригиналы и артефакты хранятся в локальном storage с контролем целостности.
- [x] Local-first: LM Studio — целевой локальный inference runtime за provider abstraction; незаметный cloud fallback запрещён.
- [x] Keycloak Stack, поставляемый вместе с Bionic, используется как единый IdP/realm для входа; второй независимый Keycloak для этой интеграции не поднимается.
- [x] Внешняя идентичность связывается с PEA по паре `(issuer, subject)`; наличие tenant claim само по себе не выдаёт права.
- [x] Разработка ведётся в `main`, если отдельное решение не согласовано.

## 2. Что уже реализовано в Personal Expert AI

### Архитектура и проектирование

- [x] Создан отдельный публичный репозиторий PEA.
- [x] Подготовлены продуктовые и архитектурные спецификации, доменная модель, API-контракты, lifecycle документов, knowledge/memory/security/LLM provider документы.
- [x] Подготовлены ERD, схема PostgreSQL и целевая архитектура.
- [x] Зафиксированы решения по использованию Bionic и границам интеграции.
- [x] Подготовлены документация Keycloak и сценарии первичного workspace/identity provisioning.

### Backend, БД и безопасность

- [x] FastAPI backend и health endpoint.
- [x] PostgreSQL, SQLAlchemy 2.x и Alembic migrations.
- [x] Tenant, Project, Document и DocumentVersion модели; ранее зафиксированный размер модели — 17 SQLAlchemy-таблиц, сверять актуальный состав по моделям и миграциям.
- [x] Composite foreign keys для согласованности tenant/project и document/version.
- [x] PostgreSQL RLS и transaction-local tenant context.
- [x] Repository/Service Layer для основных сущностей.
- [x] Tenant/project access checks в защищённых API.
- [x] External identity mapping `(issuer, subject)`.
- [x] PEA JWT RS256/JWKS validation с проверкой issuer, audience и временных claims.
- [x] Подготовлены скрипты настройки общего Keycloak realm и provisioning внешней identity.
- [x] PostgreSQL 16 CI включает migration upgrade/check/downgrade/re-upgrade, ORM/schema checks, RLS integration tests, pytest и Ruff.
- [x] Реализован локальный runtime DB role подход без SUPERUSER/BYPASSRLS; эксплуатационное применение конфигурации на целевом окружении проверяется отдельно.

### Загрузка и обработка документов

- [x] Локальное хранилище оригиналов с SHA-256, staging и атомарной публикацией.
- [x] Durable UploadOperation journal, idempotency, quarantine и crash recovery.
- [x] Проверки формата PDF, DOCX, XLSX и PPTX.
- [x] Authenticated upload/download API и проверка целостности при чтении.
- [x] ProcessingRun queue, worker leases, heartbeat, retry и ProcessingArtifact.
- [x] Локальные extraction adapters PDF/DOCX/XLSX/PPTX.
- [x] SourceFragment с locator, content hash и provenance.
- [x] PDF page rendering, structured page model, Tesseract OCR и базовая геометрическая дедупликация.
- [x] OCR benchmark runner и synthetic smoke test.

## 3. Что реализовано частично или ещё требует подтверждения

### PEA backend и база данных

- [x] Добавлена catalog-level сверка ORM и PostgreSQL для FK (с колонками, target и `ON DELETE`), UNIQUE, CHECK names и индексов; дополнительно сохраняются `alembic check` и сравнение таблиц/колонок.
- [x] Повторно подтверждён PostgreSQL 16 CI: upgrade, schema parity, integration tests, downgrade base, re-upgrade head, full pytest и Ruff — success (run [41760466319](https://github.com/Dach1980/Personal_Expert_AI/actions/runs/41760466319)).
- [x] Подтверждены существующие adversarial tests: cross-tenant composite FK, document/version project consistency, RLS visibility, cross-project document access, viewer upload denial и JWT tenant-context lookup.
- [ ] Полное покрытие каждого endpoint и всех негативных OIDC/membership lifecycle сценариев остаётся открытым.
- [ ] Проверить production runtime DB role, секреты, TLS и настройки подключения на целевом стенде.
- [ ] Зафиксировать явные правила удаления/архивирования доменных сущностей. В текущих FK нет `ON DELETE CASCADE`; действует ограничительное поведение PostgreSQL по умолчанию.
- [ ] Решить, нужны ли SQLAlchemy `relationship()` mappings: сейчас они отсутствуют; целостность обеспечивается FK/constraints и сервисным слоем.
- [ ] Проверить ротацию/отзыв identity, изменения membership и отказ доступа после блокировки пользователя/tenant.
- [ ] Проверить полный цикл backup/restore на реальном окружении.

### Keycloak и Bionic authentication

- [x] Документирована конфигурация общего Stack-managed realm `bionic-gpt`, клиента Bionic и audience `pea-api`.
- [x] Подготовлен mapper `tenant_id` и скрипт настройки realm.
- [x] В PEA реализована независимая проверка JWT и membership.
- [ ] На целевом Stack выполнить bootstrap realm и сверить discovery issuer/JWKS.
- [ ] Создать/проверить пользователя Keycloak и сопоставить его с уже существующим PEA user.
- [ ] Проверить реальный браузерный login flow.
- [ ] Подтвердить, что доверенный OIDC gateway удаляет подставленный клиентом `X-Forwarded-Access-Token` и сам передаёт проверенный access token.
- [ ] Проверить Bionic JWT implementation сборкой и тестами; не считать статический просмотр файла доказательством успешной компиляции/безопасности.
- [ ] Проверить negative cases: неизвестный subject, disabled identity/user/tenant, отсутствие membership, cross-tenant и cross-project доступ.

### Bionic fork и API Adapter

- [x] Создан отдельный fork `Dach1980/bionic-personal-expert-ai`.
- [x] Зафиксировано решение адаптировать UI Bionic, сохраняя возможность заменить его без переписывания PEA backend.
- [x] Подготовлен UI fork plan и POC execution plan.
- [ ] Подтвердить чистую baseline-сборку upstream fork.
- [ ] Исправить/проверить compile issues, включая замеченный повторный импорт `STANDARD` в `crates/web-server/jwt.rs`, если он всё ещё присутствует в текущем HEAD.
- [ ] Выполнить сборку и тесты Bionic после последних изменений.
- [ ] Завершить серверный API Adapter с allowlist реальных PEA endpoints.
- [ ] Сверить API contract с актуальным OpenAPI; не добавлять вымышленные маршруты.
- [ ] Добавить read endpoints для списка/метаданных DocumentVersion, SourceFragment/provenance и retrieval, если их ещё нет.
- [ ] Подключить реальные проекты, документы, версии, статусы обработки и evidence в UI.
- [ ] Проверить ACL и отсутствие прямого доступа Bionic к БД PEA, файловому storage и LM Studio.
- [ ] Провести E2E тест Bionic → Adapter → PEA API → PostgreSQL/storage.

### LM Studio, OCR и knowledge

- [x] Подготовлен provider-neutral контракт и начальный LM Studio OpenAI-compatible adapter с mock tests.
- [ ] На целевой машине выполнить реальные LM Studio smoke tests: chat, streaming, cancellation, embeddings, tool calling, structured output, vision, concurrency, load/unload, VRAM, latency и network capture.
- [ ] Измерить OCR accuracy на реальном обезличенном русскоязычном инженерном наборе с Ground Truth.
- [ ] Сравнить Tesseract, PaddleOCR и EasyOCR на одном наборе.
- [ ] Улучшить extraction формул, сложных таблиц, vector drawings и инженерных изображений.
- [ ] Реализовать quality/completeness scoring.
- [ ] Реализовать индексирование, hybrid retrieval, reranking и точные evidence locators.
- [ ] Провести ingestion/RAG benchmark на едином контрольном комплекте.
## 4. Публичный сайт — обязательный отдельный deliverable

**Решение от 2026-11-04: рабочую публичную web-версию Personal Expert AI необходимо разрабатывать в отдельном публичном репозитории `Dach1980/Personal_Expert_AI_Web` и публиковать через GitHub Pages по адресу https://dach1980.github.io/Personal_Expert_AI_Web/. Это не факультативная альтернатива и не только документация — отдельный обязательный поток разработки продукта.**

- [x] Зафиксировано имя публичного репозитория: `Personal_Expert_AI_Web`.
- [x] Зафиксирован публичный URL GitHub Pages.
- [x] Публичный репозиторий существует, default branch — `main`.
- [x] Есть React + TypeScript + Vite SPA scaffold, Sidebar, ProjectList, ChatPanel и адаптивное рабочее пространство.
- [x] Есть Vite base path `/Personal_Expert_AI_Web/`.
- [x] Есть GitHub Actions workflow; Pages deployment run #51 от 2026-11-03 завершился `success`.
- [x] Есть изолированный API client для будущего API Adapter.
- [ ] Проверить текущую доступность сайта и прямые SPA routes/refresh в браузере.
- [x] Использовать существующий `assets/logo.svg` в header/sidebar, footer и favicon (`index.html`).
- [ ] Завершить финальную проверку визуального branding и адаптивности в браузере.
- [x] Доработать API client и подключить загрузку session/projects к PEA endpoints `/api/v1/session` и `/api/v1/projects`; API contract документирован.
- [ ] Развернуть доверенный HTTPS API gateway/BFF для cookie session → Bearer token; не подключать браузер напрямую к PEA/Bionic внутренним адресам.
- [ ] Реализовать реальный Keycloak/OIDC login/session UX через доверенный gateway; текущая UI обрабатывает 401, но не выполняет login/logout.
- [ ] Подключить frontend к защищённому backend API через HTTPS gateway; настроить точный CORS allowlist.
- [ ] Реализовать проекты, документы, версии, processing status, чат и evidence presentation.
- [ ] Проверить streaming/SSE, browser refresh, logout, token lifecycle и обработку ошибок.
- [ ] Провести E2E и security tests: IDOR, cross-tenant/project, XSS, утечка токенов, CORS и отсутствие прямых запросов из браузера к PostgreSQL/LM Studio.

### Граница GitHub Pages

GitHub Pages — статический хостинг. В публичном репозитории размещаются frontend-код, статические ресурсы и публичная документация. GitHub Pages не запускает FastAPI, Bionic server, Keycloak, PostgreSQL, worker или LM Studio. Backend и доверенные операции остаются на отдельном защищённом runtime.

Запрещено помещать в публичный репозиторий и frontend bundle:
- пароли, client secrets, signing keys, DB credentials и provider API keys;
- приватные документы, пользовательские данные, внутренние индексы и результаты проверок;
- постоянные bearer tokens или секреты, позволяющие обходить backend authorization.

Если backend работает только локально/в частной сети, публичная Pages-страница не сможет безопасно обращаться к нему без специально настроенного защищённого канала. Не публиковать PostgreSQL, LM Studio или внутренние Bionic/PEA порты в интернет.

### Связь публичного сайта и Bionic

Публичный frontend в `Personal_Expert_AI_Web` — отдельный клиент продукта и обязательный deliverable. Bionic fork — самостоятельная серверная/UI/agent-runtime ветка для POC и возможного переиспользования компонентов. Не смешивать их deployment responsibilities. Frontend должен обращаться к собственному API adapter/контракту; на первом этапе backend может маршрутизировать допустимые операции в PEA и/или Bionic. Это сохраняет возможность заменить Bionic без переписывания сайта и доменной логики.

## 5. Дальнейшая последовательность работ

### Этап 1 — закрыть целостность и базовую безопасность

- [ ] Повторно проверить актуальный GitHub Actions status обоих репозиториев.
- [ ] Завершить расширенный аудит PostgreSQL schema: FK, unique/index, CHECK, cascade/delete, relationships.
- [ ] Проверить migration upgrade → downgrade → upgrade на PostgreSQL 16.
- [ ] Довести adversarial tenant/project isolation tests.
- [ ] Проверить runtime DB role, RLS и tenant context.
- [ ] Устранить и перепроверить ошибки Bionic build, включая повторный импорт в JWT модуле.
- [ ] Зафиксировать результаты тестов и commit SHAs.

### Этап 2 — запустить общую авторизацию

- [ ] Развернуть Bionic Stack с единым Keycloak.
- [ ] Настроить realm/client/audience/JWKS.
- [ ] Provision PEA user, tenant/project memberships и external identity.
- [ ] Подключить доверенную передачу access token через gateway.
- [ ] Проверить положительные и отрицательные authz сценарии.

### Этап 3 — сделать рабочий публичный сайт

- [ ] Инициализировать/проверить репозиторий `Personal_Expert_AI_Web`.
- [ ] Настроить GitHub Pages и автоматическую публикацию из `main`.
- [ ] Собрать интерфейс приложения, branding и навигацию.
- [ ] Реализовать API client и auth/session integration.
- [ ] Подключить реальные проекты/документы после готовности API.
- [ ] Проверить браузерный E2E flow и безопасность.

### Этап 4 — закончить интеграцию Bionic ↔ PEA

- [ ] Завершить API Adapter и read-only integration.
- [ ] Добавить недостающие версии, SourceFragment, retrieval и evidence API.
- [ ] Подключить данные в Bionic fork.
- [ ] Проверить streaming, project context и ACL.
- [ ] Принять отдельное решение, какие Bionic компоненты REUSE / ADAPT / KEEP / REPLACE.

### Этап 5 — локальный AI и интеллектуальная обработка

- [ ] Провести LM Studio runtime tests.
- [ ] Завершить OCR benchmark и сравнение движков.
- [ ] Реализовать retrieval/RAG с точными доказательствами.
- [ ] Добавить формулы, таблицы, чертежи и vision enrichment.
- [ ] Реализовать grounded chat по проектной документации.

### Этап 6 — память, Skills и инженерные проверки

- [ ] Реализовать User/Project/Professional/Session memory.
- [ ] Реализовать Skills Registry, версии, approval и execution audit.
- [ ] Интегрировать проверенные модули Project Expert AI.
- [ ] Реализовать инженерные проверки и отчёты с provenance.

### Этап 7 — эксплуатационная готовность

- [ ] Проверить multi-user isolation для документов, индексов, памяти, истории, логов, кэшей и артефактов.
- [ ] Настроить backup/restore и проверить восстановление.
- [ ] Добавить аудит действий, мониторинг и лимиты ресурсов.
- [ ] Провести security review и проверку local-only network policy.
- [ ] Подготовить воспроизводимую инструкцию deployment.

## 6. Критерии первого рабочего прототипа

Прототип считается сквозным только когда пользователь:

1. Открывает публичный сайт GitHub Pages.
2. Проходит авторизацию через согласованный Keycloak flow.
3. Видит только доступные ему tenant/project.
4. Открывает проект и загружает документ через защищённый backend.
5. Видит статус обработки и документные версии.
6. Задаёт вопрос по документации.
7. Получает ответ локальной LLM с указанием файла, версии, страницы/листа и подтверждающего SourceFragment.
8. Может открыть исходный фрагмент/страницу.9. Не может получить данные другого tenant/project даже при подмене идентификаторов в запросах.

До прохождения этого сценария система остаётся прототипом, даже если отдельные компоненты или страницы уже работают.

## 7. Правило обновления аудита

- Обновлять этот файл после существенного этапа и подтверждения тестами.
- В каждом обновлении фиксировать дату, commit SHA, workflow run и фактический результат.
- Не отмечать задачу выполненной только по наличию документации или mock test, если для неё требуется runtime.
- Не переносить в публичный репозиторий пользовательские документы, секреты или приватные результаты.
- Основные репозитории и дальнейшая разработка: PEA backend — `Personal_Expert_AI`; Bionic fork — `bionic-personal-expert-ai`; публичный сайт — `Personal_Expert_AI_Web`.

## 8. Сверка репозиториев на 2026-11-04

После фиксации исходного аудита выполнена отдельная сверка трёх репозиториев по фактическим HEAD, исходникам, API-контрактам и доступным commit status checks. Результат: [REPOSITORY_RECONCILIATION_2026-11-04.md](REPOSITORY_RECONCILIATION_2026-11-04.md).

Краткий вывод: PEA backend и conversation/provider API реализованы на уровне кода; Bionic PEA Adapter содержит document/conversation routes, но PEA document retrieval в Agent Runtime ещё не реализован; Web 0.4.0 содержит PKCE/API client/chat/document workspace. Реальный Keycloak login, trusted gateway, LM Studio runtime и сквозной E2E остаются неподтверждёнными.

Commit combined status checks для актуальных HEAD не вернули status contexts, а доступный GitHub connector не предоставил общий список последних push workflow runs. Поэтому исторические успешные CI run, перечисленные выше, не перенесены на текущие HEAD. Следующая задача — зафиксировать актуальные Actions runs всех трёх репозиториев, закрыть Bionic Rust build/test gate и затем проверить trusted gateway + реальный PKCE login в локальном Stack. См. подробный порядок и критерии приёмки в отчёте сверки.


## Execution update — 2026-11-04

The eight-step execution checklist has been evaluated against current GitHub Actions and repository source. Steps 1 (CI confirmation) and 2 (Bionic Rust tests/build) are complete. Steps 3–7 require a live local Stack/Keycloak/PEA/LM Studio runtime and remain unaccepted. Step 8 (PEA document retrieval in Agent Runtime) requires implementation of a scoped search API/tool and grounded-answer tests; it is not an environment-only task.

Detailed evidence, run URLs, exact tested SHAs, current limitations and the next UAT procedure are recorded in [REPOSITORY_RECONCILIATION_2026-11-04.md](REPOSITORY_RECONCILIATION_2026-11-04.md), section 10.


### Deployment provenance gate added

A further review of Bionic `infra-as-code/stack.yaml` and `docker-compose.yml` found that both currently reference the upstream image `ghcr.io/bionic-gpt/bionicgpt:1.13.4`, not an image built from the Personal Expert AI fork. The Rust CI validates source code but does not build/publish the fork container image or validate `infra-as-code/**`.

Therefore, before runtime authorization tests, the fork-specific image must be built/deployed and its immutable digest verified. The detailed finding and required remediation are in section 10.5–10.6 of [REPOSITORY_RECONCILIATION_2026-11-04.md](REPOSITORY_RECONCILIATION_2026-11-04.md). No registry/tag was invented and no deployment manifest was changed without choosing the image delivery method.
