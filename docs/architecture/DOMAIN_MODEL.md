# Domain Model — модель предметной области

- Статус: базовая архитектурная спецификация, версия 1.0
- Дата: 2026-11-01

## 1. Принципы моделирования

1. PostgreSQL — источник истины для метаданных и связей. Файловое хранилище содержит бинарные оригиналы и производные артефакты.
2. Все идентификаторы сущностей — устойчивые UUID; внешние API не раскрывают внутренние пути хранения.
3. Все tenant-scoped сущности содержат tenant_id; проектные сущности дополнительно содержат project_id, где применимо.
4. Время хранится в UTC; дата нормативной применимости — отдельное календарное значение и не подменяется временем загрузки.
5. Оригинал, версия, результат обработки, извлечённый факт и вывод проверки — разные сущности.
6. Автоматически извлечённые значения не считаются подтверждёнными только потому, что их вернула модель.

## 2. Контекст владения и доступа

**Tenant** — граница организации/изолированной установки. Для single-user установки tenant всё равно существует.

**User** — учётная запись. Не является владельцем файлов напрямую: доступ определяется членством и разрешениями.

**Membership** — связь пользователя с tenant и ролью.

**Workspace** — пользовательская область группировки проектов и диалогов. Не заменяет tenant boundary.

**Project** — инженерный объект/проект, содержащий документы, версии, контекст, знания, память, диалоги и проверки.

**ProjectMembership** — связь пользователя с проектом и набором прав.

## 3. Основные сущности

| Сущность | Назначение | Ключевые поля |
|---|---|---|
| Tenant | Организационная граница | id, name, status, created_at |
| User | Пользователь | id, login, display_name, status |
| Membership | Роль в tenant | tenant_id, user_id, role |
| Workspace | Область интерфейса | id, tenant_id, name |
| Project | Проект | id, tenant_id, workspace_id, code, name, status, metadata |
| ProjectMembership | Доступ к проекту | project_id, user_id, role |
| Document | Логический документ | id, project_id, document_type, title, current_version_id |
| DocumentVersion | Неизменяемая редакция | id, document_id, version_label, checksum, storage_key, media_type, size |
| ProcessingRun | Запуск обработки версии | id, document_version_id, pipeline_version, status, started_at |
| ProcessingArtifact | Производный файл/результат | id, processing_run_id, artifact_type, storage_key, checksum |
| SourceFragment | Локализованный участок источника | id, document_version_id, locator, content, content_hash |
| KnowledgeItem | Структурированное знание | id, project_id, kind, canonical_value, status |
| KnowledgeAssertion | Утверждение с provenance | id, knowledge_item_id, source_fragment_id, extractor, confidence, review_status |
| Relation | Связь между объектами/знаниями | id, project_id, source_id, relation_type, target_id |
| Conversation | Диалог | id, project_id, owner_user_id, title |
| Message | Сообщение | id, conversation_id, role, content, created_at |
| MemoryEntry | Запись памяти | id, scope_type, scope_id, content, status, provenance |
| Skill | Версионируемая процедура | id, name, version, status, definition |
| SkillExecution | Запуск Skill | id, skill_version_id, project_id, status, input_ref, output_ref |
| ReviewRun | Запуск инженерной проверки | id, project_id, config, status, reproducibility_manifest |
| Finding | Результат проверки | id, review_run_id, severity, category, statement, status |
| EvidenceLink | Связь вывода с доказательством | id, finding_id, source_fragment_id, evidence_role |
| AuditEvent | Аудит действия | id, tenant_id, actor_id, action, target_ref, timestamp |

## 4. Связи

- Tenant 1:N User memberships, Workspaces, Projects.
- Workspace 1:N Projects.
- Project 1:N Documents, Conversations, KnowledgeItems, ReviewRuns.
- Document 1:N DocumentVersions.
- DocumentVersion 1:N ProcessingRuns.
- ProcessingRun 1:N ProcessingArtifacts и SourceFragments.
- SourceFragment может поддерживать несколько KnowledgeAssertions и EvidenceLinks.
- KnowledgeItem 1:N KnowledgeAssertions; одно знание может иметь несколько источников и конфликтующие утверждения.
- Relation связывает KnowledgeItems и/или другие разрешённые доменные объекты в пределах проекта.
- Conversation 1:N Messages.
- MemoryEntry имеет ровно одну область действия: user, project, conversation или tenant.
- Skill 1:N SkillVersions; SkillExecution ссылается на конкретную версию.
- ReviewRun 1:N Findings; Finding 1:N EvidenceLinks.

## 5. Документ и версия

Document — логическая идентичность документа (например, «Пояснительная записка»). DocumentVersion — конкретный бинарный файл/редакция. Новая загрузка не должна изменять старый storage object. Версия может быть помечена как current, superseded, rejected или archived, но физически хранится по политике retention.

Checksum вычисляется для исходных байтов. Дубликат checksum в пределах проекта может быть предложен пользователю как повторная загрузка, но решение об объединении логических документов не должно приниматься только по checksum.

## 6. SourceFragment и локаторы

Локатор — типизированная структура, а не свободный текст. Примеры:
- PDF: page_number, bbox, coordinate_system, rotation.
- DOCX: section_path, paragraph_index, table_index, cell coordinates.
- XLSX: sheet_name, cell_range.
- DWG/IFC: model_id, object_id, drawing/sheet reference, geometry locator — по мере поддержки.
- Image: page/image identifier, bbox, crop reference.

Каждый фрагмент сохраняет document_version_id, processing_run_id, extraction_method, content_hash и ссылку на исходный артефакт. Координаты должны иметь однозначную систему отсчёта и преобразование к отображаемому изображению.

## 7. Статусы и неизменяемость

Для ProcessingRun: queued, running, succeeded, partially_succeeded, failed, cancelled.

Для KnowledgeAssertion: proposed, accepted, rejected, superseded, disputed.

Для MemoryEntry: proposed, confirmed, rejected, expired, deleted.

Для Finding: draft, open, accepted, rejected, resolved, deferred.

Для DocumentVersion: uploaded, processing, indexed, failed, superseded, archived, deleted_pending, deleted.

Переходы статусов валидируются сервисным слоем. Существенные изменения и удаления аудируются.

## 8. Multi-tenant и целостность

- Все запросы выполняются в контексте tenant и пользователя.
- Foreign keys и уникальные ограничения включают tenant_id там, где это защищает от межтенантных ссылок.
- PostgreSQL Row-Level Security может использоваться как дополнительная защита, но не заменяет проверки в application layer.
- Нельзя строить запросы к vector index без tenant_id и project_id фильтра.
- Объекты файлового хранилища получают непредсказуемые storage keys; путь нельзя строить из пользовательского имени файла.
- Логи и кэши не должны содержать содержимое документов без необходимости.

## 9. Индексация и производные представления

Поисковые записи, embeddings, summaries и graph projections — производные данные, а не источник истины. Каждая запись должна быть связана с исходной сущностью, версией документа, pipeline/model version и областью доступа. Производные индексы можно перестроить из сохранённых оригиналов и промежуточных артефактов.

## 10. Что не фиксируется преждевременно

Физическая схема vector store, graph database и стратегия partitioning остаются открытыми. Начальный benchmark сравнивает PostgreSQL FTS + pgvector с Qdrant на одинаковом корпусе и наборе запросов. Graph store вводится только при доказанной потребности в traversal, которую нельзя разумно обслужить реляционными связями.
