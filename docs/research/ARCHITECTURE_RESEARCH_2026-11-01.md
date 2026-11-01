# Архитектурное исследование Personal Expert AI

**Дата:** 2026-11-01  
**Статус:** исследование завершено; архитектурные решения предварительные до интеграционных прототипов.

## 1. Цель и критерии

Personal Expert AI должен предоставлять интерфейс диалога, похожий на ChatGPT, но специализироваться на проектной документации. Пользователь загружает комплект документов; система сохраняет оригиналы, извлекает текст, таблицы, формулы, изображения и структуру, создаёт подробное описание и индексирует материалы. Затем пользователь задаёт вопросы по конкретному проекту и получает ответы с точными ссылками на исходные доказательства. Отдельный режим запускает инженерные проверки.

Критерии выбора: локальность и контроль сетевых обращений; API и интегрируемость; разделение пользователей/проектов; сохранение provenance (происхождения данных); пригодность для PDF, таблиц, формул и чертежей; расширяемость; лицензия и риск зависимости от внешнего продукта.

## 2. Краткий итог

| Компонент | Роль | Рекомендация |
|---|---|---|
| AnythingLLM Docker | Готовый UI и экспериментальная оболочка чата/RAG | Проверить прототипом; не делать владельцем доменной модели |
| LM Studio | Локальный runtime моделей и embeddings | Использовать первым LLM runtime за собственным адаптером |
| Hermes Agent | Образец памяти, Skills, истории и делегирования | Изучить и заимствовать идеи; не включать как обязательное ядро |
| Project Expert AI | Инженерная обработка и экспертные проверки | Переносить как независимые Python-модули/API |
| Bionic | Настольная агентная среда для документов и задач | Экспериментальная среда; не использовать как серверное ядро |

Основной принцип: собственная доменная модель, backend, document pipeline, память и инженерное ядро. Внешние приложения — заменяемые адаптеры и пользовательские поверхности.

## 3. AnythingLLM

### Подтверждённые возможности

Официальная документация разделяет Desktop и Docker. Docker поддерживает браузерный интерфейс, многопользовательский режим, пользователей и роли, управление доступом к workspace, API, RAG, агенты и локальные/внешние LLM-провайдеры. Desktop ориентирован на одного пользователя и не предоставляет multi-user permissions.

AnythingLLM имеет Developer API для управления workspace, документов, embeddings и чата. API-документация доступна на экземпляре по `/api/docs`; API-ключ даёт доступ к API и не должен попадать в браузер или публичные логи.

Репозиторий AnythingLLM опубликован под MIT License. Продукт поддерживает LM Studio и множество других LLM/embedding providers. Docker использует встроенную обработку документов и векторное хранилище LanceDB по умолчанию, с альтернативами, включая PGVector и Qdrant.

### Ограничения и риски

- Multi-user mode в Docker нельзя штатно вернуть в single-user mode после включения. Режим нужно выбрать до первичного развёртывания.
- Наличие workspace не означает автоматически достаточную для нашего продукта изоляцию файлов, векторных индексов, логов, кэшей и экспортов. Это нужно проверить тестами доступа.
- Встроенный ingestion/RAG — общий механизм для общения с документами, но не замена инженерному извлечению фактов, геометрии bbox, связей между листами, редакций документа и нормативной применимости.
- В контейнере доступ к LM Studio на хосте обычно настраивается через `host.docker.internal`, а не `localhost`.
- Официальный Docker quickstart использует `SYS_ADMIN` capability. До использования в продуктовой установке необходимо выяснить, можно ли обойтись меньшими привилегиями и ограничить контейнер.
- AnythingLLM умеет подключать как локальные, так и облачные провайдеры. Сам факт self-hosting не гарантирует локальность: нужно зафиксировать и ограничить конфигурацию провайдеров, telemetry, web search, connectors и внешние MCP.

### Решение

Оставить AnythingLLM Docker кандидатом на быстрый UI-прототип. Сначала проверить: авторизацию, workspace ACL, загрузку и удаление документов, источники/цитаты, streaming, историю, API и корректность работы с LM Studio. Не позволять AnythingLLM быть единственным хранилищем проектов и источником истины. Не выдавать клиенту его API key.

Если его UI/API мешает нашему provenance-контракту или изоляции, заменить на собственный frontend, сохранив backend.

## 4. LM Studio

### Подтверждённые возможности

LM Studio работает как локальный сервер моделей на localhost или в локальной сети. Доступны REST API, Python/TypeScript SDK и OpenAI-compatible endpoints. Совместимый API включает chat/responses, tool calling и embeddings. В актуальной документации рекомендуется собственный REST API v1 (`/api/v1/*`); он поддерживает stateful chat, MCP через API, API-token authentication, управление загрузкой/выгрузкой моделей.

Есть настройки сервера для аутентификации, доступа из локальной сети, CORS, MCP и JIT model loading. Разрешение API-клиентам вызывать MCP из `mcp.json` может давать доступ к файловой системе и приватным данным; использовать его только с аутентификацией и проверенным allowlist.

### Решение

Использовать LM Studio как первый локальный inference runtime. Backend обращается к нему через интерфейс `LLMProvider`, не напрямую из UI. Начать с OpenAI-compatible API для совместимости клиентских библиотек; отдельно адаптировать native v1 API для управления моделями и специфических возможностей.

Embeddings проверять отдельным тестовым набором. Не считать, что embedding-модель, хорошо работающая на обычном тексте, автоматически подходит для инженерных документов, обозначений, таблиц, нормативных пунктов и смешанного русского/латинского текста.

Ввести registry моделей и capabilities: chat, vision, embeddings, reranking, tool calling, context length. Выбор модели — конфигурация/профиль задачи, а не ветвления по провайдеру внутри инженерной логики.

Локальность достигается конфигурацией endpoint, запретом cloud providers по умолчанию, отключением ненужных внешних функций и сетевыми правилами. LM Studio может слушать сеть; по умолчанию оставить localhost, включить API token, не публиковать порт в интернет.

## 5. Hermes Agent

### Подтверждённые возможности

Hermes Agent — самостоятельный MIT-лицензированный агентный фреймворк. Он предоставляет tools/toolsets, MCP, делегирование подзадач, Skills, persistent memory и поиск по предыдущим сессиям.

Документированная базовая память включает:
- `MEMORY.md` — компактные заметки агента об окружении, проектах и изученных процедурах;
- `USER.md` — профиль и предпочтения пользователя;
- SQLite + FTS5 — история сессий и полнотекстовый поиск по ней.

Skills загружаются по требованию (progressive disclosure), что экономит контекст. Hermes поддерживает внешние memory providers и профили. Документация отдельно предупреждает не запускать два процесса, пишущих в один Hermes home.

### Решение

Не встраивать Hermes целиком в backend Personal Expert AI на текущем этапе. Заимствовать паттерны:
- компактная подтверждаемая память;
- отдельный поиск по истории;
- Skills с metadata, версиями, scope, тестами и approval;
- изолированные агенты/задачи;
- ограниченный tool registry.

Реализовать собственный Memory Engine на нашей доменной модели и в нашей БД. Память пользователя, проекта, документа, диалога и инженерных решений должна иметь владельца, provenance, дату, статус подтверждения, срок актуальности и возможность удаления. Память не является источником инженерной истины.

Автоматическое обучение Skills разрешать только в черновой области. Публикация навыка, влияющего на инженерную проверку, требует review и тестов.

## 6. Project Expert AI

### Что переносить

Изученные архитектурные материалы текущего репозитория подтверждают наличие следующих концепций и наработок:
- PDF parsing, OCR, страницы, визуальные доказательства и bbox;
- Evidence contract и проверка качества evidence;
- Engineering Facts и Project Object Model;
- Normative JSON 2.0 и normative routing;
- RAG как поиск кандидатов требований, а не самостоятельное решение;
- проверка применимости требования;
- Qwen expert decision;
- decision gaps, audit trace, pipeline telemetry и report contract;
- версионирование результатов и reference benchmarks.

Текущий инженерный контур:

`Evidence → Engineering Context → Normative Fit → Decision → Report`

Для полноценной экспертной проверки сохраняется расширенная цепочка:

`Project Document → Project Fact → Checking Object → Project Context → Normative Routing → RAG → Requirement → Applicability → Engineering Comparison → Qwen Decision → Evidence/Provenance → Report`

### Решение

Не копировать весь репозиторий в Personal Expert AI и не переписывать работающие модули. Выделять независимые Python-пакеты и API-контракты, переносить их поэтапно. Сначала определить границы модулей и зависимости, затем обеспечить одинаковые regression tests на старом и новом контурах.

Разделить два пользовательских режима:
1. **Документный помощник:** ответы на вопросы о загруженном проекте, поиск, сводки и сравнение редакций.
2. **Инженерная экспертиза:** запуск Skills и специализированного проверочного pipeline с нормативной базой и формализованными доказательствами.

Оба режима используют одну Document/Knowledge модель и один source-fragment/provenance контракт.

## 7. Bionic от LM Studio

### Подтверждённые возможности

Bionic — отдельное desktop-приложение, а не другое название LM Studio. Оно организует работу в Projects и Sessions, поддерживает прикрепление файлов/папок, общий набор project files, работу с документами, таблицами, PDF и изображениями. Для задач с кодом может работать с выбранным локальным каталогом, Git и shell-командами. Есть фоновые сессии, MCP и выбор локальной, удалённой или облачной модели.

Bionic может работать полностью с локальной моделью, но интерфейс также предлагает облачные модели LM Studio Secure Cloud и удалённые модели через LM Link. Следовательно, облачный режим должен быть исключён в наших испытаниях локальности.

В релизах октября 2026 отмечены совместная работа Bionic с LM Studio, улучшения MCP/skills, предварительный просмотр документов Office, CSV/TSV и управление decision model. Это активно развивающийся продукт.

### Решение

Использовать Bionic как лабораторию для оценки агентного UX, многошаговой работы с документами, Skills, фоновых сессий и локальных моделей. Не считать его готовым backend/UI-компонентом для нашего многопользовательского продукта: в исследованных публичных документах не обнаружен подтверждённый серверный API для встраивания Bionic как управляемого tenant-aware сервиса. Это не утверждение об отсутствии любых внутренних интерфейсов; требуется отдельная проверка.

Bionic не должен получать доступ ко всему каталогу с пользовательскими документами без изоляции. Не включать web search, cloud model и LM Link в тестах, где проверяется строгий offline режим.

## 8. Рекомендуемая целевая архитектура

### Логические слои

1. **Frontend/UI** — AnythingLLM Docker как прототип либо собственный web UI. UI отвечает за диалог, загрузку, проекты, просмотр источников и статусы задач.
2. **API Gateway / FastAPI** — единая точка доступа; auth, tenant/project scope, rate limits, audit.
3. **Application orchestration** — управление задачами, pipeline, модельными вызовами, Skills и агентами.
4. **Document Processing Engine** — извлечение PDF, OCR, таблиц, формул, изображений, чертежей, координат и структуры.
5. **Knowledge Engine** — Document/Version/SourceFragment/EngineeringFact/ProjectObject; точный, полнотекстовый, структурный и семантический поиск.
6. **Memory Engine** — пользовательская, проектная, документная и сессионная память; Skills registry.
7. **Expert Engine** — независимые модули Project Expert AI и будущие проверки разделов.
8. **LLM Gateway** — provider abstraction; LM Studio первым провайдером; registry моделей и capabilities.
9. **Persistence** — PostgreSQL как источник истины для метаданных, прав, версий, памяти и результатов; отдельное файловое хранилище для оригиналов/артефактов; векторное хранилище выбирается экспериментом.
10. **Integration layer** — MCP и внутренние tools с allowlist, минимальными правами и аудитом.

### Поток загрузки и вопросов

`Upload → Security Validation → Immutable Original → Document Version → Parse/OCR/Vision → Normalize → Source Fragments → Document Description + Engineering Facts → Quality Review → Index → Ready`

Далее:

`User Question → Auth/Project Scope → Query Classification → Hybrid Retrieval → Evidence Selection → Local LLM → Citation/Provenance Validation → Answer`

Если пользователь запускает проверку, запрос направляется не в обычный чатовый RAG, а в Expert Engine.

### Доменная модель

Сохранить и расширить сущности из текущего OVERVIEW:
- User, Workspace, Project;
- Document, DocumentVersion, ProcessingRun;
- SourceFragment;
- KnowledgeItem, EngineeringFact, ProjectObject, ProjectRelation;
- Conversation, Message;
- MemoryEntry, Skill, SkillVersion;
- Finding, Evidence, AuditEvent.

Каждая сущность, содержащая пользовательские данные, должна быть привязана к tenant/user и project scope. Индексы и фоновые задачи обязаны сохранять ту же область доступа.

### Хранилища

PostgreSQL оставить системным источником истины. Не фиксировать преждевременно vector DB или graph DB. Сравнить:
- pgvector + PostgreSQL FTS как минимальную операционную сложность;
- Qdrant + PostgreSQL как отдельный векторный слой;
- graph store только если Project Object Model и междокументные связи неэффективно поддерживаются реляционной моделью.

Оригинальные файлы хранить отдельно от БД, с content hash, неизменяемыми версиями и контролем доступа. Векторные индексы должны быть пересоздаваемыми производными данными.

## 9. Безопасность и локальность

- Local-only режим — настройка по умолчанию, а не обещание интерфейса.
- По умолчанию запрещены облачные LLM, внешние embedding APIs, web search, сторонние connectors и MCP с сетевым доступом.
- Исходные файлы считаются недоверенными данными; текст из них не может менять системные инструкции или разрешения агента.
- MCP/tools работают по allowlist; никаких произвольных shell/file/network tools в обычном режиме вопрос-ответ.
- Секреты AnythingLLM и LM Studio остаются только на backend/в локальном secret store.
- Проверить логи, telemetry, crash reports, DNS и сетевые соединения при offline тесте.
- Межпользовательская изоляция проверяется на API, файлах, индексах, кэшах, памяти, логах, экспортах и фоновых задачах.
- Документы, результаты и embeddings имеют tenant/project scope; поиск никогда не выполняется глобально без явного разрешения.
- Резервные копии шифруются; удаление проекта распространяется на производные индексы и память с учётом retention policy.

## 10. Прототипы, которые должны предшествовать окончательному выбору

### P0. Локальный inference
Поднять LM Studio API; проверить chat, vision, embeddings, tool calling, context limits, concurrency, streaming, authentication и поведение при выгрузке модели.

### P1. AnythingLLM UI/API
Запустить Docker локально; подключить LM Studio через host gateway; проверить workspace/user ACL, документы, API, citations, историю и удаление. Проверить контейнерные привилегии и сетевые соединения.

### P2. Документный pipeline
Взять обезличенный тестовый комплект PDF/DOCX/XLSX с текстом, таблицами, формулами, сканами и чертежами. Сравнить AnythingLLM ingestion с собственным ingestion Project Expert AI. Измерить полноту, точность, page/coordinate provenance, качество retrieval и время обработки.

### P3. Memory/Skills
Сделать прототип памяти с областями user/project/session и поиском истории. Сравнить простые SQL/FTS, семантический поиск и Skills on-demand. Проверить подтверждение, версионирование, удаление и защиту от prompt injection.

### P4. Интеграция Project Expert AI
Выделить один end-to-end кейс ВК и прогнать его через старый и новый контуры. Сравнить evidence, engineering facts, normative routing, applicability, Qwen decision и итоговый report по существующему benchmark.

### P5. Multi-user security
Создать минимум два тестовых пользователя и два проекта; попытаться получить чужие документы, фрагменты, embeddings, память, историю, логи и артефакты через все доступные API.

## 11. Предварительные архитектурные решения

1. Собственный FastAPI backend и доменная модель — обязательны.
2. LM Studio — первый локальный inference runtime, но за абстракцией LLM provider.
3. AnythingLLM Docker — кандидат на UI-прототип, не обязательная зависимость.
4. Hermes — источник архитектурных идей для памяти и Skills, не runtime-ядро.
5. Bionic — исследовательский desktop harness, не production backend.
6. Project Expert AI — инженерное ядро, переносимое по модульным контрактам.
7. PostgreSQL — источник истины; vector/graph решения остаются открытыми до benchmark.
8. Multi-tenant/project isolation моделируется с первого дня, даже если первый запуск single-user.

## 12. Открытые вопросы

- Насколько AnythingLLM API позволяет встроить наш точный provenance и пользовательский document lifecycle без дублирования состояния?
- Удастся ли обеспечить полноценную workspace isolation на уровне API, индексов и файлов?
- Какие embedding/reranker модели лучше работают на русскоязычных инженерных текстах и смешанных обозначениях?
- Достаточно ли PostgreSQL + pgvector или нужен Qdrant?
- Какие части Project Expert AI выделять как независимые пакеты первыми?
- Какой UI в итоге лучше: AnythingLLM с адаптацией или собственный frontend?
- Какие юридические условия и ограничения распространения применимы к LM Studio/Bionic в целевой коммерческой поставке? Это требует отдельной проверки актуальных условий продукта.

## 13. Источники

### AnythingLLM
- [Docker installation overview](https://docs.anythingllm.com/installation-docker/overview)
- [Security and access](https://docs.anythingllm.com/features/security-and-access)
- [API access and keys](https://docs.anythingllm.com/features/api)
- [GitHub repository and MIT license](https://github.com/Mintplex-Labs/anything-llm)
- [Docker deployment notes](https://github.com/Mintplex-Labs/anything-llm/blob/master/docker/HOW_TO_USE_DOCKER.md)

### LM Studio / Bionic
- [Developer documentation](https://lmstudio.ai/docs/developer)
- [REST API](https://lmstudio.ai/docs/developer/rest)
- [OpenAI-compatible endpoints](https://lmstudio.ai/docs/developer/openai-compat)
- [Server settings](https://lmstudio.ai/docs/developer/core/server/settings)
- [Bionic overview](https://lmstudio.ai/docs/bionic)
- [Bionic projects and sessions](https://lmstudio.ai/docs/bionic/projects-and-sessions)
- [Bionic working with documents](https://lmstudio.ai/docs/bionic/agent/work-project)
- [Bionic changelog 1.1.9 (2026-10-21)](https://lmstudio.ai/changelog/bionic-v1.1.9)

### Hermes Agent
- [Hermes documentation](https://hermes-agent.nousresearch.com/docs/)
- [Persistent memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)
- [Tools and toolsets](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools)
- [Sessions](https://hermes-agent.nousresearch.com/docs/user-guide/sessions)
- [MIT license](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE)

### Existing engineering core
- [Project Expert AI repository](https://github.com/Dach1980/VKS_Expert_AI)
- [Expert checking strategy](https://github.com/Dach1980/VKS_Expert_AI/blob/main/docs/architecture/EXPERT_CHECKING_STRATEGY.md)
