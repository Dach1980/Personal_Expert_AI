# Security Model — безопасность, права и локальность

- Статус: базовая модель угроз и требований, версия 1.0
- Дата: 2026-11-01

## 1. Цели

Защитить конфиденциальность проектных документов, изолировать пользователей и проекты, сохранить целостность оригиналов и результатов, ограничить LLM/tools и обеспечить проверяемую локальность.

## 2. Защищаемые активы и угрозы

Активы: оригиналы, OCR и previews, БД, embeddings, память, история, результаты проверок, ключи, логи и backups.

Угрозы:
- межпроектный/межтенантный доступ через IDOR или ошибку фильтра;
- утечка через UI, API key, logs, telemetry, crash dump или внешнюю модель;
- prompt injection в PDF, OCR, таблицах, изображениях и tool output;
- эксплуатация parser или исчерпание ресурсов вредоносным файлом;
- SSRF и произвольный доступ инструмента к локальной сети/файлам;
- подмена документа, индекса, citation или результата;
- небезопасная конфигурация Docker/runtime;
- компрометация backup и временных файлов.

## 3. Границы доверия

Browser/UI — недоверенный клиент. Backend API — точка принудительного контроля доступа. PostgreSQL и object storage доверяются только при корректной конфигурации. LLM не является механизмом авторизации. Документы, OCR, извлечённый текст и tool output — недоверенные данные. Skills и инструменты получают минимальные привилегии.

## 4. Идентификация и авторизация

Каждый запрос имеет authenticated principal и tenant context. Для каждого объекта проверяются membership, project role и право на действие. UUID не является доказательством доступа. Рекомендуемые роли: tenant_admin, project_manager, engineer, reviewer, viewer.

Разделить разрешения read, upload, process, delete, manage_members, run_review, approve_finding, manage_skill и administer. Сервисные аккаунты имеют отдельные минимальные scopes. PostgreSQL RLS может быть дополнительным уровнем защиты, но не заменяет application-level checks.

## 5. Секреты и файлы

Секреты не хранятся в Git, исходниках, образах или UI. API keys моделей и AnythingLLM остаются на backend. Файлы хранятся вне web root по непрозрачным storage keys. Оригиналы неизменяемы, checksum проверяется при переносе/чтении. Previews и временные файлы наследуют ACL оригинала. Логи не содержат полный текст документов и секреты без специальной необходимости.

## 6. Безопасная обработка файлов

Использовать allowlist форматов, MIME-проверку по содержимому, лимиты размера и распаковки, защиту от zip bombs/path traversal/symlink abuse, sandbox парсеров, timeout и CPU/memory limits. Не исполнять макросы и embedded scripts. Ошибка парсера не должна влиять на API и другие задания.

## 7. Prompt injection и LLM

Содержимое документа передаётся только как недоверенные данные, не как инструкции управления. System policy отделена от retrieved content. LLM не получает credentials, unrestricted shell или filesystem access. Все tool calls проверяются backend по allowlist, schema, permissions и scope. Цитаты валидируются по реально переданным SourceFragments. Критические операции требуют подтверждения человека.

## 8. Local-only политика

Local-only — проверяемый режим. По умолчанию отключены cloud LLM/embeddings, внешние OCR/vision API, внешние MCP, web search, telemetry/analytics и автоматические сетевые обновления. Разрешены только явно настроенные локальные endpoints.

Для подтверждения локальности проверить DNS, proxy, container egress, browser network calls, telemetry, crash reporting, model downloads и CDN. Загрузка моделей из сети — отдельная административная операция до перехода в offline режим. При отключённом внешнем доступе должны работать загрузка, индексация, поиск и ответы; попытки внешнего соединения блокируются и/или регистрируются.

## 9. Docker и инфраструктура

Не использовать privileged containers без документированной необходимости. Уменьшать Linux capabilities, ограничивать mounts и ресурсы, применять read-only filesystem где возможно. Не монтировать весь host filesystem. Разделять сети UI, backend, DB и runtime. Проверить необходимость SYS_ADMIN у AnythingLLM в выбранном режиме и найти минимально привилегированную конфигурацию. Фиксировать версии и image digests.

## 10. Аудит

Аудировать login/logout, доступ к документам, upload/download/delete, смену прав, export, вызовы инструментов, Skills/reviews, изменения памяти и администрирование. AuditEvent включает actor, action, target, timestamp, request_id и outcome. Не записывать секреты и полные документы. Логи защищаются от изменения и имеют retention policy.

## 11. Backup и удаление

Backups шифруются, ограничиваются по доступу и регулярно проверяются восстановлением. Удаление охватывает originals, artifacts, indices, caches и backup expiration. Удаление из основной БД не означает мгновенное исчезновение из резервных копий; администратор должен видеть фактическое окно окончательного удаления.

## 12. Обязательные проверки до multi-user

- IDOR и cross-tenant API tests.
- Изоляция retrieval/vector search/cache/queue/logs.
- Prompt injection corpus.
- SSRF и Tool Gateway tests.
- Upload/parser fuzzing и resource exhaustion.
- Secret/dependency/container scanning.
- Network egress tests для local-only.
- Backup/restore и deletion verification.
- Проверки admin roles, session expiry, CSRF и rate limits.

Single-user prototype не считается безопасным multi-user продуктом до threat-model review и прохождения этих тестов.


## 13. Реализуемый механизм tenant isolation (2026-11-01)

В миграции `0002_tenant_isolation` включены PostgreSQL RLS policies для таблиц с `tenant_id` и для `tenants.id`. Policies используют transaction-local параметр `app.tenant_id`. Включён `FORCE ROW LEVEL SECURITY`, поэтому владелец таблицы также подчиняется policy; superuser и роли с `BYPASSRLS` по-прежнему обходят RLS.

Backend устанавливает контекст через `set_config('app.tenant_id', ..., true)` в текущей транзакции. Значение должно поступать только из проверенного principal, а не из тела запроса. Сессия запроса оборачивается в транзакцию: успешный запрос фиксируется, исключение приводит к rollback. Transaction-local context сбрасывается при завершении транзакции.

HTTP API использует подписанный JWT от доверенного identity provider. Проверяются подпись HS256, issuer, audience, exp, iat, sub и tenant_id. Обязательные настройки:
- `JWT_SECRET` — секрет не короче 32 символов;
- `JWT_ISSUER` — ожидаемый issuer;
- `JWT_AUDIENCE` — ожидаемая audience.

Токен должен содержать UUID пользователя в `sub` и UUID tenant в `tenant_id`. Приложение не выдаёт токены и не реализует регистрацию/пароли: подключение и управление identity provider остаётся отдельной эксплуатационной настройкой. Без JWT-конфигурации защищённые endpoint возвращают 503; без действительного bearer token доступ запрещён.

Runtime DB role обязана быть отдельной ролью PostgreSQL без `SUPERUSER`, без `BYPASSRLS` и не должна владеть таблицами. Миграции выполняются отдельной DDL-ролью. Использование владельца таблиц или superuser как runtime connection разрушает ожидаемую границу RLS.

CI проверяет RLS под отдельной ролью `app_runtime`, не являющейся владельцем таблиц и не имеющей `BYPASSRLS`. Проверки PostgreSQL должны проходить до использования схемы в multi-user окружении.
