# ADR 0003: Стратегия оценки и поэтапного внедрения Bionic

- Статус: принято для этапа исследования и POC; решение о внедрении компонентов не принято.
- Дата: 2026-11-03.

## Контекст

Personal Expert AI уже содержит PostgreSQL tenant/project model, RLS, immutable document versions, local storage с SHA-256, durable upload/recovery lifecycle, extraction pipeline PDF/DOCX/XLSX/PPTX, OCR, provenance-bearing SourceFragments и LM Studio provider adapter.

При этом полноценные conversational orchestration, production RAG retrieval, Skills execution и общий agent runtime ещё не завершены. Bionic содержит развитую Rust-платформу с agent harness, tool runtime, Skills, virtual filesystem, RAG worker, RBAC, teams, audit и deployment tooling.

Полная замена Personal Expert AI на Bionic создаёт риск дублирования identity, project/document ownership и потери инженерной provenance. Кроме того, статический аудит обнаружил security assumptions, которые требуют проверки до production use: JWT claims в отдельных Bionic extractors читаются из forwarded token payload без локальной криптографической проверки, CORS agent-harness разрешает Any, Compose example содержит тестовые credentials и JWT override.

## Решение

1. Personal Expert AI остаётся владельцем доменной модели, tenant/project identity, оригиналов документов, immutable versions, provenance, инженерных знаний и инженерного checking engine.
2. Bionic оценивается как кандидат на reuse/adaptation общих платформенных компонентов: request orchestration, agent runtime, tools, Skills, VFS, RAG и audit/observability.
3. Ни один компонент не заменяется только на основании наличия реализации в Bionic.
4. Для каждого компонента применяется одна из меток: REUSE, ADAPT, KEEP или REPLACE.
5. Замена возможна только после изолированного POC, security tests, benchmark, data migration plan, rollback plan и подтверждения критериев приёмки.
6. GitHub Pages может использоваться для публикации отдельного статического frontend. Bionic backend, DB, workers, object storage и model runtime размещаются отдельно; приватные документы и секреты в Pages не хранятся.
7. Для frontend сохраняется собственный API adapter layer, чтобы не привязывать интерфейс к внутренним деталям Bionic.

## Рассмотренные варианты

### A. Полностью заменить Personal Expert AI на Bionic

Отклонено на текущем этапе: риск потери provenance, специализированной обработки инженерной документации и появления второго источника истины.

### B. Использовать Bionic как платформенный backend, сохранив инженерное ядро

Предпочтительный вариант для POC. Требует проверки API/identity boundary, доступа к SourceFragments, LM Studio compatibility, RAG metadata и sandbox.

### C. Перенять только архитектурные идеи и реализовать собственный runtime

Резервный вариант, если Bionic окажется слишком связанным со своей DB/UI/auth model или не пройдёт security/compatibility criteria.

## Последствия

- Потребуется отдельная интеграционная граница между Personal Expert AI API и Bionic.
- Нельзя давать Bionic произвольный прямой доступ к оригинальному storage.
- Нужно mapping tenant/project/user identities и enforcement на backend.
- RAG POC должен измерять retrieval quality и exact source provenance, а не только релевантность текста.
- Нужны network egress controls, JWT validation boundary, CORS allowlist и sandbox tests.
- GitHub Pages — только static hosting; он не заменяет Bionic runtime.
- Вся работа и критерии приёмки ведутся в `docs/integrations/bionic/` и общем `docs/development/ROADMAP.md`.

## План проверки

См. [COMPONENTS.md](../integrations/bionic/COMPONENTS.md), [GITHUB_PAGES_FRONTEND.md](../integrations/bionic/GITHUB_PAGES_FRONTEND.md) и [ROADMAP.md](../development/ROADMAP.md).
