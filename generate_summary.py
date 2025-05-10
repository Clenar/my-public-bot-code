# generate_summary.py
import datetime
import pathlib
import subprocess

# --- Настройки ---
OUTPUT_FILENAME = "PROJECT_SUMMARY.md"
ROADMAP_FILENAME = "ROADMAP.md"
PROJECT_ROOT = pathlib.Path(
    __file__
).parent.resolve()  # Корень проекта - папка, где лежит скрипт

# Папки и файлы для исключения из дерева файлов (на основе .gitignore и здравого смысла)
EXCLUDE_DIRS = {".git", ".idea", ".vscode", "venv", "__pycache__"}
EXCLUDE_FILES = {
    ".DS_Store",
    OUTPUT_FILENAME,
    ROADMAP_FILENAME,
    "generate_summary.py",  # Сам скрипт
    "bot_debug.log",
    "load_services.log",  # Логи
}
EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".log",
    ".db",
    ".sqlite3",
}  # Расширения для исключения

# Описания ключевых файлов/папок (строки разбиты для E501)
KEY_FILES_DESC = {
    "run.py": "Главный скрипт запуска бота, содержит основную логику "
    "Application и ConversationHandler.",
    "config.py": "Конфигурационный файл (ВАЖНО: должен быть в .gitignore!). "
    "Хранит токены, ключи, настройки БД.",
    "database/models.py": "Определение всех моделей базы данных через SQLAlchemy "
    "(таблицы UserData, Masters, Services и т.д.).",
    "load_services_to_db.py": "Вспомогательный скрипт для загрузки данных об "
    "услугах из CSV в БД (использовался один раз).",
    "handlers/": "Папка с обработчиками сообщений и колбэков Telegram "
    "(разделены по логике: start, city, service и т.д.).",
    "keyboards/": "Папка с функциями для генерации Telegram-клавиатур.",
    "utils/": "Папка для вспомогательных функций (например, error_handler).",
    "data/": "Папка для статичных данных (например, список городов - "
    "если используется).",
    "ROADMAP.md": "Файл с планом разработки проекта (Roadmap).",
    ".gitignore": "Файл конфигурации Git для игнорирования файлов и папок.",
    "requirements.txt": "Список зависимостей Python проекта.",
    "PROJECT_SUMMARY.md": "Автоматически генерируемый файл-сводка о проекте "
    "(этот файл).",
}
MAX_TREE_DEPTH = 4  # Максимальная глубина дерева файлов для отображения
# --- Конец Настроек ---


def get_git_info():
    """Получает информацию о последнем коммите Git."""
    try:
        commit_hash = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=PROJECT_ROOT,
        ).stdout.strip()

        commit_info_raw = subprocess.run(
            ["git", "log", "-1", "--pretty=%B%n[%an | %ad]", "--date=iso"],
            capture_output=True,
            text=True,
            check=True,
            cwd=PROJECT_ROOT,
        ).stdout.strip()

        # Разделяем сообщение и автора/дату
        parts = commit_info_raw.split("\n")
        commit_message = (
            "\n".join(parts[:-1]).strip() if len(parts) > 1 else parts[0]
        )  # Все строки кроме последней
        commit_author_date = (
            parts[-1].strip() if len(parts) > 1 else "[No Author/Date Info]"
        )

        return {
            "hash": commit_hash,
            "message": commit_message,
            "author_date": commit_author_date,
        }
    except FileNotFoundError:
        # Строка ошибки разбита для E501
        return {
            "error": "Команда 'git' не найдена. Убедитесь, что Git установлен "
            "и доступен в PATH."
        }
    except subprocess.CalledProcessError as e:
        return {"error": f"Ошибка выполнения команды git: {e.stderr.strip()}"}
    except Exception as e:
        return {"error": f"Неизвестная ошибка при получении информации Git: {e}"}


def generate_file_tree(start_path, max_depth=MAX_TREE_DEPTH):
    """Генерирует строковое представление дерева файлов."""
    tree = []
    start_path = pathlib.Path(start_path)

    def _walk_dir(current_path, depth, prefix=""):
        if depth > max_depth:
            tree.append(f"{prefix}...")  # Указываем, что есть что-то глубже
            return

        # Комментарий разбит для E501
        # Используем list() чтобы можно было модифицировать при итерации
        # (хотя здесь не модифицируем)
        items = list(current_path.iterdir())
        # Сортируем: сначала папки, потом файлы, все по алфавиту
        items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))

        pointers = ["├── "] * (len(items) - 1) + ["└── "]

        for pointer, item in zip(pointers, items):
            # Пропускаем исключенные папки и файлы
            if (
                item.name in EXCLUDE_DIRS
                or item.name in EXCLUDE_FILES
                or item.suffix in EXCLUDE_EXTENSIONS
            ):
                continue
            # Пропускаем саму папку venv (на всякий случай, если она не в EXCLUDE_DIRS)
            if item.is_dir() and item.name == "venv":
                continue

            tree.append(f"{prefix}{pointer}{item.name}{'/' if item.is_dir() else ''}")

            if item.is_dir():
                extension = "│   " if pointer == "├── " else "    "
                # Рекурсивный вызов для подпапки
                _walk_dir(item, depth + 1, prefix + extension)

    # Добавляем корень в начало дерева
    tree.insert(0, f"{start_path.name}/")
    _walk_dir(start_path, 1)
    return "\n".join(tree)


def main():
    """Основная функция генерации сводки."""
    print("Генерация сводки проекта...")

    # 1. Получаем информацию Git
    print("- Получение информации Git...")
    git_info = get_git_info()
    git_section = "## Информация о последнем коммите Git\n\n"
    if "error" in git_info:
        git_section += f"*Не удалось получить информацию: {git_info['error']}*\n"
    else:
        git_section += f"- **Хеш:** `{git_info['hash']}`\n"
        git_section += f"- **Автор и дата:** {git_info['author_date']}\n"
        git_section += f"- **Сообщение:**\n```\n{git_info['message']}\n```\n"

    # 2. Генерируем дерево файлов
    print("- Генерация дерева файлов...")
    try:
        file_tree_section = f"## Структура Проекта (до {MAX_TREE_DEPTH} ур.)\n\n```\n"
        file_tree_section += generate_file_tree(PROJECT_ROOT)
        file_tree_section += "\n```\n"
    except Exception as e:
        file_tree_section = (
            f"## Структура Проекта\n\n*Не удалось сгенерировать дерево файлов: {e}*\n"
        )

    # 3. Описания ключевых файлов
    print("- Формирование описаний ключевых файлов...")
    key_files_section = "## Ключевые Файлы и Папки\n\n"
    for path, desc in KEY_FILES_DESC.items():
        # Проверяем существование файла/папки для актуальности
        actual_path = PROJECT_ROOT / path
        exists_marker = "✅" if actual_path.exists() else "❌"
        key_files_section += f"- `{path}` {exists_marker}: {desc}\n"

    # 4. Читаем Roadmap
    print(f"- Чтение {ROADMAP_FILENAME}...")
    roadmap_section = f"## Roadmap (из {ROADMAP_FILENAME})\n\n"
    try:
        with open(PROJECT_ROOT / ROADMAP_FILENAME, encoding="utf-8") as f:
            roadmap_content = f.read()
        # Добавляем как блок кода Markdown для сохранения форматирования
        roadmap_section += f"```markdown\n{roadmap_content}\n```\n"
    except FileNotFoundError:
        roadmap_section += f"*Файл {ROADMAP_FILENAME} не найден.*\n"
    except Exception as e:
        roadmap_section += f"*Ошибка чтения файла {ROADMAP_FILENAME}: {e}*\n"

    # 5. Собираем и записываем файл
    print(f"- Запись в {OUTPUT_FILENAME}...")
    summary_content = f"""# Сводка по Проекту Sprofy

*Автоматически сгенерировано: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*

---
{git_section}
---
{file_tree_section}
---
{key_files_section}
---
{roadmap_section}
"""
    try:
        with open(PROJECT_ROOT / OUTPUT_FILENAME, "w", encoding="utf-8") as f:
            f.write(summary_content)
        print(f"Сводка успешно сохранена в {OUTPUT_FILENAME}")
    except Exception as e:
        print(f"Ошибка записи файла {OUTPUT_FILENAME}: {e}")


if __name__ == "__main__":
    main()
