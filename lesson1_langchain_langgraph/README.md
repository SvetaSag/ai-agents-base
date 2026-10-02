# Занятие 1 — LangChain + LangGraph, по шагам

Каждый ноутбук — один шаг. Шаг берёт идеи предыдущего и добавляет **одну**
новую вещь. Ячейки запускаются по очереди — видно, что происходит на
каждом этапе.

## Запуск

```bash
uv sync
cp .env.example .env     # вписать OPENROUTER_API_KEY (и при желании MODEL)
uv run jupyter lab       # или открыть папку в VS Code / Cursor и выбрать kernel .venv
```

**VS Code / Cursor не видит ядро?** Редактор ищет `.venv` только в корне
открытой папки. Либо откройте именно `lesson1_langchain_langgraph` как
папку, либо зарегистрируйте окружение как именованное ядро:

```bash
.venv/bin/python -m ipykernel install --user --name ai-agents-lesson1 --display-name "AI agents · lesson 1 (.venv)"
```

и выберите его: *Выбрать ядро → Выбрать другое ядро → Ядро Jupyter →
AI agents · lesson 1 (.venv)*. Удалить: `jupyter kernelspec uninstall ai-agents-lesson1`.

## Шаги

| Ноутбук | Что нового | Что смотреть |
|---------|------------|--------------|
| `01_first_call` | ChatOpenAI → OpenRouter, `.invoke`, токены | ответ — объект `AIMessage`, `usage_metadata` |
| `02_chat` | история сообщений (System/Human/AI), стриминг `.stream` | без истории модель не знает имя, с историей — знает |
| `03_structured_output` | ответ как Pydantic-объект, `with_structured_output` | `Task(priority='high', …)` |
| `04_tools` | `@tool`, JSON-схема, `bind_tools`, `tool_calls`, ToolMessage | что именно видит модель + один раунд по шагам |
| `05_agent_loop` | второй инструмент + цикл «модель → инструменты → модель» | агент сам делает `list_files → read_file` |
| `06_langgraph` | тот же агент как граф: State, Node, Edge; `create_agent` | схема графа, шаги узлов, граф `create_agent` той же формы |
| `07_memory` | SQLite-checkpointer, `thread_id` | «перезапущенный» граф помнит, другая нить — нет |
| `08_human_in_the_loop` | `write_file`/`run_command` + `interrupt` → `resume("y"/"n")` | граф стоит на паузе между ячейками |

```
01 вызов → 02 чат → 03 структура → 04 инструмент → 05 цикл (= агент)
→ 06 граф → 07 память → 08 человек в контуре
```

## Инструменты

`tools.py` — общие инструменты для ноутбуков 05–08. `@tool(parse_docstring=True)`
строит JSON-схему для модели: имя функции → `name`, докстринг → `description`,
type hints и раздел `Args:` → `parameters` с описанием каждого аргумента.
В `04_tools` эта схема печатается целиком.

## Заметки

- Инструменты работают относительно текущей директории (папка занятия).
  `08_human_in_the_loop` работает в отдельной `playground/` — её можно
  удалять, ноутбук создаёт её заново.
- `read_file` не отдаёт `.env`, а `list_files` скрывает dot-файлы — секреты
  не уходят в модель.
- `07_memory` пишет `memory.sqlite` и стирает его в начале, чтобы демо
  начиналось с чистого листа.
