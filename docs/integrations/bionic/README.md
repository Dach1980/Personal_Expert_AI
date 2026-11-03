# Оценка и интеграция Bionic

- Статус: сравнительный аудит выполнен; runtime POC не начат.
- Дата аудита: 2026-11-03.
- Bionic: https://github.com/bionic-gpt/bionic-gpt
- Проверенная ревизия Bionic: `main`, tree SHA `8a9797c39680ae8421bfaef72f87eb90650e7a09`.
- Проверенная ревизия Personal Expert AI: `main`, commit `7858c46eb4545efef7f78e4d3167b61266822484`.

## Цель

Оценить Bionic как источник готовых платформенных компонентов для Personal Expert AI: хранения и доступа к данным, RAG, пользователей и разрешений, обработки запросов, агентного runtime, Skills, инструментов, аудита и эксплуатации.

Решение о полной или частичной замене текущей реализации не принято. До изменения production-кода выполняются компонентный аудит, изолированный POC, сравнительные тесты и проверка безопасности.

## Основной принцип

Personal Expert AI остаётся продуктом и владельцем инженерной предметной модели. Bionic рассматривается как возможная платформа для общих AI-функций. Нельзя создавать две конкурирующие системы истины для пользователей, проектов, документов и их версий.

Сохраняются обязательные свойства Personal Expert AI:
- неизменяемые версии оригиналов и SHA-256;
- точные source locators: PDF page/bbox, DOCX paragraph/table cell, XLSX sheet/cell, PPTX slide/shape;
- provenance каждого SourceFragment, ProcessingRun и ProcessingArtifact;
- специализированная инженерная Knowledge Model и Project Expert Engine;
- локальный LM Studio provider и запрет незаметного облачного fallback.

## Классификация

- **REUSE** — использовать компонент Bionic без существенного изменения после проверки контрактов.
- **ADAPT** — взять реализацию или архитектуру Bionic и адаптировать под наши tenant/project/provenance требования.
- **KEEP** — сохранить компонент Personal Expert AI.
- **REPLACE** — заменить текущий компонент только после успешного POC, миграции и плана отката.

## Документы

- [Сравнительный аудит шести направлений](COMPONENTS.md).
- [Вариант отдельного сайта на GitHub Pages](GITHUB_PAGES_FRONTEND.md).
- Общий список задач: [ROADMAP](../../development/ROADMAP.md).

## Ограничения аудита

Это статический анализ исходного кода, SQL migrations, запросов и deployment-конфигурации. Не проводились запуск Bionic, penetration testing, performance benchmark, тестирование восстановления и end-to-end проверка LM Studio. Утверждения о совместимости и готовности к production должны быть подтверждены POC.
