# Контракт API v0.1 — шаг 1

Базовый URL: `http://127.0.0.1:8000`. JSON в UTF-8, время в UTC ISO 8601.
ID — непрозрачные строки. В демоданных ID стабильны, новые задачи получают UUID.
Рабочие примеры запросов/ответов: `docs/api-examples.json`.
Схема реализованных операций: `/openapi.json`.

## Уже работает

| Метод | Адрес | Назначение |
|---|---|---|
| GET | `/health` | Проверка сервера и базы |
| GET | `/api/demo/profiles` | `{businesses: [], teams: []}` для переключателя |
| POST | `/api/tasks` | Создать черновик; ответ 201 и объект задачи |
| GET | `/api/tasks` | Массив задач выбранного бизнеса, не публичный каталог |
| GET | `/api/tasks/{id}` | Приватная рабочая задача выбранного бизнеса |
| PATCH | `/api/tasks/{id}` | Сохранить рабочие поля; ответ — объект задачи |

Для всех `/api/tasks` обязателен заголовок `X-Demo-Business-Id: business-1`
или `business-2`. Это выбор демопрофиля, не настоящий вход в систему.
Отсутствующий заголовок — 400, неизвестный профиль — 404. Чужая задача также даёт 404.
Отдельный `X-Demo-Team-Id` будет подключён на шаге 4; сейчас его маршрутов нет.

Создание принимает `original_text` (непустой, максимум 20 000 символов) и `topic`
(необязательный, максимум 100 символов). `business_id` определяется из заголовка.

PATCH принимает только `draft_text`, `topic`, `answers`, `proposed_card`.
Пропущенное поле не меняется. `answers` и `proposed_card` при передаче заменяются
целиком; пустые поля карточки имеют значение `""`, список рекомендаций — `[]`.
`null`, пустой PATCH, поля статуса, рейтинга, владельца или снимков отклоняются.
`answers` — объект `{question_id: answer}`. `questions` — массив `{id, field, text}`,
пока пустой; позже его заполнит серверный AI-модуль.

Поля карточки:

`title`, `context`, `need`, `users`, `data`, `constraints`, `expected_result`,
`success_criteria`, `contact`, `interaction_format`, `ai_recommendations`.

Все поля, кроме списка `ai_recommendations`, — строки. Рекомендации не являются
подтверждёнными требованиями бизнеса. Клиент не рассчитывает рейтинг.

Слои задачи:

- `original_text` — исходный ввод, не меняется.
- `draft_text`, `questions`, `answers`, `proposed_card` — рабочие материалы.
- `confirmed_card`, `confirmed_rating`, `confirmed_at` — последний подтверждённый снимок.
- `published_card`, `published_rating`, `published_at` — снимок для общего каталога.
- `status` — только `draft` или `published`; это не уровень готовности.

Сейчас подтверждённые и опубликованные поля равны `null`. Не показывайте `null`
как нулевой рейтинг: показывайте «Ещё не рассчитан». В дальнейшем рейтинг содержит
`score`, `level`, `categories: [{key, label, points, maximum}]`, `missing_fields`.
Уровни: `draft`, `working`, `ready`, `priority`. Расчёт и границы реализуются на шаге 3.

Ошибки 400/404/405/422:

```json
{"error":{"code":"validation_error","message":"Проверьте поля запроса","details":[{"field":"body.original_text","message":"..."}]}}
```

Клиент должен сохранять локальный ввод при любом неуспешном запросе.
Для общего сервера CORS не нужен. Для разработки на другом порту задайте
`CORS_ORIGINS` в `.env` (примеры есть в `.env.example`).

## Следующие шаги: предлагаемые адреса, пока НЕ реализованы

| Шаг | Метод и адрес | Операция |
|---|---|---|
| 2 | `POST /api/tasks/{id}/questions` | Уточняющие вопросы |
| 2 | `POST /api/tasks/{id}/generate-card` | Карточка из ответов |
| 3 | `POST /api/tasks/{id}/confirm` | Подтверждение и рейтинг |
| 3 | `POST /api/tasks/{id}/publish` | Публикация без порога рейтинга |
| 4 | `GET /api/catalog?topic=retail&readiness=working` | Публичный каталог |
| 4 | `GET /api/catalog/{id}` | Только опубликованные сведения |
| 4 | `POST /api/tasks/{id}/proposals` | Предложение команды |
| 4 | `GET /api/tasks/{id}/proposals` | Отклики для владельца |
| 4 | `GET /api/my/proposals` | Отклики выбранной команды |
| 4 | `PATCH /api/proposals/{id}` | Ручное решение бизнеса |
| 4 | `POST /api/proposals/{id}/milestones` | Отправка этапа |
| 4 | `POST /api/milestones/{id}/confirm` | Подтверждение этапа и баллы |

Объект предложения: `id`, `task_id`, `team_id`, `idea`, `plan`, `timeline`,
`prototype_url`, `questions`, `status`, `created_at`, `decided_at`.
`prototype_url: null` означает отсутствие прототипа. Статусы: `submitted`, `selected`, `rejected`.

Объект этапа: `id`, `proposal_id`, `description`, `result_url`, `status`,
`points_awarded`, `created_at`, `confirmed_at`. Статусы: `submitted`, `confirmed`.
Поля рейтинга, статусов, времени и начислений всегда устанавливает сервер.
Форматы запросов будущих операций согласуем при их реализации; они не часть
работающего API v0.1. UI-заглушки должны быть явно отмечены как тестовые.
