# Bionic POC — план исполнения и журнал результатов

- Дата: 2026-11-03.
- Bionic upstream: https://github.com/bionic-gpt/bionic-gpt
- Upstream revision: 8a9797c39680ae8421bfaef72f87eb90650e7a09.
- Personal Expert AI baseline: b0b1d5d1b40f14c413d610d6aa79ea7b964a67b4.
- Статус: подготовка POC; runtime испытания не выполнены.
- Ограничение: LM Studio сейчас недоступен пользователю; реальные runtime тесты не отмечать как пройденные.

## Решение по форку
Основной экспериментальный путь — отдельный форк Bionic с адаптацией UI под Personal Expert AI. Форк сохраняет upstream историю и лицензионные уведомления Apache-2.0. Изменения UI отделяются от изменений agent runtime и backend.
Предлагаемое имя: Dach1980/bionic-personal-expert-ai. Создать через GitHub Fork; если операция недоступна, не имитировать fork копированием файлов. После создания закрепить upstream remote и вести журнал синхронизации.

## Архитектурные ограничения
- PostgreSQL Personal Expert AI — единственный источник истины для tenant, project, document, immutable versions, processing runs, source fragments, knowledge и review records.
- Bionic не получает прямые credentials к БД Personal Expert AI.
- Интеграция только через backend API adapter с allowlisted endpoints.
- Backend сам определяет principal, tenant и project scope; модель не может задавать или расширять scope.
- Bionic VFS получает виртуальные файлы и артефакты через API, но не меняет оригиналы.
- Bionic RAG не индексирует оригиналы независимо до отдельного решения; сначала POC над SourceFragment с сохранением provenance.
- Никакого cloud fallback. LM Studio доступен только через loopback/private network.
- UI не содержит секретов, DB credentials или provider API keys.

## A — модель, streaming, tool calling
Без LM Studio: проверить provider adapter contract и capability gating; mock-тестировать OpenAI-compatible mapping; проверить streaming fixtures; нормализацию tool-call proposal; отказ на неизвестной capability; loopback-only и отсутствие cloud fallback.
Требует LM Studio: реальный Qwen chat, streaming/cancellation, tool calling на выбранной сборке/template, structured output, embeddings, concurrency, model load/unload, VRAM, latency и network capture.
Критерий: mock/contract tests проходят; реальные сценарии отмечаются отдельно.

## B — PDF, DOCX, XLSX
Personal Expert AI уже имеет локальные adapters: PDF pages/native text/blocks/bbox/render/OCR; DOCX paragraphs/styles/tables/cells/images; XLSX sheets/cells/values/formulas/merged ranges/images.
Проверка: подготовить обезличенный комплект с контрольными фактами и locator ground truth; загрузить через authenticated API; запустить ProcessingRun; сверить extraction manifest, SourceFragment и locator; отдельно сравнить Bionic extraction/RAG; измерить completeness, locator accuracy, duplicate rate, latency и warnings.
Критерий: каждый контрольный факт имеет точный source locator. Потеря locator считается дефектом, даже если текст извлечён правильно.
Статус: статический анализ адаптеров выполнен; E2E набор и runtime сравнение не выполнены.

## C — Skill проверки документации
Подготовлен экспериментальный Skill: skills/project-documentation-review/SKILL.md.
Проверки: read-only API; pass/fail/partial/unknown/blocked; provenance; prompt-injection resistance; запрет прямого доступа к БД и оригиналам; approval для write actions; отсутствие cloud fallback.
Критерий: выводы grounded; недостаток доказательств даёт unknown; cross-project access отклоняется backend; prompt injection не расширяет полномочия.
Статус: текст Skill подготовлен; исполнение в Bionic runtime не выполнено.

## Проверенный API surface Personal Expert AI

По текущим исходникам main подтверждены маршруты:
- GET /api/v1/tenants/{tenant_id}/projects
- GET /api/v1/tenants/{tenant_id}/projects/{project_id}/documents
- POST /api/v1/tenants/{tenant_id}/projects/{project_id}/documents
- POST /api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions
- GET /api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/content
- POST и GET processing-runs для конкретной document version.

Обнаруженные пробелы для полноценного grounded agent:
- нет подтверждённого GET списка/метаданных версий документа;
- нет read API для SourceFragment и provenance locators;
- нет API поиска/retrieval по фрагментам;
- нет API для создания/чтения результатов инженерной проверки и review evidence.

Следовательно, Bionic пока нельзя подключить как полноценного агента для ответов с доказательствами только на существующих API. Первый adapter может быть read-only для списка проектов/документов и статусов ProcessingRun. Следующий backend этап — добавить tenant/project-scoped read endpoints для immutable versions, SourceFragments и retrieval, затем contract tests и только потом зарегистрировать их как Bionic tools.

## D — интеграция с backend
Поток: customized Bionic UI → Bionic agent harness → Personal Expert API adapter → FastAPI auth/authz → Repository/Service Layer → PostgreSQL RLS + local storage/worker.
Bionic вызывает API только через adapter/tool gateway. Backend не доверяет tenant_id/project_id из tool arguments; scope извлекается из authenticated principal.
Первый этап read-only. Предполагаемые ресурсы: project, documents, immutable versions, processing runs, source fragments. Перед созданием tool schema сверить реальные маршруты и response models в OpenAPI; не выдумывать endpoints.
Security tests: missing/invalid/expired JWT; user A requests user B project; cross-tenant document/version/fragment; cross-project ID substitution; unauthorized artifact write; direct DB access disabled; no secrets in frontend; no direct browser calls to PostgreSQL/LM Studio.
Критерий: Bionic не имеет DB connection string, не владеет документами и не обходит backend authorization.

## План адаптации интерфейса форка
1. Создать настоящий GitHub fork upstream; не заменять его копией исходников.
2. Поднять upstream без кастомизаций и зафиксировать baseline build/test.
3. Найти UI entrypoints и составить карту компонентов/роутов.
4. Выделить branding/theme/navigation/chat shell в минимально инвазивный слой.
5. Использовать логотип https://raw.githubusercontent.com/Dach1980/cherkashin_ai_site/main/assets/logo.svg для header/footer/favicon.
6. Навигация: Проекты, Документы, Диалоги, Проверки, База знаний, Skills, Настройки.
7. Добавить project/document context, evidence cards с page/sheet/cell locators и streaming chat.
8. Подключить API adapter; сохранить upstream sync path и regression tests.

## Статус
| Проверка | Сейчас | Осталось |
|---|---|---|
| A: mock provider contract | ранее реализован в Personal Expert AI | проверить CI и расширить fixtures |
| A: real Qwen/LM Studio | blocked | нужен LM Studio runtime |
| B: parser static review | выполнен | контрольный комплект и ground truth |
| B: extraction E2E | не выполнен | fixtures и запуск worker |
| C: Skill authoring | подготовлено | запуск в Bionic и adversarial tests |
| D: API boundary design | подготовлено | сверить OpenAPI, реализовать adapter/tests |
| UI fork | решение принято | создать GitHub fork, затем UI layer |

## Правило закрытия POC
Статический анализ и mock-тесты не доказывают runtime совместимость Bionic/LM Studio или реальную точность извлечения. Закрывать сценарии только по фактическим логам, тестам и manifests.