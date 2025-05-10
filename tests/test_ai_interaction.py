# tests/test_ai_interaction.py
import asyncio
import logging
import os
import sys
import typing

# Добавлены импорты sqlalchemy (исправлено F821, E402) и отсортировано (I001)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Добавляем корень проекта в путь (этот код должен идти ПОСЛЕ всех импортов)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Импорты из проекта (отсортировано I001)
importerror = False
session_maker: typing.Optional[async_sessionmaker[AsyncSession]] = None
# ^^^ Аннотация типа исправлена (добавлены импорты выше), строка разбита (E501)

try:
    from ai.interaction import generate_text_response
    from database.models import close_database, initialize_database
except ImportError as e:
    logging.error(f"!!! ОШИБКА ИМПОРТА: {e}")
    importerror = True
except Exception as e:
    logging.error(f"!!! Неожиданная ошибка при импорте: {e}", exc_info=True)
    importerror = True


# Настройка логирования (после добавления пути к проекту и импортов)
logging.basicConfig(
    level=logging.DEBUG,
    # Строка format разбита для E501
    format=(
        "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] "
        "- %(message)s"
    ),
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def run_test():
    """Запускает тестовый вызов AI и закрывает БД."""
    global session_maker
    if importerror:
        logging.error("Тест не может быть запущен из-за ошибки импорта.")
        return

    logging.info("Инициализация БД для теста...")
    session_maker = await initialize_database()
    if not session_maker:
        logging.error("Не удалось инициализировать БД.")
        return
    logging.info("БД инициализирована, фабрика сессий получена.")

    # --- Параметры теста: Формируем ИСТОРИЮ сообщений ---
    test_messages = [
        {"role": "user", "content": "Какая самая большая планета в Солнечной системе?"}
        # Можно добавить больше:
        # {"role": "assistant", "content": "Самая большая планета - Юпитер."},
        # {"role": "user", "content": "А какая вторая по величине?"}
    ]
    # =====================================================
    test_instruction_key = "search_assistant_prompt"  # Ключ, который должен быть в БД
    test_user_lang_code = "ru"  # Язык для поиска инструкции
    fallback_msg = "Веди себя как обычный чат-бот."
    # --- Конец параметров ---

    print("-" * 30)
    logging.info(f"Отправка истории в AI: {test_messages}")
    # Строка лога разбита для E501
    logging.info(
        f"Используем ключ инструкции: '{test_instruction_key}', "
        f"язык: '{test_user_lang_code}'"
    )
    print("-" * 30)

    response = None
    # Убедимся, что session_maker был инициализирован
    if not session_maker:
        logging.error("Фабрика сессий не была инициализирована перед использованием.")
        return

    async with session_maker() as session:
        logging.debug("Создана сессия БД...")
        try:
            # Передаем список messages вместо prompt
            response = await generate_text_response(
                messages=test_messages,  # <--- Передаем историю
                instruction_key=test_instruction_key,
                user_lang_code=test_user_lang_code,
                fallback_system_message=fallback_msg,
                session=session,
            )
        except Exception as e:
            logging.error(
                f"Ошибка во время вызова generate_text_response: {e}", exc_info=True
            )
        logging.debug("Сессия БД автоматически закрыта.")

    print("-" * 30)
    if response:
        logging.info("Получен ответ AI:")
        print(response)
    else:
        logging.error("!!! Не удалось получить ответ от AI.")
    print("-" * 30)

    logging.info("Завершение теста, закрытие БД...")
    await close_database()
    logging.info("Соединение с БД (движок) закрыто.")


if __name__ == "__main__":
    logging.info("Запуск тестового скрипта ai/interaction...")
    try:
        asyncio.run(run_test())
    except Exception as e:
        logging.critical(f"Критическая ошибка в run_test: {e}", exc_info=True)
    finally:
        logging.info("Тестовый скрипт завершил работу.")
