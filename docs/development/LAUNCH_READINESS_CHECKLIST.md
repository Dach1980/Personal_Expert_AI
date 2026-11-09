# Launch Readiness Checklist — Personal Expert AI

- Дата обновления: 2026-11-09
- Основной репозиторий: [Dach1980/Personal_Expert_AI](https://github.com/Dach1980/Personal_Expert_AI)
- Рабочая ветка: `main`
- Зафиксированный HEAD перед созданием этого файла: `ecebf6343f6d55a54edc922fa699062ed37bb6c6`
- Связанные репозитории:
  - [Bionic fork](https://github.com/Dach1980/bionic-personal-expert-ai)
  - [Public Web](https://github.com/Dach1980/Personal_Expert_AI_Web)
- Публичный сайт: https://dach1980.github.io/Personal_Expert_AI_Web/

> Правило приёмки: `DONE` ставится только при наличии проверяемого результата для указанного окружения и SHA. Наличие кода, документации, mock-теста или старого CI run не доказывает готовность runtime. Если проверка не выполнялась, используем `NOT VERIFIED`, а не предполагаем успех.

## 1. Статусы

| Статус | Значение |
|---|---|
| `DONE` | Проверка выполнена; ссылка на evidence и дата указаны |
| `PARTIAL` | Часть реализации или проверки подтверждена |
| `OPEN` | Работа или проверка ещё не выполнена |
| `BLOCKED` | Есть конкретный блокирующий дефект/зависимость |
| `NOT VERIFIED` | Недостаточно актуальных runtime/CI доказательств |

## 2. Сводка готовности

На 2026-11-09 инфраструктура локальной разработки восстановлена и основные сервисы доступны. Это **не является разрешением на публичный production launch**: браузерный login, защищённый backend endpoint, изоляция данных и полный пользовательский сценарий ещё не приняты.

| Область | Статус | Последнее подтверждение |
|---|---|---|
| PEA backend и API scaffold | PARTIAL | 2026-11-09: локальный `/health` OK; OpenAPI содержит 35 paths |
| PostgreSQL PEA | PARTIAL | 2026-11-09: контейнер healthy / pg_isready принимает соединения; SQL-запрос через PEA ещё не проверен |
| RLS и tenant isolation | PARTIAL | Миграции/политики и исторические тесты существуют; актуальная локальная adversarial-проверка не выполнена |
| Keycloak / OIDC discovery | DONE (локальный smoke test) | 2026-11-09: realm `stack-app` discovery HTTP 200 |
| Kubernetes / k3d | DONE (локальный smoke test) | 2026-11-09: кластер `k3d-bionic`, оба узла Ready |
| Public Web hosting | PARTIAL | Исторический Pages deploy success; текущий браузерный E2E не проверен |
| Browser authentication | OPEN | Реальный PKCE login/logout/refresh не принят |
| Protected backend gateway | OPEN | Публичный HTTPS BFF/gateway и доверенная передача identity не приняты |
| Bionic PEA retrieval | BLOCKED | Найдены контрактное несовпадение и риск обхода проверки цитат; E2E не выполнен |
| Document upload → processing → evidence | PARTIAL | Компоненты/API существуют; live user flow не принят |
| Local LLM runtime | PARTIAL | Provider abstraction есть; полный runtime smoke test не принят |
| MVP launch | BLOCKED | Нет подтверждения полного безопасного пользовательского сценария |

## 3. P0 — обязательные ворота MVP

### 3.1 Backend и PostgreSQL

| ID | Проверка / результат | Статус | Дата проверки | Evidence / тест |
|---|---|---|---|---|
| PEA-DB-01 | PostgreSQL 16 запущен и принимает соединения | DONE | 2026-11-09 | `docker exec personal-expert-postgres pg_isready` → accepting connections |
| PEA-DB-02 | PEA выполняет реальный SQL-запрос через собственный SQLAlchemy engine/session | OPEN | — | Выполнить безопасный read-only запрос через конфигурацию приложения; не выводить DSN/секреты |
| PEA-DB-03 | Alembic head соответствует ожидаемой схеме БД | OPEN | — | `alembic current`, `alembic check`; зафиксировать вывод без credentials |
| PEA-DB-04 | Upgrade → schema parity → downgrade → re-upgrade на PostgreSQL 16 | PARTIAL | Исторически | Исторические CI: [41760466319](https://github.com/Dach1980/Personal_Expert_AI/actions/runs/41760466319), [41813394892](https://github.com/Dach1980/Personal_Expert_AI/actions/runs/41813394892). Не считать доказательством текущего HEAD |
| PEA-DB-05 | Runtime DB role не SUPERUSER/BYPASSRLS; права минимальны | OPEN | — | Проверить role attributes и grants в целевом runtime |
| PEA-DB-06 | Backup и restore проверены на отдельном тестовом наборе | OPEN | — | Зафиксировать backup artifact, restore log и проверку данных |

### 3.2 RLS и авторизация PEA

| ID | Проверка / результат | Статус | Дата проверки | Evidence / тест |
|---|---|---|---|---|
| PEA-SEC-01 | RLS включён и принудительно применяется на защищённых таблицах | PARTIAL | Статический аудит | Миграции и политики; нужен PostgreSQL runtime test |
| PEA-SEC-02 | Пользователь tenant A не читает tenant B | PARTIAL | Исторически | Проверить/расширить adversarial tests в `tests/`; исторические CI run выше |
| PEA-SEC-03 | Нельзя получить чужой project/document подменой ID | PARTIAL | Исторически | Проверить API tests для cross-project access и composite FK |
| PEA-SEC-04 | Неактивные user/tenant/membership и отозванная identity дают отказ | OPEN | — | Добавить/выполнить negative authz lifecycle tests |
| PEA-SEC-05 | Bionic workload не может изменять project binding | OPEN | — | PostgreSQL integration test для workload RLS |
| PEA-SEC-06 | Owner не читает чужие delegation grants; workload видит только допустимые grants | OPEN | — | PostgreSQL integration tests для grants/bindings |
| PEA-SEC-07 | Контекст workload/user/tenant не позволяет читать источники другого tenant | OPEN | — | Проверить transaction-local context и RLS на реальном PostgreSQL |

### 3.3 Keycloak и browser login

| ID | Проверка / результат | Статус | Дата проверки | Evidence / тест |
|---|---|---|---|---|
| PEA-OIDC-01 | Локальный Keycloak доступен; realm discovery отвечает | DONE | 2026-11-09 | `http://localhost:30000/realms/stack-app/.well-known/openid-configuration` → HTTP 200 |
| PEA-OIDC-02 | PEA валидирует RS256/JWKS, issuer, audience и временные claims | PARTIAL | По коду/тестам | `app/api/auth.py`, `tests/api/test_keycloak_auth.py`; требуется актуальный runtime test |
| PEA-OIDC-03 | Реальный браузерный Authorization Code + PKCE login/logout | OPEN | — | Web OIDC client и реальный Keycloak redirect flow |
| PEA-OIDC-04 | Refresh/expiry/revocation и повторная авторизация работают | OPEN | — | Browser E2E; проверить отсутствие хранения постоянных секретов в bundle |
| PEA-OIDC-05 | Два пользователя не могут получить доступ к чужим tenant/project | OPEN | — | Два тестовых пользователя и negative E2E |
| PEA-OIDC-06 | Доверенный gateway удаляет spoofed forwarded-token header и передаёт проверенный token | OPEN | — | Gateway configuration + spoofing test |
| PEA-OIDC-07 | Dev realm в Bionic config согласован с локальным realm `stack-app` | BLOCKED | 2026-11-09 | В ранее проверенном `infra-as-code/stack.yaml` встречался `bionic-gpt`; сверить актуальный файл и все issuer/URL перед изменением |

### 3.4 Публичный Web и защищённый backend

| ID | Проверка / результат | Статус | Дата проверки | Evidence / тест |
|---|---|---|---|---|
| WEB-01 | GitHub Pages публикует статический frontend | PARTIAL | Исторически | [Pages deployment history](https://github.com/Dach1980/Personal_Expert_AI_Web/actions); проверить последний run и текущий сайт |
| WEB-02 | Страницы и прямые SPA routes открываются после refresh | OPEN | — | Browser test на опубликованном URL |
| WEB-03 | Визуальная адаптивность и branding проверены | PARTIAL | Исторически | Нужна финальная desktop/mobile browser acceptance |
| WEB-04 | Реальный HTTPS backend/BFF endpoint доступен с сайта | OPEN | — | Зафиксировать домен, TLS, ingress/gateway, health check |
| WEB-05 | CORS allowlist ограничен origin публичного сайта | OPEN | — | Проверить gateway config и preflight/negative origin tests |
| WEB-06 | Браузер не обращается напрямую к PostgreSQL, LM Studio или внутренним Bionic/PEA портам | OPEN | — | Network capture / browser devtools acceptance |
| WEB-07 | В frontend bundle и публичных файлах отсутствуют secrets и постоянные tokens | OPEN | — | Secret scan и проверка production bundle |

### 3.5 Документный сценарий MVP

| ID | Проверка / результат | Статус | Дата проверки | Evidence / тест |
|---|---|---|---|---|
| DOC-01 | Пользователь видит только разрешённые tenant/project | OPEN | — | Browser E2E + API negative tests |
| DOC-02 | Загрузка документа через защищённый backend | PARTIAL | Код существует | Проверить реальный PDF/DOCX тестовый файл |
| DOC-03 | Создаётся immutable DocumentVersion и корректный hash | PARTIAL | Код существует | Проверить storage и DB после upload |
| DOC-04 | ProcessingRun выполняется worker-ом до terminal status | OPEN | — | Запустить worker и проверить статусы/retry |
| DOC-05 | SourceFragment содержит locator, provenance и content hash | PARTIAL | Код существует | Проверить фактический результат extraction |
| DOC-06 | UI отображает processing status, версии и ошибки | OPEN | — | Browser E2E с реальным документом |
| DOC-07 | Пользователь может открыть исходный evidence/fragment | OPEN | — | Browser E2E; сверить файл, версию и страницу/лист |

### 3.6 Chat и local LLM

| ID | Проверка / результат | Статус | Дата проверки | Evidence / тест |
|---|---|---|---|---|
| LLM-01 | LM Studio provider abstraction и mock tests существуют | PARTIAL | По коду/историческому аудиту | `app/llm/lm_studio.py`, `tests/unit/test_lm_studio_provider.py` |
| LLM-02 | Реальный локальный chat completion на выбранной модели | OPEN | — | Runtime smoke test; проверить русскоязычный ответ и точный model id |
| LLM-03 | Streaming, cancellation, timeout и ошибки провайдера | OPEN | — | Provider/API integration tests |
| LLM-04 | Cloud fallback выключен; незапланированные внешние запросы отсутствуют | OPEN | — | Config + network capture |
| CHAT-01 | Пользователь создаёт conversation и видит историю | PARTIAL | API/UI код существует | Browser E2E на реальном backend |
| CHAT-02 | SSE streaming стабилен и корректно завершается/отменяется | OPEN | — | End-to-end browser test |
| CHAT-03 | Ответ по документу содержит проверяемые ссылки на source fragments | BLOCKED | 2026-11-09 | Требуется scoped retrieval и citation validation |

## 4. P0/P1 — Bionic ↔ PEA integration

| ID | Проверка / результат | Статус | Дата проверки | Evidence / тест |
|---|---|---|---|---|
| BIO-01 | Server-side `PeaRetrievalContext`; identifiers/grant не передаются моделью | PARTIAL | Статический аудит | `crates/tool-runtime/pea_retrieval.rs`, `crates/cron/src/main.rs` |
| BIO-02 | Контракт retrieval принимает `owner_subject`, который отправляет Bionic | BLOCKED | 2026-11-09 | PEA `app/api/delegation.py`: `BionicRetrievalRequest` не содержит поле при strict validation; handler обращается к `payload.owner_subject`. Тест: `tests/api/test_bionic_delegation_contract.py` |
| BIO-03 | Citation validation применяется и при наличии `tool_calls` | BLOCKED | 2026-11-09 | Риск в `crates/agent-harness/result_sink.rs`: ветка проверки зависит от отсутствия tool calls. Добавить regression test |
| BIO-04 | PEA SearchResponse и Bionic parser совпадают по полям/типам | PARTIAL | Статический аудит | `app/api/delegation.py`, `crates/tool-runtime/pea_retrieval.rs`; добавить shared fixture/contract tests |
| BIO-05 | Grant привязан к owner, project, Bionic task, instance и сроку действия | PARTIAL | По коду | `app/api/delegation.py`; нужны positive/negative endpoint tests |
| BIO-06 | Grant revoke работает; истёкший/отозванный grant не принимается | OPEN | — | API tests issue/search/revoke/expiry |
| BIO-07 | Workload JWT реально проходит Keycloak → Bionic → PEA | PARTIAL | 2026-11-09 | Ранее локально проверялись issuer/aud/azp/scope и RS256; полный HTTP E2E отсутствует |
| BIO-08 | Fork-specific Bionic image действительно собран из fork commit и запущен | OPEN | — | Ранее обнаружен upstream image reference в Stack/Compose; проверить актуальные manifests, image digest и source SHA |
| BIO-09 | Pod Bionic достигает PEA API по private route | OPEN | — | Pod-to-service/network test; не подменять проверкой host-to-host |
| BIO-10 | Scheduled task выполняет scoped search, grounded response и revoke | OPEN | — | End-to-end scheduled task с тестовым документом |
| BIO-11 | Bionic Rust tests/build проходят на текущем HEAD | NOT VERIFIED | — | Зафиксировать Actions run URL, exact HEAD SHA, conclusion и jobs |

## 5. P1/P2 — после MVP

| ID | Проверка / результат | Статус | Evidence / тест |
|---|---|---|---|
| OPS-01 | Мониторинг backend/worker/Keycloak/DB и error alerts | OPEN | Deployment/observability checks |
| OPS-02 | Backup/restore документов, БД и конфигурации | OPEN | Restore drill |
| OPS-03 | Rate limits, upload limits и resource quotas | PARTIAL | Upload body limit есть; проверить весь публичный периметр |
| OPS-04 | Security review: IDOR, XSS, CSRF, CORS, token leakage, prompt injection | OPEN | Security test report |
| OPS-05 | Audit trail для критических действий и delegation | PARTIAL | Проверить coverage и retention |
| OPS-06 | Runbook развёртывания, обновления и rollback | OPEN | Документированный rehearsal |
| OPS-07 | OCR accuracy benchmark на обезличенном контрольном наборе | OPEN | Ground-truth benchmark |
| OPS-08 | Hybrid retrieval, reranker, evidence quality и grounded-answer benchmark | OPEN | Retrieval evaluation |
| OPS-09 | Memory/Skills и инженерные проверки | OPEN | Отдельные acceptance suites |

## 6. Проверки, выполненные 2026-11-09 — локальная инфраструктура

Ниже перечислены только реально полученные результаты текущего сеанса:

| Проверка | Результат | Подтверждение |
|---|---|---|
| Docker Engine | DONE | Docker Server 29.9.2 |
| k3d cluster | DONE | `k3d-bionic`, 1 server / 1 agent |
| Kubernetes nodes | DONE | Оба узла `Ready`, Kubernetes v1.35.5+k3s1 |
| Keycloak Pod | DONE | `keycloak-0` Running, Ready 1/1 |
| Keycloak DB Pod | DONE | Running, Ready 1/1 |
| Realm OIDC discovery | DONE | issuer `http://localhost:30000/realms/stack-app`, HTTP 200 |
| PEA PostgreSQL container | DONE | `pg_isready` → accepting connections |
| PEA API health | DONE | `GET http://127.0.0.1:8000/health` → `{"status":"ok","service":"personal-expert-ai"}` |
| PEA OpenAPI | DONE | title Personal Expert AI, version 0.1.0, 35 paths, delegation path present |
| PEA SQLAlchemy query | OPEN | Не выполнялась |
| PEA ↔ Keycloak authenticated request | OPEN | Не выполнялась |
| Bionic pod → PEA request | OPEN | Не выполнялась |

**Runtime caveat:** перед завершением локального сеанса PEA Uvicorn следует корректно остановить через `Ctrl+C`. Docker Desktop/k3d можно оставить остановленными; кластер не удалять и не пересоздавать. Не запускать `just dev-init` без проверки: известный Bionic helper ранее содержал `k3d cluster delete k3d-bionic`.

## 7. План закрытия MVP

1. Реальный SQLAlchemy read-only запрос и Alembic state.
2. PostgreSQL RLS tests для tenant, owner, workload, grants и binding.
3. Исправить `BionicRetrievalRequest.owner_subject`; добавить contract и endpoint tests.
4. Исправить citation validation при `tool_calls`; добавить regression tests.
5. Сверить `stack-app` / `bionic-gpt`, realm URLs, worker client, audience и scope.
6. Зафиксировать актуальные CI run + exact SHA для PEA, Bionic и Web.
7. Проверить fork-specific Bionic image provenance и deployment manifest.
8. Поднять доверенный HTTPS gateway/BFF; проверить spoofed headers, CORS и private routing.
9. Провести реальный PKCE browser login/logout/refresh.
10. Пройти пользовательский MVP: login → project → upload → processing → chat → source evidence.
11. Провести два-user cross-tenant/project negative E2E.
12. Только после прохождения всех P0 пунктов принять решение о первом публичном запуске.

## 8. Журнал обновлений

| Дата | Изменение | Проверенное основание |
|---|---|---|
| 2026-11-09 | Создан исходный Launch Readiness Checklist | PEA HEAD `ecebf6343f6d55a54edc922fa699062ed37bb6c6`; локальные проверки инфраструктуры в сеансе 2026-11-09 |

При каждом обновлении добавлять дату, точный commit SHA, URL workflow/E2E evidence и конкретный результат. Не заменять старые исторические evidence новыми статусами без повторной проверки.
