# Отдельный frontend для Bionic с публикацией через GitHub Pages

- Статус: архитектурная возможность подтверждена; разработка и интеграционный POC не начаты.
- Дата: 2026-11-03.

## Краткий ответ

Да, можно создать отдельный GitHub-репозиторий с собственным frontend и публиковать его через GitHub Pages. Статический сайт может взаимодействовать с отдельно развёрнутым Bionic backend по HTTPS API.

Однако GitHub Pages — это static hosting, а не сервер приложений. Он не запускает Bionic, Rust/Axum, PostgreSQL, RAG worker, object storage, агента или локальные модели. Сам Bionic — серверная платформа, для которой нужен отдельный runtime и deployment.

## Предлагаемая схема

```text
Browser
  |
  | HTTPS: static assets
  v
GitHub Pages
  |
  | HTTPS API / streaming
  v
Reverse proxy / API gateway
  |
  +--> Bionic web-server / agent-harness
  |       +--> PostgreSQL / pgvector
  |       +--> RAG worker
  |       +--> tool runtime / sandbox
  |
  +--> LM Studio (private network / loopback on host)
```

Frontend можно разрабатывать независимо: React + Vite, Vue + Vite или другой static SPA stack. GitHub Actions собирает HTML/CSS/JS и публикует каталог build output в Pages. Для SPA нужно отдельно обработать маршрутизацию и fallback на index.html.

## Что будет работать на GitHub Pages

- публичная стартовая страница, описание продукта и документация;
- frontend приложения, собранный в статические HTML/CSS/JS assets;
- формы, таблицы, навигация, чат UI и клиентская логика;
- вызовы backend API из браузера, если backend доступен по HTTPS и корректно настроены CORS, authentication и network policy.

## Что не будет работать на GitHub Pages

- Rust/Axum server и Bionic runtime;
- Python/FastAPI backend;
- PostgreSQL/pgvector и миграции;
- RAG ingestion workers и фоновые очереди;
- файловое хранилище, приватные документы и секреты;
- хранение API keys и доверенная серверная проверка пользовательских прав;
- LM Studio как сервер модели.

Нельзя помещать токены, ключи, приватные документы или секреты в frontend bundle, GitHub repository или Pages environment, доступные браузеру.

## Варианты deployment

### Вариант A — GitHub Pages + self-hosted Bionic (рекомендуется для POC)

- UI лежит в отдельном репозитории и публикуется Pages.
- Bionic развёрнут на отдельном сервере/локальной машине пользователя.
- Доступ к Bionic идёт через HTTPS reverse proxy или VPN/private gateway.
- Identity проверяется backend-side; CORS ограничен точным origin Pages.
- LM Studio остаётся в private network, а не публикуется напрямую в интернет.

Преимущество: независимый UI и переиспользование Bionic backend. Ограничение: если Bionic доступен только на localhost/в домашней LAN, внешний Pages frontend не сможет безопасно обращаться к нему без специально настроенного защищённого канала.

### Вариант B — Pages только для публичного сайта, приложение обслуживает Bionic

- GitHub Pages публикует маркетинговый сайт и документацию.
- Кнопка входа ведёт на отдельный домен/поддомен, где Bionic сам обслуживает web application.
- Приватная часть не зависит от Pages и может быть доступна только через VPN.

Преимущество: меньше проблем с CORS и интеграцией, проще сохранить штатную авторизацию Bionic. Недостаток: frontend не является полностью независимым.

### Вариант C — полностью локальный/offline UI

- Frontend собирается из отдельного репозитория, но раздаётся локальным Bionic/reverse proxy или локальным web server.
- GitHub Pages используется только для публичной демонстрации/документации, не для доступа к приватным данным.

Это наиболее согласованный вариант с требованием offline/local-only, если браузер и Bionic находятся на одном устройстве/в одной защищённой сети.

## Критические условия безопасности

1. Не публиковать Bionic API, LM Studio и PostgreSQL напрямую в интернет.
2. Использовать HTTPS, reverse proxy, rate limits и строгую CORS allowlist.
3. Проверять подпись JWT, issuer, audience, expiry и scopes на доверенной backend boundary. Не считать forwarded claims доказательством подлинности.
4. Не помещать bearer tokens, provider API keys или DB credentials в JS bundle.
5. Все project/tenant permissions проверять на backend для каждого запроса; скрытие UI-кнопки не является контролем доступа.
6. Запретить публичный network egress из sandbox, если он не разрешён policy.
7. Убедиться, что GitHub Pages не используется для загрузки или хранения приватной документации.
8. Отдельно проверить streaming/SSE, CORS preflight, cookies/credentials и browser storage/token lifecycle.
9. Для local-only режима не допускать fallback на hosted model/provider.

## Отдельный репозиторий

Предлагаемое имя: `Personal_Expert_AI_Web` (имя предварительное, репозиторий не создан).

Пример структуры:

```text
Personal_Expert_AI_Web/
├── src/
│   ├── app/
│   ├── pages/
│   ├── components/
│   ├── api/
│   ├── auth/
│   └── features/
├── public/
├── tests/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── SECURITY.md
│   └── BIONIC_API_CONTRACT.md
├── .github/workflows/
│   └── pages.yml
├── package.json
└── vite.config.ts
```

Frontend должен зависеть от собственного API client/adapter, а не напрямую от внутренних URL и форм Bionic. Это позволит позднее заменить Bionic или переключить frontend на Personal Expert AI API без переписывания интерфейса.

## POC acceptance criteria

- [ ] Статический build успешно публикуется GitHub Pages из отдельного репозитория.
- [ ] Frontend подключается к тестовому Bionic backend через HTTPS.
- [ ] Login/session flow проходит без секретов в build output.
- [ ] CORS ограничен только ожидаемыми origins.
- [ ] Chat streaming, conversation history и error handling работают.
- [ ] Файлы и RAG доступны только после backend authorization.
- [ ] Проверены cross-user/team/project access denial и IDOR cases.
- [ ] Browser network capture подтверждает отсутствие прямого обращения к LM Studio/PostgreSQL.
- [ ] Backend не доступен публично без защищённого auth gateway.
- [ ] Проверена работа при выключенном внешнем hosted inference и запрещённом egress.

## Архитектурное решение на текущем этапе

GitHub Pages подходит для независимого статического frontend, но не является местом размещения Bionic. Для первой проверки разумно создать отдельный frontend repository, не форкать и не переносить в него Bionic server code. Сначала выполнить небольшой read-only/chat POC, затем решать вопрос о полноценной пользовательской платформе.
