# Сверка трёх репозиториев Personal Expert AI

Дата сверки: 2026-11-04  
Ветка: `main` во всех трёх репозиториях.  
Метод: GitHub commit history, содержимое актуальных файлов, API contracts, документация интеграции и доступные commit status checks.

## 1. Снимок HEAD

| Репозиторий | HEAD на момент сверки | Последний commit | Вывод |
|---|---|---|---|
| [Personal_Expert_AI](https://github.com/Dach1980/Personal_Expert_AI) | `a8202a74671b0da5b97fab71aa6a705a4b9ec16c` | docs(keycloak): add public PKCE client and membership provisioning steps | Backend/API и auth contract продвинулись; PEA остаётся владельцем доменных данных и ACL |
| [bionic-personal-expert-ai](https://github.com/Dach1980/bionic-personal-expert-ai) | `d0966984957a39a5efe5d407279cfb061424da05` | docs(adapter): remove undocumented document detail route | Server-side Adapter расширен; требуется подтверждение актуального Rust CI и live trust boundary |
| [Personal_Expert_AI_Web](https://github.com/Dach1980/Personal_Expert_AI_Web) | `066f30a83d2c9af11dda1fa46a4fb359e39d3b38` | chore(web): release document workspace client 0.4.0 | SPA 0.4.0 содержит auth/chat/document workspace integration; runtime E2E не подтверждён |

Все три репозитория имеют только ветку `main` в доступном списке веток.

## 2. Personal Expert AI — backend

Подтверждено по HEAD, README, ROADMAP, API и Keycloak документации:

- PostgreSQL 16, SQLAlchemy/Alembic, composite FK, RLS и tenant context.
- External identity mapping `(issuer, subject)`, RS256/JWKS и membership checks.
- Upload/download lifecycle, processing queue, extraction adapters и SourceFragment.
- Conversation/message API и локальный LM Studio provider abstraction.
- Отдельный public Keycloak client `pea-web` с Authorization Code + PKCE S256 описан в bootstrap-инструкции.
- Модельный endpoint требует явно заданный `PEA_LLM_MODEL`; cloud fallback не предусмотрен.

Историческое CI-доказательство, уже указанное в основном аудите: PostgreSQL 16 run [41760466319](https://github.com/Dach1980/Personal_Expert_AI/actions/runs/41760466319) — migration upgrade/check/downgrade/re-upgrade, ORM/schema checks, RLS integration tests, pytest и Ruff завершились успешно. Этот run не является доказательством прохождения CI на текущем HEAD `a8202a7`.

Открытые проверки:
- текущий runtime DB role, TLS/secrets и backup/restore;
- отрицательные OIDC/membership lifecycle сценарии;
- фактическая доступность LM Studio и streaming на целевой модели;
- live E2E PEA ↔ Bionic ↔ browser.

## 3. Bionic fork — UI/runtime и server-side Adapter

Подтверждено по HEAD и `docs/integration/PEA_API_ADAPTER.md`:

- JWT verification через RS256/JWKS, issuer, audience и time claims.
- Фиксированный server-side Adapter `/api/pea`, без произвольного upstream URL.
- PEA независимо валидирует forwarded user token и проверяет identity/membership.
- Описаны session/projects/conversations/messages/SSE, documents/versions, processing runs, source fragments, artifacts, reviews/findings/evidence и knowledge.
- Multipart upload ограничен 100 MiB, поддерживается idempotency key.
- В документации явно указано: Agent Runtime пока не выполняет retrieval по PEA SourceFragments/KnowledgeItems. Нельзя считать ответы чата grounded по загруженным документам до появления scoped search tool и тестов.

Важное уточнение доверенной границы:
- Stack OIDC gateway должен выполнять login/session, удалять клиентский `X-Forwarded-Access-Token` и инжектировать проверенный токен по приватному каналу.
- Публичная Pages SPA также использует Authorization Code + PKCE и отправляет короткоживущий Bearer token на Bionic Adapter.
- Текущий документированный Adapter допускает Bearer и Stack-forwarded token; фактическая конфигурация ingress/gateway, CORS и сетевой доступ должны быть проверены в развернутой среде.
- Обычный Docker Compose сам по себе не является OIDC gateway.

В Keycloak integration документации записано историческое успешное выполнение последнего завершённого Bionic Rust/browser-assets workflow: 63 Rust tests, formatting, server compilation и web-assets build. Однако точные run URL и SHA, к которому относился этот результат, не указаны. Поэтому это историческое свидетельство, а не подтверждение CI для текущего HEAD `d096698`.

Открытые проверки:
- получить результат Rust tests/build для актуального HEAD и сохранить run URL + SHA;
- проверить JWT extractor и gateway spoofing/negative cases;
- проверить реальный Stack OIDC gateway и приватную связность Bionic → PEA;
- провести браузерный login и E2E по Adapter;
- не считать PEA document retrieval частью Agent Runtime до реализации отдельного scoped tool.

## 4. Personal Expert AI Web — публичный SPA

Подтверждено по HEAD, README, API contract и исходникам:

- React + TypeScript + Vite, версия 0.4.0.
- Вызовы API изолированы в `src/services/api/client.ts`.
- OIDC PKCE вынесен в отдельный модуль; access token передаётся как Bearer, browser fetch использует `credentials: omit`.
- UI загружает session/projects, conversation history и SSE chat.
- DocumentWorkspace содержит вызовы list/create document, upload immutable version, enqueue processing, versions, fragments, artifacts, reviews/findings/evidence.
- Существуют demo mode и synthetic/demo data; README предупреждает, что без реального backend/runtime они не являются рабочими пользовательскими данными.

Историческое CI-доказательство в основном аудите: GitHub Pages deployment run #51 от 2026-11-03 завершился success. Текущий deployment для HEAD `066f30a` отдельно не подтверждён.

Открытые проверки:
- фактический Keycloak login/logout, refresh/expiry и возврат после redirect;
- доступность опубликованной страницы и прямые SPA routes/refresh;
- загрузка документов и отображение processing status на live PEA;
- устойчивость SSE, отмена и повторное подключение;
- E2E ACL/IDOR, XSS, CORS и отсутствие утечки токенов.

## 5. Проверка CI на текущих HEAD — ограничение результата

Для трёх актуальных HEAD были запрошены commit combined statuses. GitHub connector вернул пустой список status contexts для каждого SHA. Доступный через него метод получения workflow runs для commit ограничен PR-triggered runs и не даёт общего списка последних push workflow runs.

Следовательно, на момент этой сверки:
- нельзя честно проставить `CI passed` для текущих HEAD;
- нельзя заключить, что CI отсутствует или упал;
- исторические успешные run из предыдущего аудита остаются историческими;
- перед переходом к runtime интеграции нужно открыть Actions и зафиксировать run URL, head SHA, conclusion и ключевые jobs для каждого репозитория.

## 6. Сводный статус

| Контрольная область | Статус | Основание |
|---|---|---|
| PEA backend / DB architecture | Реализовано; runtime gates открыты | Код, миграции, тесты и исторический PostgreSQL 16 CI |
| PEA conversation API / local provider | Код реализован; реальный inference не подтверждён | API/provider implementation и config contract |
| Bionic PEA Adapter | Код и маршруты документированы; сборка текущего HEAD не подтверждена | HEAD и Adapter contract |
| Bionic Agent Runtime document retrieval | Не реализовано | Adapter document прямо фиксирует отсутствие scoped search tool |
| Public Web auth/chat/document client | Интеграционный код присутствует; live login не подтверждён | React API client, OIDC module, DocumentWorkspace |
| Keycloak realm provisioning | Скрипт и инструкции готовы; применение к живому realm не подтверждено | PEA bootstrap documentation |
| Trusted gateway | Требует runtime-проверки | Security contract и deployment note |
| Сквозной сценарий | Не подтверждён | Нет доказательства live E2E |

## 7. Следующая задача и критерии приёмки

**Следующая задача: закрыть CI gate трёх актуальных HEAD и затем провести runtime-проверку доверенной авторизации — не добавлять новые функции до получения этих результатов.**

Порядок:

1. В GitHub Actions открыть последний run для PEA, Bionic и Web; проверить, что каждый run относится к текущему HEAD или к последнему соответствующему code commit. Зафиксировать run URL, SHA, conclusion и jobs.
2. Для Bionic отдельно подтвердить `cargo fmt --check`, Rust tests, server compilation и web-assets build. При ошибках исправлять их в `main` и повторять проверки.
3. На локальном Stack развернуть/проверить общий Keycloak realm `bionic-gpt`, Bionic OIDC gateway и PEA API connection. Убедиться, что gateway удаляет spoofed `X-Forwarded-Access-Token` и передаёт фактический токен по приватной сети.
4. Применить `pea-web` client и `pea-api-context` scope; provision существующего PEA user через `(issuer, subject)` и явные tenant/project memberships.
5. Проверить реальный browser PKCE login → session → projects → logout, затем conversation create/history/SSE с локальной LM Studio моделью.

Критерии приёмки runtime-auth:
- неизвестный/неактивный subject, отключённый user/tenant и отсутствующее membership дают отказ;
- подмена tenant/project/conversation ID не открывает чужие данные;
- клиентский spoofed forwarded-token header не становится доверенной identity;
- Bionic и PEA независимо валидируют подпись, issuer, audience и временные claims;
- браузер не получает PEA credentials и не обращается к PEA/PostgreSQL/LM Studio напрямую.

После закрытия этого gate следующая отдельная задача — связать document workspace с реальным backend: upload → immutable version → processing run → SourceFragment/artifact preview, а затем добавить scoped PEA retrieval tool в Agent Runtime. Только после этого можно считать чат grounded по документам.

## 8. Правило статусов

Не переводить runtime/integration пункты в Done на основании документации, mock tests или наличия endpoint. Для каждого Done хранить ссылку на commit и успешный workflow/run либо E2E evidence. Все изменения продолжаются в `main`.


## 9. Документационные фиксации после сверки

В ходе самой сверки выполнены только документационные изменения (исходный runtime-код не менялся):

- PEA: создан этот отчёт, commit `fce48c14f5e8324eac4f30f4d0074261a65e8818`; затем основной аудит дополнен ссылкой и кратким статусом, commit `bf83eeacea097fb031f573647bdf6a735d0a5e09`.
- Web: README приведён в соответствие с кодом версии 0.4.0, отделены реализованные frontend-функции от live-проверок, commit `e54e4680625addd50601516964566cf83c0fdd72`.
- Bionic: изменений не выполнялось.

Эти коммиты не меняют приведённые выше исходные HEAD-снимки; они фиксируют результат аудита и исправляют устаревшее описание Web. CI для документационных коммитов отдельно не заявляется.


## 10. Выполнение контрольных шагов — результат 2026-11-04

### 10.1 CI и сборки

**Шаг 1 — подтверждение актуальных CI: выполнен.**

- PEA HEAD `a263e323017d219638737f2b71f228d3621259bf`: [run 41813394892](https://github.com/Dach1980/Personal_Expert_AI/actions/runs/41813394892) — success. Job `postgres-16`: upgrade, ORM/schema parity, downgrade, re-upgrade, full test suite и lint — все шаги success.
- Bionic code commit `1639300304e6b1b84050ee6b90f403b5c35e97c1`: [run 41764529468](https://github.com/Dach1980/bionic-personal-expert-ai/actions/runs/41764529468) — success. Jobs `rust` и `web-assets` — success; formatting, server compilation, web server tests, Agent Runtime auth/dialogue tests и browser assets build прошли. Текущий HEAD `d0966984957a39a5efe5d407279cfb061424da05` опережает этот code-tested SHA на четыре коммита. GitHub compare подтверждает, что изменения после tested SHA затрагивают только `docs/integration/PEA_API_ADAPTER.md`, `infra-as-code/.env.example` и `infra-as-code/docker-compose.yml`; Rust source не менялся. Изменения compose/env не подтверждены отдельным deployment test.
- Web HEAD `e54e4680625addd50601516964566cf83c0fdd72`: [run 41813379914](https://github.com/Dach1980/Personal_Expert_AI_Web/actions/runs/41813379914) — build и deploy jobs success. Pages deployment для предыдущего code commit `066f30a` также прошёл успешно. После последнего документационного уточнения Web README/API adapter docs изменены ещё одним docs-only commit; production build code не менялся.

**Шаг 2 — Rust tests и build Bionic: выполнен для текущего Rust source.** Повторные исправления Rust-кода по результатам последнего успешного CI не требуются. Deployment compose/env delta остаётся отдельной непроверенной конфигурацией.

### 10.2 Runtime gates

| № | Контрольный шаг | Результат | Причина / следующее действие |
|---|---|---|---|
| 3 | Trusted gateway Keycloak → Bionic → PEA | Не выполнен в runtime | Документы подтверждают Stack OIDC gateway contract; фактический кластер, strip/inject forwarded header, private routing и spoofing tests требуют доступа к локальному Stack |
| 4 | Реальный PKCE login в Pages SPA | Код готов; runtime не выполнен | OIDC client реализует Authorization Code + PKCE S256, state/nonce, memory-only tokens и refresh. Bootstrap script существует, но не запускался против живого realm; нужны admin credentials и redirect/origin allowlist |
| 5 | Смена пользователя, tenant, project | Частично готово; runtime не выполнен | PEA identity mapping и membership checks реализованы; тесты покрывают отрицательные сценарии. Текущая модель использует один `tenant_id` в access token; tenant switch UX/flow ещё не реализован. Нужны два тестовых пользователя и несколько tenant/project memberships |
| 6 | Conversation API + LM Studio | API/CI подтверждены; live inference не выполнен | PEA conversation API, Bionic Adapter и Web SSE client реализованы. Реальная доступность LM Studio, точный `PEA_LLM_MODEL`, потоковый ответ через всю цепочку и timeout/cancel нужно проверить на локальной машине |
| 7 | Upload документов и processing | Кодовые компоненты готовы; live processing не выполнен | PEA document/version/processing endpoints, Bionic Adapter и Web DocumentWorkspace содержат upload/version/enqueue/fragments/artifacts/evidence flows. Требуется реальный файл, worker, storage, обработка и проверка artifact preview |
| 8 | PEA retrieval в Agent Runtime | Не реализовано | Bionic Adapter обслуживает документы и knowledge для UI, но Agent Runtime ещё не вызывает tenant/project-scoped PEA search tool. Требуется search API/tool, фильтрация ACL до prompt и grounded-answer regression tests |

### 10.3 Важные ограничения и вывод

- GitHub Actions подтверждает CI, но не может заменить тест локального Stack, Keycloak, Kubernetes/Docker networking или LM Studio на компьютере разработчика.
- В текущем сеансе нет подключения к локальному компьютеру/кластеру пользователя и нет Keycloak admin credentials. Поэтому шаги 3–7 нельзя безопасно выполнить удалённо из GitHub. Они не отмечаются Done.
- Для шага 5 нельзя считать смену tenant реализованной: текущая интеграция передаёт один активный tenant context в токене. До разработки tenant switch следует проверить изоляцию между отдельными пользователями/tenant и не добавлять переключатель, который меняет только frontend state.
- Для шага 8 нельзя называть ответы Bionic документно-обоснованными. До реализации retrieval tool чат должен явно оставаться без автоматического контекста загруженных документов.
- Web docs/API_ADAPTER.md приведён в соответствие с фактическим кодом DocumentWorkspace 0.4.0: upload/version/processing/evidence UI присутствуют, но live E2E не принят.

### 10.4 Следующий исполнимый этап

После успешного CI gate следующий этап — **локальный runtime UAT авторизации**:

1. Запустить Stack-managed Keycloak realm `bionic-gpt`, Bionic и PEA; убедиться, что Bionic OIDC gateway работает и PEA доступен только по private route.
2. Выполнить `python scripts/configure_keycloak_realm.py` в PEA с реальными локальными Stack admin credentials; проверить discovery issuer, JWKS, audience `pea-api`, scope `pea-api-context`, public client `pea-web`, exact redirect URI и web origin.
3. Создать/проверить два PEA user и memberships; выполнить явное identity provisioning по immutable `(issuer, subject)`. Не создавать membership автоматически при входе.
4. Проверить gateway spoofed-header rejection, invalid signature/issuer/audience/expiry, inactive identity/user/tenant/membership и cross-project IDOR.
5. Выполнить PKCE login/logout в браузере и подтвердить session/projects.
6. Только после auth gate проверить conversation/SSE/LM Studio и document upload → processing → SourceFragment/artifact preview.
7. Отдельной разработкой добавить scoped PEA retrieval tool в Agent Runtime.

**Текущий итог:** шаги 1 и 2 закрыты. Шаги 3–7 требуют локального runtime UAT. Шаг 8 требует разработки, а не только настройки окружения.


### 10.5 Дополнительный deployment blocker, обнаруженный при проверке Stack manifest

Проверка `bionic-personal-expert-ai/infra-as-code/stack.yaml` и `infra-as-code/docker-compose.yml` выявила существенное расхождение:

- Stack manifest указывает `services.web.image: ghcr.io/bionic-gpt/bionicgpt:1.13.4`.
- Docker Compose также указывает upstream image `ghcr.io/bionic-gpt/bionicgpt:1.13.4`.
- CI `rust-check.yml` проверяет Rust source и web assets, но не собирает и не публикует fork-specific container image; workflow имеет path filters на Rust crates/Cargo/workflow и не проверяет изменения `infra-as-code/**`.

Следствие: успешные Rust tests/build доказывают компилируемость форка, но сами по себе не доказывают, что локальный Stack запускает именно этот fork. Если развернуть Stack по текущему manifest без отдельного image override/build, вероятно будет запущен upstream Bionic image без PEA Adapter изменений.

**Нельзя продолжать runtime-auth UAT, пока не будет однозначно подтверждено, что развернутый Bionic image собран из fork commit `d096698...` (или более нового проверенного commit).**

Следующая инфраструктурная задача перед шагом 3:
1. Выбрать контролируемый способ доставки fork image: локальная сборка/загрузка в локальный Kubernetes либо отдельный fork-owned GHCR package.
2. Зафиксировать immutable image tag/digest, содержащий fork Adapter и JWT extractor.
3. Обновить Stack manifest (и при необходимости Compose) на этот image; не указывать upstream image и не публиковать fork под upstream package.
4. Добавить CI validation для `infra-as-code/stack.yaml` и Compose; по возможности build/publish workflow с fork-owned package.
5. Проверить в запущенном pod/container image digest и наличие ожидаемых Adapter routes до начала login tests.

Это не исправлялось автоматически: целевой registry/package и способ локального развёртывания ещё не согласованы. Нельзя подставлять выдуманный GHCR image или tag.

### 10.6 Обновлённый порядок выполнения

1. CI PEA/Web и Rust source gate Bionic — пройдены.
2. **Fork-specific Bionic image build/deploy provenance — новый обязательный gate, открыт.**
3. Trusted gateway и private Bionic → PEA network.
4. Keycloak realm provisioning и browser PKCE login.
5. User/tenant/project negative isolation tests; tenant switching остаётся отдельной функцией.
6. Live conversation/SSE + LM Studio.
7. Live document upload → immutable version → processing → SourceFragment/artifact.
8. Implement PEA-scoped retrieval tool in Agent Runtime and grounded-answer tests.

До закрытия пункта 2 нельзя считать последующие runtime gates проверенными.


**Local environment safety note:** the Bionic fork's `.agents/skills/k3d-environment/dev-init.sh` begins with `k3d cluster delete k3d-bionic`. Do not run `just dev-init` against a cluster containing data or workloads that must be preserved. Inspect the current k3d cluster and back up needed state before local UAT. The setup script also disables Kubernetes API TLS verification in the local kubeconfig; keep this limited to disposable local development and do not reuse that kubeconfig for production.
