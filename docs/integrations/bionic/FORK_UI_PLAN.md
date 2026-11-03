# Bionic fork — план адаптации интерфейса Personal Expert AI

Upstream: https://github.com/bionic-gpt/bionic-gpt
Предлагаемое имя форка: Dach1980/bionic-personal-expert-ai
Лицензия upstream: Apache License 2.0. Сохранять LICENSE, copyright notices и notices исходных компонентов.

## Цель
Создать отдельный форк upstream Bionic и адаптировать UI под Personal Expert AI, сохраняя upstream agent harness и серверные возможности до завершения POC.

## Продуктовые принципы
- Personal Expert AI — название продукта и интерфейса.
- Bionic остаётся upstream-технологической основой, а не владельцем доменной модели.
- Personal Expert AI backend — authority для user, tenant, project, document, version, processing run, source fragment и review.
- Не переносить credentials Personal Expert AI PostgreSQL в Bionic.
- Не давать UI прямой доступ к БД, локальному storage или LM Studio.
- Не публиковать секреты в браузерном bundle.
- Локальный inference без незаметного облачного fallback.

## UI branding
- Product name: Personal Expert AI.
- Header/footer/app icon/favicon: https://raw.githubusercontent.com/Dach1980/cherkashin_ai_site/main/assets/logo.svg
- Проверить SVG и favicon pipeline, светлую и тёмную темы.
- Цветовую систему и типографику определить на UI prototype, не затрагивая runtime.

## Навигация
- Проекты
- Документы
- Диалоги
- Проверки
- База знаний
- Skills
- Настройки

## Рабочее пространство проекта
- список документов и immutable versions;
- статусы загрузки и обработки;
- evidence/source locators;
- история проверок;
- диалог с выбранным проектным контекстом;
- состояния insufficient evidence и processing incomplete.

## Чат
- streaming и отмена генерации;
- ссылки на исходные фрагменты;
- файл, версия, страница/лист/ячейка/слайд;
- отдельные tool activity events;
- понятное сообщение о недоступности локальной модели.

## Границы кастомизации
Сначала менять только branding/theme, navigation, pages/layout, chat composer/message rendering, project/document context panels и evidence presentation.
Не менять на первом этапе agent loop, tool dispatcher, sandbox, database schema, auth internals, RAG ingestion или model provider. Любое изменение runtime — отдельный commit с regression tests.

## Интеграционный слой
Создать адаптер Personal Expert API, преобразующий Bionic UI/agent tool calls в API контракты Personal Expert AI. Вызовы проходят через authenticated backend; browser UI не передаёт произвольные tenant scopes.
Первый этап read-only. Запись артефактов, запуск обработки и создание review records подключаются после проверки permission/approval semantics.

## Этапы
1. Создать настоящий GitHub fork upstream; не заменять fork копией исходников.
2. Зафиксировать upstream revision и sync strategy.
3. Поднять upstream без кастомизаций и сохранить baseline build/test.
4. Найти UI entrypoints и составить карту компонентов/роутов.
5. Сделать branding/theme отдельным минимальным слоем.
6. Перестроить навигацию и проектный workspace.
7. Подключить API adapter и evidence locators.
8. Добавить visual/contract/integration tests.
9. После этого оценить необходимость изменения agent runtime.

## Условия готовности
- upstream baseline собирается;
- custom UI собирается без изменения agent runtime;
- license notices сохранены;
- секреты остаются server-side;
- Bionic не имеет прямого доступа к Personal Expert AI PostgreSQL;
- project/document scope определяется сервером;
- evidence links ведут к точным immutable sources;
- upstream можно обновлять без ручного переноса всех UI изменений.