# Backend API — контракты UI и backend

- Статус: проект спецификации API, версия 1.0
- Дата: 2026-11-02
- Базовый префикс: /api/v1

## 1. Назначение

Backend является единственным владельцем доменной логики и доступа к данным. UI (AnythingLLM на этапе прототипа или собственный frontend позднее) обращается к Personal Expert AI API. UI не получает прямой доступ к PostgreSQL, файловому хранилищу, индексам, секретам LLM provider или внутренним инструментам.

Контракт ориентирован на REST/JSON; длительные операции выполняются асинхронно. Для потоковых ответов допускается SSE. Конкретные схемы Pydantic должны соответствовать этой спецификации и иметь OpenAPI описание.

## 2. Общие правила

- Все пути версионированы: /api/v1.
- Все даты/время — ISO 8601 UTC; календарные даты проектирования/нормативной применимости передаются отдельно.
- UUID используется для идентификаторов.
- Список поддерживает limit/cursor или limit/offset с документированным порядком сортировки.
- Запросы, изменяющие состояние, требуют аутентификации и CSRF-защиты, если используется cookie session.
- Каждый запрос проверяет tenant scope, project membership и разрешение на операцию.
- Внутренние storage keys, абсолютные пути, API keys и секреты не возвращаются.
- Для изменяющих запросов поддерживается Idempotency-Key там, где повтор может создать дубликат/задачу.
- Ошибки имеют единый формат.

Пример ошибки:
```json
{
  "error": {
    "code": "PROJECT_ACCESS_DENIED",
    "message": "Access to this project is not permitted.",
    "request_id": "uuid",
    "details": {}
  }
}
```

## 3. Основные ресурсы и маршруты

### Health и конфигурация
- GET /health — процесс жив.
- GET /ready — приложение и обязательные зависимости готовы.
- GET /api/v1/capabilities — доступные функции и ограничения без раскрытия секретов.

### Пользователи и проекты
- GET /api/v1/me
- GET /api/v1/workspaces
- POST /api/v1/workspaces
- GET /api/v1/projects
- POST /api/v1/projects
- GET /api/v1/projects/{project_id}
- PATCH /api/v1/projects/{project_id}
- GET /api/v1/projects/{project_id}/members
- PUT /api/v1/projects/{project_id}/members/{user_id}

### Документы
- POST /api/v1/projects/{project_id}/documents — регистрация/загрузка.
- GET /api/v1/projects/{project_id}/documents
- GET /api/v1/documents/{document_id}
- GET /api/v1/documents/{document_id}/versions
- GET /api/v1/document-versions/{version_id}
- POST /api/v1/document-versions/{version_id}/process
- GET /api/v1/processing-runs/{run_id}
- POST /api/v1/document-versions/{version_id}/set-current
- DELETE /api/v1/document-versions/{version_id}

Загрузка может использовать multipart/form-data либо двухшаговый upload session. Сервер проверяет фактический тип содержимого, размер, checksum, имя и права. Клиентское расширение файла не является достаточной проверкой формата.

#### Реализованный контракт загрузки и скачивания оригиналов

Текущая реализация использует tenant-scoped URL, привязанный к существующему Document:

- POST `/api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions`
- GET `/api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/content`

Upload принимает `multipart/form-data` с полем `file` и обязательным заголовком `Idempotency-Key` (8–128 символов ASCII из allowlist). Для первого успешного приёма возвращается HTTP 201 и метаданные DocumentVersion; идентичный повтор с тем же ключом, документом, именем и байтами возвращает HTTP 200 с той же версией. Повторное использование ключа с иным содержимым или незавершённой операцией возвращает HTTP 409.

Разрешённые начальные форматы: PDF, DOCX, XLSX и PPTX. MIME определяется сервером по сигнатуре и структуре OOXML package; клиентский Content-Type не считается доверенным. Ограничение по умолчанию — 100 MiB. Проверка active tenant membership и project role выполняется на backend. Viewer/reviewer не могут загружать документы; чтение оригинала доступно участникам проекта с read permission.

Download перед началом передачи открывает файл, проверяет SHA-256 и размер по зарегистрированной DocumentVersion и только затем отдаёт поток. При отсутствии оригинала или несовпадении checksum возвращается HTTP 503; файл не выдаётся.

UploadOperation хранит durable state machine и idempotency key. После сбоя состояния receiving/quarantined/publishing восстанавливаются tenant-scoped командой `python -m app.storage.reconcile --tenant-id <TENANT_UUID>`. PostgreSQL и файловая система не считаются одной транзакцией; согласование реализовано через отдельные фиксируемые фазы и reconciliation.

Подробности: [DOCUMENT_UPLOAD_AND_RECOVERY.md](DOCUMENT_UPLOAD_AND_RECOVERY.md).

### Поиск и знания
- POST /api/v1/projects/{project_id}/search
- GET /api/v1/projects/{project_id}/knowledge
- GET /api/v1/knowledge-items/{item_id}
- GET /api/v1/source-fragments/{fragment_id}
- GET /api/v1/source-fragments/{fragment_id}/preview

### Диалоги
- POST /api/v1/projects/{project_id}/conversations
- GET /api/v1/conversations/{conversation_id}
- POST /api/v1/conversations/{conversation_id}/messages
- GET /api/v1/conversations/{conversation_id}/messages
- POST /api/v1/conversations/{conversation_id}/stream — SSE response stream.

### Память и Skills
- GET /api/v1/memory
- POST /api/v1/memory
- PATCH /api/v1/memory/{memory_id}
- DELETE /api/v1/memory/{memory_id}
- GET /api/v1/skills
- GET /api/v1/skills/{skill_id}/versions
- POST /api/v1/skills/{skill_id}/execute

### Инженерные проверки
- POST /api/v1/projects/{project_id}/reviews
- GET /api/v1/reviews/{review_id}
- GET /api/v1/reviews/{review_id}/findings
- PATCH /api/v1/findings/{finding_id}
- GET /api/v1/findings/{finding_id}/evidence

### Администрирование
- GET /api/v1/admin/providers
- GET /api/v1/admin/jobs
- GET /api/v1/admin/audit
- GET/PATCH /api/v1/admin/policies

Маршруты — целевой контракт, а не заявление, что все endpoints уже реализованы.

## 4. Примеры контрактов

### Создание проекта
Request:
```json
{
  "name": "Жилой дом",
  "code": "ЖД-01",
  "description": "Проектная документация",
  "metadata": {"stage": "П"}
}
```
Response:
```json
{
  "id": "uuid",
  "name": "Жилой дом",
  "status": "active",
  "created_at": "2026-11-01T10:00:00Z"
}
```

### Запуск обработки
Request:
```json
{
  "pipeline": "default-document-ingestion",
  "options": {"ocr_fallback": true}
}
```
Response HTTP 202:
```json
{
  "run_id": "uuid",
  "status": "queued",
  "status_url": "/api/v1/processing-runs/uuid"
}
```

### Поиск по проекту
Request:
```json
{
  "query": "Какова отметка чистого пола первого этажа?",
  "filters": {
    "document_types": ["АР"],
    "version_state": "current"
  },
  "top_k": 10
}
```
Response:
```json
{
  "results": [
    {
      "fragment_id": "uuid",
      "document_version_id": "uuid",
      "excerpt": "...",
      "score": 0.91,
      "locator": {"page": 12, "bbox": [10, 20, 300, 80]}
    }
  ]
}
```
Score — техническая характеристика retrieval, не вероятность истинности.

### Сообщение диалога
Request:
```json
{
  "content": "Сопоставь отметки в АР и КР",
  "mode": "document_assistant",
  "stream": true
}
```
Поток SSE может содержать события meta, token, citation, warning, done и error. Каждое citation ссылается на fragment_id и version_id; UI получает безопасный preview через API.

## 5. Контракт ответа с доказательствами

Ответ должен отделять:
- answer — текст ответа;
- claims — атомарные утверждения;
- citations — ссылки на источники;
- limitations — пробелы, неоднозначности и ограничения;
- actions — разрешённые следующие действия.

У каждого citation есть fragment_id, document_version_id, document title, locator и excerpt. Backend проверяет доступ к каждому источнику до выдачи. LLM не может самостоятельно создавать действительные идентификаторы цитат: они выбираются из retrieval context.

## 6. Аутентификация и авторизация

На прототипе допустима локальная development-auth схема. До многопользовательского использования требуется полноценная аутентификация, безопасное хранение паролей/секретов, управление сессиями и восстановление доступа.

Авторизация выполняется сервером на каждом ресурсе. Нельзя считать workspace ID, скрытый UI-раздел или случайный UUID доказательством доступа. API keys внешних компонентов хранятся только на backend.

## 7. Интеграция AnythingLLM

Предпочтительная схема: UI обращается к собственному backend; backend вызывает AnythingLLM только через изолированный adapter, если прототип подтвердит необходимость. Если AnythingLLM требует прямого подключения браузера к его API, API key не передаётся в клиентский код. Данные синхронизируются по явному контракту, а источником истины остаётся доменная БД Personal Expert AI.

До выбора интеграционного режима проверить API lifecycle, права workspace, citations, удаление, обработку файлов и сетевые обращения.

## 8. Фоновые задания и повторяемость

Длительные ingestion/review задачи возвращают 202 Accepted и run_id. Состояние задания хранит этап, процент (если измерим), warnings, errors, timestamps, correlation_id и manifest версий. Повторный запрос с тем же Idempotency-Key не создаёт второй запуск. Retry ограничен и безопасен для каждого этапа.

## 9. Версионирование и совместимость

Изменения breaking contract требуют новой major версии API или согласованного периода миграции. OpenAPI schema тестируется в CI. Contract tests должны подтверждать соответствие backend и UI adapter. Нельзя связывать API с внутренними форматами ответов конкретной LLM.


## Реализованные read endpoints для Bionic UI (2026-11-03)

Следующие маршруты реализованы в `app/api/routes.py` и требуют Bearer JWT, tenant из JWT и активное членство/доступ к проекту:

- GET `/api/v1/tenants/{tenant_id}/projects`
- GET `/api/v1/tenants/{tenant_id}/projects/{project_id}/documents`
- GET `/api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions`
- GET `/api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}`
- GET `/api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/source-fragments`
- GET `/api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/source-fragments/{fragment_id}`
- GET `/api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/artifacts`
- GET `/api/v1/tenants/{tenant_id}/projects/{project_id}/documents/{document_id}/versions/{version_id}/artifacts/{artifact_id}/content`
- GET `/api/v1/tenants/{tenant_id}/projects/{project_id}/knowledge`

Source-fragment responses return a bounded excerpt (up to 4,000 characters), typed locator and extraction provenance. Internal storage keys and filesystem paths are recursively removed from locators. Rendered-page content is restricted to registered `rendered_page` artifacts with PNG/JPEG/WebP media types and is streamed only after the requested tenant/project/document/version relationship has been checked and the stored bytes pass SHA-256 and size verification. Responses are private/no-store and set `X-Content-Type-Options: nosniff`.

The page-artifact endpoint intentionally uses an opaque artifact UUID rather than accepting a storage key or filesystem path from the browser. The UI first lists the rendered-page artifact metadata, then requests the selected artifact content.

**Not implemented yet:** Reviews/Findings/Evidence domain resources and their routes. The current ORM schema has KnowledgeItem, KnowledgeAssertion and SourceFragment, but no Review or Finding entities. Do not present Bionic Reviews as connected until a review domain model, migration, service authorization, API schemas/routes and tenant-isolation tests exist.

**Bionic authentication bridge is also pending.** Personal Expert AI validates trusted HS256 JWTs issued by an identity provider and maps `sub` to its own User UUID plus `tenant_id`. Bionic's existing login/session must not be treated as equivalent without an explicit trusted identity mapping. Do not place a backend service token or JWT signing secret in browser code, local storage, static Pages assets or a public repository.
