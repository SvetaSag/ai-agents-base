# Курс «Разработка и внедрение AI-агентов»

3 занятия. Код — маленькими поэтапными шагами: каждый шаг (Jupyter-ноутбук)
добавляет одну вещь к предыдущему. Подробный план — в [PLAN.md](PLAN.md).

| Занятие | Тема | Папка |
|---------|------|-------|
| 1 | LangChain + LangGraph | [lesson1_langchain_langgraph](lesson1_langchain_langgraph/README.md) |
| 2 | Интеграция: Telegram-бот + MCP | скоро |
| 3 | Мультиагентность, протокол A2A | скоро |

## Запуск занятия

Шаги — Jupyter-ноутбуки, ячейки запускаются по очереди.

```bash
cd lesson1_langchain_langgraph
uv sync
cp .env.example .env          # вписать OPENROUTER_API_KEY
uv run jupyter lab
```

## Сборка презентации

```bash
cd lesson1_langchain_langgraph/lecture
NODE_PATH=/opt/homebrew/lib/node_modules node build.js
```

`theme.js` в корне — общий стиль всех лекций (pptxgenjs).

Прошлая версия курса (5 занятий, проект mini-code) лежит в `_archive/`.
