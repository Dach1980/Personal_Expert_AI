# Публичный frontend Personal Expert AI — GitHub Pages

- Дата обновления решения: 2026-11-04.
- Репозиторий: https://github.com/Dach1980/Personal_Expert_AI_Web
- Публичный адрес: https://dach1980.github.io/Personal_Expert_AI_Web/
- Статус: **обязательный отдельный поток разработки; рабочая версия сайта должна быть создана в этом публичном репозитории**.

## Решение

С 2026-11-04 GitHub Pages frontend больше не рассматривается только как запасная альтернатива или место для документации. Пользователь подтвердил, что рабочую публичную web-версию Personal Expert AI нужно разрабатывать в отдельном публичном репозитории `Personal_Expert_AI_Web` и публиковать по указанному URL.

Этот frontend — самостоятельный клиент продукта. Он не заменяет PEA backend и не запускает Bionic server. Bionic fork продолжает развиваться как отдельная серверная/UI/agent-runtime ветка для POC и переиспользования компонентов. Сайт должен иметь собственный API client/adapter, чтобы не зависеть от внутренних маршрутов и форм Bionic.

## Целевая схема

```text
Browser
  |
  | HTTPS: static assets
  v
GitHub Pages
  |  Personal_Expert_AI_Web (SPA)
  |
  | HTTPS API / streaming
  v
Trusted HTTPS gateway / reverse proxy
  |
  +--> Personal Expert AI FastAPI
  |      +--> PostgreSQL + RLS
  |      +--> local document storage
  |      +--> processing workers
  |
  +--> Bionic fork (optional agent/UI runtime during POC)
  |
  +--> Keycloak (OIDC login; same Stack-managed realm)
             |
             v
       Local LM Studio (private network only, backend-side)
```

Схема логическая: browser не обращается напрямую к PostgreSQL, local storage, LM Studio или внутренним портам Bionic. Все операции с данными и проверка прав выполняются на доверенной backend boundary.

## Обязанности репозитория сайта

- React/Vite или другой согласованный static SPA stack.
- Публичная стартовая страница и рабочий интерфейс приложения.
- Branding Personal Expert AI, утверждённый логотип, favicon и навигация.
- Проекты, документы, версии, статусы обработки, диалог и evidence presentation.
- Собственный API client/adapter и типизированные контракты.
- Auth/session UX для согласованной Keycloak/OIDC схемы.
- Unit, component, contract и browser E2E tests.
- GitHub Actions workflow для build и публикации Pages.

## Что GitHub Pages не выполняет

GitHub Pages — статический хостинг. Он не запускает FastAPI, Bionic web-server/agent runtime, Keycloak, PostgreSQL, workers, storage или LM Studio. Backend должен работать отдельно на локальном/частном или защищённом серверном runtime.

Если backend доступен только через localhost или LAN, внешний Pages frontend не сможет безопасно обращаться к нему без специально настроенного защищённого канала. Не публиковать внутренние порты и не отключать auth ради демонстрации.

## Обязательные требования безопасности

1. Не включать секреты, пароли, client secrets, DB credentials, provider keys и signing keys в публичный репозиторий или JS bundle.
2. Не хранить приватные документы, персональные данные, индексы и результаты проверок в GitHub Pages.
3. Не помещать постоянные bearer tokens в localStorage или исходный код; выбрать и документировать безопасный session/token flow с учётом OIDC и static hosting.
4. Backend проверяет JWT signature, issuer, audience, expiry и актуальные memberships.
5. Все tenant/project scopes вычисляются/проверяются backend-side; клиентские ID не являются доказательством доступа.
6. CORS allowlist ограничивается точным origin Pages и необходимыми методами/headers.
7. Не открывать PostgreSQL, LM Studio и внутренние Bionic/PEA порты в интернет.
8. Проверить CSRF/XSS, redirect URI, logout, token expiry/refresh, SSE streaming и browser network requests.
9. Не допускать cloud inference fallback при local-only конфигурации.

## План реализации

- [ ] Проверить наличие и настройки репозитория `Dach1980/Personal_Expert_AI_Web`.
- [ ] Настроить GitHub Pages и custom workflow из ветки `main`.
- [ ] Создать SPA scaffold с корректным base path `/Personal_Expert_AI_Web/`.
- [ ] Добавить branding, logo, favicon, theme и навигацию.
- [ ] Реализовать страницы Projects, Project Workspace, Documents, Chat, Reviews/Evidence, Settings.
- [ ] Создать независимый API client/adapter и contract tests.
- [ ] Спроектировать и реализовать OIDC login/session flow для Pages origin.
- [ ] Настроить защищённый HTTPS gateway и строгий CORS.
- [ ] Подключить PEA projects/documents/versions/processing status.
- [ ] Подключить chat streaming и evidence locators.
- [ ] Провести browser E2E и security tests, включая IDOR и cross-tenant/project cases.
- [ ] Проверить deployment после чистой публикации и refresh прямых SPA routes.

## Критерии готовности

- Публичный URL доступен по HTTPS и автоматически обновляется из `main`.
- Приложение загружается, навигация и прямые URL работают после refresh.
- Пользователь может пройти авторизацию и выйти.
- Реальные проекты/документы отображаются только после backend authorization.
- Чат и streaming работают через защищённый API.
- Ответы показывают проверяемые источники и locators.
- Никаких секретов и приватных данных нет в публичных assets.
- Подтверждены cross-user, cross-tenant, cross-project denial и отсутствие прямого доступа браузера к внутренним сервисам.

## Связанные документы

- [Сводный аудит и план проекта](../../development/PROJECT_STATUS_AUDIT_2026-11-04.md)
- [Целевая архитектура](../../architecture/TARGET_ARCHITECTURE.md)
- [Bionic fork UI plan](FORK_UI_PLAN.md)
- [Bionic POC execution](POC_EXECUTION.md)

