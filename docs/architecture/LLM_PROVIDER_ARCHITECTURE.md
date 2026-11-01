# LLM Provider Architecture — архитектура подключения моделей

- Статус: проект спецификации, версия 1.0
- Дата: 2026-11-01

## 1. Цель

Изолировать доменную логику Personal Expert AI от конкретного inference runtime и формата API. Первым провайдером рассматривается LM Studio. Другие локальные runtimes должны подключаться без переписывания Document, Knowledge, Memory и Review Engines.

## 2. Схема

Domain services → LLM Orchestrator → Provider Adapter → Runtime API → Model.

Orchestrator выбирает capability и policy, формирует запрос, управляет timeout/retry/streaming и фиксирует manifest. Adapter преобразует внутренний контракт в API runtime и нормализует ответ. Доменным сервисам запрещены прямые вызовы специфичных endpoint LM Studio/OpenAI-compatible API.

## 3. Внутренние capabilities

- chat_completion(messages, options);
- stream_chat(messages, options);
- generate_structured(messages, schema, options);
- create_embeddings(inputs, options);
- vision_analysis(messages_with_assets, options);
- tool_calling(messages, tool_schemas, options);
- list_models();
- health_check().

Capability может быть unsupported. Нельзя предполагать поддержку vision, JSON schema, tools или embeddings только по факту наличия endpoint.

## 4. Provider Adapter

Adapter реализует provider_id/config, endpoint/auth, network scope, capability discovery, mapping request/response, streaming normalization, error normalization, timeout/cancellation/retry, model identity и health/readiness.

LM Studio adapter должен проверить Native REST API и OpenAI-compatible API. Выбор конкретного API определяется покрытием возможностей и результатами тестов. Секреты хранятся только на backend.

## 5. Типы моделей и маршрутизация

Категории: general reasoning/chat, embedding, reranker, vision/document understanding и OCR. Маршрутизатор выбирает модель по capability, локальной доступности, context window, VRAM и политике проекта. Автоматическая замена модели запрещена, если она меняет воспроизводимость инженерного результата.

## 6. Model manifest

Фиксировать provider_id, runtime name/version, model_id и ревизию/файл, quantization, context_length, temperature/top_p/seed (если доступны), system prompt version, template version, tool schema version, embedding model/version, timestamp и параметры выполнения. Неизвестные значения помечать unknown.

## 7. Контракт генерации

Запрос содержит task_type, типизированные messages (text/image), response schema, allowlisted tools, capability requirements, sampling options, timeout/cancellation и контекст безопасности tenant/project.

Ответ содержит content/structured output, нормализованные tool calls, usage (если доступно), finish_reason, provider/model manifest, warnings и latency. Raw provider metadata допускается только в безопасном диагностическом поле.

## 8. Streaming и tools

Adapter нормализует события started, delta, citation, tool_call_proposed, warning, completed и failed. Tool call — лишь предложение модели. Backend валидирует имя, schema, пользователя, scope, режим read/write/network, подтверждение, rate limit и timeout. UI не исполняет tool calls из токенов модели.

## 9. Embeddings

Embeddings имеют отдельный manifest. Индексы разных embedding models/dimensions нельзя смешивать. При смене модели требуется отдельная коллекция/пространство и контролируемый re-embedding. Сравнить модели на инженерном русскоязычном benchmark: recall@k, precision@k, MRR/nDCG, latency, memory, работа с таблицами и обозначениями.

## 10. Параллелизм и ресурсы

Учитывать VRAM/CPU, очередь, загрузку/выгрузку моделей, context windows и concurrency. Нужны bounded queue, quotas, cancellation и backpressure. Реальные лимиты runtime устанавливаются экспериментально.

## 11. Local-only

По умолчанию provider endpoint допускает только loopback/private адреса из allowlist. При ошибке локальной модели запрещено автоматически переключаться на облачный endpoint. Offline режим подкрепляется firewall/container policy и network tests.

## 12. План LM Studio P0

Проверить:
1. Chat completion на коротких и длинных инженерных запросах.
2. Streaming, завершение и отмену.
3. Structured output/JSON schema.
4. Tool calling: корректные, некорректные и запрещённые вызовы.
5. Vision: страницы PDF, таблицы, чертежи, формулы.
6. Embeddings: размерность, batching, стабильность.
7. Authentication и неверный токен.
8. Одновременные запросы, очередь, VRAM.
9. Загрузка/выгрузка модели и сбои runtime.
10. Network capture в local-only режиме.

Для каждого теста сохранять fixtures, manifest, expected/actual result, latency, resource usage и сетевые наблюдения.

## 13. Критерии готовности

Adapter готов, когда проходит contract и integration tests заявленных capabilities, сообщает unsupported features, корректно обрабатывает отмену и ошибки, не раскрывает секреты и не вызывает внешние сервисы вне разрешённой политики.
