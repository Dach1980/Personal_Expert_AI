# Personal Expert AI — межрепозиторный roadmap

Дата актуализации: 2026-11-05  
Статус: план реализации, актуализируемый по фактическим CI и runtime результатам.

Текущие отчёты выполнения на 2026-11-05: [PEA](IMPLEMENTATION_STATUS_2026-11-05.md) · [Web](https://github.com/Dach1980/Personal_Expert_AI_Web/blob/main/docs/IMPLEMENTATION_STATUS_2026-11-05.md) · [Bionic adapter](https://github.com/Dach1980/bionic-personal-expert-ai/blob/main/docs/integration/PEA_API_ADAPTER.md).

## Репозитории и ответственность

| Репозиторий | Ответственность |
|---|---|
| [Personal_Expert_AI](https://github.com/Dach1980/Personal_Expert_AI) | Доменная модель, PostgreSQL, tenant/project ACL, документы и версии, processing, SourceFragments, reviews/findings/evidence, conversation API, локальный LLM provider |
| [bionic-personal-expert-ai](https://github.com/Dach1980/bionic-personal-expert-ai) | Bionic fork, Agent Runtime, server-side PEA Adapter, проверка JWT, trusted gateway boundary, Docker image |
| [Personal_Expert_AI_Web](https://github.com/Dach1980/Personal_Expert_AI_Web) | React/TypeScript UI, Keycloak PKCE client, проекты, документы, чат, reviews, knowledge, Skills, settings, GitHub Pages |

Подробный пользовательский и технический план экранов, API и критериев приёмки: [Personal_Expert_AI_Web/docs/PROJECT_ROADMAP.md](https://github.com/Dach1980/Personal_Expert_AI_Web/blob/main/docs/PROJECT_ROADMAP.md).

## Целевая архитектура

```text
Browser → GitHub Pages React SPA
       → Keycloak OIDC (Authorization Code + PKCE)
       → Bionic fork / PEA Adapter (public HTTPS boundary)
       → Personal Expert AI API (private service)
       → PostgreSQL + document storage + processing workers
       → local LM Studio / Qwen (no cloud fallback)
```

PEA остаётся единственным владельцем доменных данных и авторизации tenant/project. Bionic — интеграционная и agent-runtime платформа, не замена PEA domain layer. Frontend не обращается к PostgreSQL, private storage или LM Studio напрямую.

## Текущий статус на дату документа

### Подтверждено CI / исходниками

- PEA: PostgreSQL 16 migration/schema/integration gates, tenant/project data isolation checks, API/domain tests и lint проходят на проверенных CI revisions.
- Bionic: Rust formatting, compilation, tests, Agent Runtime auth/dialogue tests и web assets build проходят на проверенной CI revision.
- Web: TypeScript/Vite build и GitHub Pages deployment проходили на предыдущей проверенной CI revision. Последние изменения OIDC/SSE/citations/npm lockfile workflow находятся в `main`, но их новый Actions run пока не подтверждён.
- Web branding fix: root `assets/` назначен Vite `publicDir`; Sidebar, Footer и favicon используют `${BASE_URL}logo.svg`; workflow проверяет logo asset до и после публикации. Новые OIDC проверки (RS256/JWKS, issuer/audience/expiry/nonce, single-flight refresh, prompt=none session restore), SSE parser/citation UI, unit tests, npm ci bootstrap и GitHub Variables wiring добавлены в Web. Latest Web implementation status: [2026-11-05](https://github.com/Dach1980/Personal_Expert_AI_Web/blob/main/docs/IMPLEMENTATION_STATUS_2026-11-05.md).

### Не принято как runtime-ready

- Keycloak realm/client/scope configuration ещё нужно применить и проверить в фактическом Stack.
- Browser login/logout и token refresh не прошли live E2E.
- Bionic fork уже содержит server-side PEA Adapter routes для session/projects/conversations/SSE/documents/processing/source fragments/artifacts/reviews/findings/evidence и JWT extractor; это подтверждено исходниками/README, но не live runtime. Private network routing и реальный gateway flow не подтверждены.
- Переключение tenant не реализовано как полный пользовательский workflow; нельзя считать его готовым только потому, что API токен содержит tenant context.
- Развернутый Bionic image пока ссылается на upstream image, а не fork-specific image. До runtime UAT требуется собрать и проверить fork image.
- PEA Retrieval Tool для Bionic Agent Runtime и grounded answers с citations ещё требуется реализовать; наличие lexical SourceFragment API и Bionic proxy route само по себе не является runtime tool.
- LM Studio inference, embeddings, tool calling, streaming и производительность не проверены без локальной модели.
- Реальная загрузка/обработка документов и просмотр artifacts требуют runtime E2E.

## Принятые решения

1. Ветка разработки — `main`; не создавать feature branches без отдельной необходимости.
2. Изменения и аудит фиксировать в соответствующих GitHub repositories.
3. Пока пользователь не может запускать локальные команды, работать repository-first: source changes, documentation, GitHub Actions, contract/unit/integration tests.
4. Не объявлять runtime проверку пройденной на основании компиляции или mock tests.
5. Локальная модель — основной и единственный inference provider; cloud fallback запрещён.
6. Bionic deployment — вариант C: сейчас local fork image → k3d; architecture registry-neutral; позже private GHCR и immutable digest.
7. Не запускать destructive k3d initialization scripts автоматически; в частности, `dev-init.sh` удаляет кластер `k3d-bionic`.

## Порядок реализации

### Gate 0 — Frontend baseline
- Исправить и проверить logo/favicon asset publishing.
- Зафиксировать lockfile, перейти к reproducible npm install.
- Добавить frontend unit/component tests, lint/typecheck, asset smoke checks.
- Проверить Pages base path и published artifact.

### Gate 1 — UX and navigation
- Завершить разделы Workspace, Projects, Documents, Dialogues, Reviews, Knowledge Base, Skills, Settings.
- Реализовать loading/empty/error/permission states и responsive layout.
- Не показывать mock actions как реальные backend operations.

### Gate 2 — Identity and trusted gateway
- Keycloak public client `pea-web`, PKCE S256, issuer/audience/nonce/state/token expiry.
- Bionic independently validates RS256/JWKS and forwards only verified caller identity.
- PEA independently validates token and membership.
- Strip browser-supplied identity/forwarded-token headers at trusted gateway boundary.
- Add negative auth tests and token leakage checks.

### Gate 3 — Tenant and project context
- Tenant membership/list/switch API.
- Active tenant context must be server-validated, not client asserted.
- Project selection, role-aware UI, tenant/project isolation and RLS tests.
- Reset dependent UI state on context switch.

### Gate 4 — Conversation experience
- Normalize conversation/message API and SSE envelope.
- History, create/rename/archive, cancellation, retry, reconnect and errors.
- Stream text, citations, completion and error events.
- Contract tests for partial frames and network interruptions.

### Gate 5 — Document lifecycle
- Document list/detail, immutable versions, SHA-256, upload idempotency.
- Processing status, retry, parser outputs, SourceFragments and artifacts.
- Secure preview/download and evidence navigation.
- Test malformed, oversized and duplicate uploads.

### Gate 6 — PEA retrieval in Agent Runtime
- PEA scoped search endpoint over SourceFragments.
- ACL filtering before context construction.
- Bionic tool adapter with tenant/project scope from verified identity.
- Provenance citations to immutable document version and page/sheet/locator.
- Retrieval regression, prompt injection and cross-tenant tests.

### Gate 7 — Reviews and expert workflows
- Reviews, Findings, Evidence UI.
- Severity, violation/evidence-gap/conflict classification.
- Traceable source references and audit trail.
- Report export only after contract and provenance validation.

### Gate 8 — Knowledge, memory and Skills
- Explicit scope/ownership/retention of project memory.
- Versioned skills and permission checks.
- UI to inspect memory provenance and skill version.
- Prevent memory/skill paths from bypassing ACL.

### Gate 9 — Fork image and deployment
- Audit upstream Docker packaging and build pipeline.
- Build fork-specific Bionic image from immutable commit SHA.
- Update Stack and Compose manifests.
- Verify image digest and PEA Adapter routes.
- CI image build/manifest checks.
- Keep local k3d path independent from GHCR; later add private GHCR publishing.

### Gate 10 — Integrated acceptance
- Staging configuration and automated contract/E2E suite.
- Login → tenant → project → conversation → retrieval → citations.
- Upload → immutable version → processing → SourceFragments → artifacts.
- Failure tests for Keycloak, API, storage, worker and model provider.
- Observability without tokens or document contents.
- Backup/restore and security review.

## Ограничения repository-first режима

Без доступа к локальным Docker/k3d/Keycloak/LM Studio:

- можно реализовывать frontend/backend code, migrations, Docker build definitions, manifests, documentation and CI;
- можно запускать GitHub-hosted tests, static analysis, schema tests, contract tests and browser tests against controlled test services;
- нельзя утверждать, что локальный k3d cluster, реальные Keycloak settings, private network routes или LM Studio работают;
- mock model responses не засчитываются как LM Studio acceptance;
- live runtime acceptance остаётся отдельным release gate, который будет выполнен при появлении доступа к runtime среде.

## Definition of Done — продукт

Personal Expert AI считается рабочим продуктом, когда пользователь может безопасно войти через Keycloak, выбрать разрешённый tenant и project, загрузить документ, получить результат обработки, вести историю диалогов и получать ответы локальной модели с точными проверяемыми citations на доступные версии документов. Все действия должны быть tenant/project scoped, а изоляция подтверждена автоматизированными тестами.
