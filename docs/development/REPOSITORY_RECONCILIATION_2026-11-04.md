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
