# Sprofy/run.py (Версия ПОСЛЕ удаления ConversationHandler и очистки импортов)

# === BLOCK 1: Initial Imports ===
import asyncio
import logging
import signal
import sys
import typing  # Оставляем для typing.Optional, если используется где-то еще
from typing import Optional

from telegram import Update  # Оставляем, используется в type hints
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    # ConversationHandler, # УДАЛЕНО
    MessageHandler,
    filters,
)

try:
    from BehaviorEngine.engine import handle_update as engine_handle_update
except ImportError as e:
    logging.critical(f"CRITICAL: Failed to import BehaviorEngine: {e}", exc_info=True)
    print(f"CRITICAL: Failed to import BehaviorEngine: {e}", file=sys.stderr)
    raise
# === END BLOCK 1 ===


# === BLOCK 2: Configuration Loading ===
# --- Загрузка конфигурации ---
try:
    # Импорты старых состояний ConversationHandler УДАЛЕНЫ
    from config import BOT_TOKEN  # ADMIN_CHANNEL_ID если он используется где-то здесь

    if not BOT_TOKEN or "БОТ ТОКЕН ТЕЛЕГРАМ" in BOT_TOKEN:
        raise ValueError("Токен бота (BOT_TOKEN) не задан или не изменен в config.py!")
except (ImportError, KeyError, ValueError) as e:
    try:
        logging.basicConfig(level=logging.CRITICAL)
        logging.critical(f"Config error: {e}")
    except Exception:
        pass
    print(f"!!! КРИТИЧЕСКАЯ ОШИБКА: Проблема с файлом config.py: {e}", file=sys.stderr)
    print("Пожалуйста, проверьте наличие и корректность config.py.", file=sys.stderr)
    exit(1)
# === END BLOCK 2 ===


# === BLOCK 3: Logging Setup ===
logging.basicConfig(
    format=(
        "%(asctime)s - %(name)s - %(levelname)s - "
        "[%(filename)s:%(lineno)d] - %(message)s"
    ),
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot_main.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,
)
logging.getLogger("BehaviorEngine").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)
# === END BLOCK 3 ===


# === BLOCK 4: Handler and DB Imports ===
# --- Импорты обработчиков и БД ---
try:
    from database.models import close_database, initialize_database
    from handlers.admin import (
        ask_for_codes_file,
        ask_for_instructions_file,
        ask_for_scenario_file,
        handle_codes_file,
        handle_instructions_file,
        handle_scenario_file,
        view_instructions,
        view_registration_codes,
    )

    # Импорты старых обработчиков диалогов УДАЛЕНЫ
    from handlers.common_handlers import cancel  # Для команды /cancel
    from handlers.start import start  # Новый /start через BehaviorEngine
    from utils.error_handler import error_handler
    # from utils.message_utils import escape_md # Если escape_md не используется напрямую в run.py

    logger.info("Обработчики, утилиты и функции БД успешно импортированы.")

except ImportError as e:
    logger.critical(
        f"!!! КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать модуль! Ошибка: {e}",
        exc_info=True,
    )
    print(
        f"!!! КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать модуль! Ошибка: {e}",
        file=sys.stderr,
    )
    exit(1)
except Exception as e:
    logger.critical(
        f"!!! КРИТИЧЕСКАЯ ОШИБКА: Неизвестная ошибка при импорте: {e}", exc_info=True
    )
    print(
        f"!!! КРИТИЧЕСКАЯ ОШИБКА: Неизвестная ошибка при импорте: {e}", file=sys.stderr
    )
    exit(1)
# === END BLOCK 4 ===


# === BLOCK 5: Logger Configuration ===
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.INFO)
logging.getLogger("telegram.bot").setLevel(logging.INFO)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
# === END BLOCK 5 ===


# === BLOCK 6: Global 'application' and Shutdown Handler ===
application: Optional[Application] = None


async def shutdown(signal_number: typing.Union[int, str], frame) -> None:
    global application
    signal_name = signal_number
    if isinstance(signal_number, int):
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"Signal {signal_number}"
    logger.warning(
        f"Получен сигнал завершения {signal_name}, начинаем штатную остановку..."
    )
    if application and application.running:
        logger.info("Вызов процедур остановки application...")
        try:
            if application.updater and application.updater.running:
                logger.info("Вызов application.updater.stop()...")
                await application.updater.stop()
                logger.info("application.updater.stop() выполнен.")
            logger.info("Вызов application.stop()...")
            await application.stop()
            logger.info("application.stop() выполнен.")
            logger.info("Вызов application.shutdown()...")
            await application.shutdown()
            logger.info("application.shutdown() выполнен.")
        except Exception as app_shutdown_err:
            logger.error(
                f"Ошибка при штатной остановке application: {app_shutdown_err}",
                exc_info=True,
            )
    else:
        logger.warning("Объект application не найден или уже не запущен.")
    logger.info("Вызов close_database()...")
    try:
        await close_database()
        logger.info("close_database() выполнен.")
    except Exception as db_close_err:
        logger.error(f"Ошибка при вызове close_database: {db_close_err}", exc_info=True)
    logger.warning(
        "Работа бота должна быть завершена (обработчик сигнала завершил выполнение)."
    )


# === END BLOCK 6 ===


# === BLOCK 7: Setup Shutdown Handlers ===
def setup_shutdown_handlers() -> None:
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.error("Не удалось получить текущий цикл событий для настройки сигналов.")
        return
    signals_to_handle = (signal.SIGINT, signal.SIGTERM)
    for sig in signals_to_handle:
        try:
            loop.add_signal_handler(
                sig, lambda s=sig: asyncio.create_task(shutdown(s, None))
            )
            logger.info(f"Настроен обработчик для сигнала {sig.name}.")
        except (NotImplementedError, ValueError) as e:
            logger.warning(
                f"Не удалось настроить обработчик для {sig.name} в текущей системе: {e}"
            )
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при настройке обработчика для {sig.name}: {e}",
                exc_info=True,
            )
    logger.info("Настройка обработчиков сигналов завершения завершена.")


# === END BLOCK 7 ===


# === BLOCK 8: Main Async Function ===
async def main() -> None:
    global application
    logger.info(">>> Запуск основной функции main()")
    setup_shutdown_handlers()
    logger.info(">>> Вызов initialize_database()...")
    session_maker = await initialize_database()
    if not session_maker:
        logger.critical("!!! БД не инициализирована.")
        return
    logger.info("<<< initialize_database() успешно завершена.")
    logger.info(">>> Инициализация ApplicationBuilder...")
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    logger.info("<<< ApplicationBuilder завершен.")
    application.bot_data["session_maker"] = session_maker
    logger.info("Фабрика сессий БД добавлена в application.bot_data")

    # --- Старый Conversation Handler УДАЛЕН ---

    # --- Регистрация обработчиков В ПРАВИЛЬНОМ ПОРЯДКЕ ---
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.ALL & ~filters.COMMAND,
            engine_handle_update,
            block=False,
        ),
        group=0,
    )
    application.add_handler(
        CallbackQueryHandler(engine_handle_update, block=False), group=0
    )
    logger.info("Обработчик BehaviorEngine (engine_handle_update) добавлен в группу 0.")

    application.add_handler(CommandHandler("start", start), group=1)
    application.add_handler(CommandHandler("cancel", cancel), group=1)
    logger.info("Обработчики команд /start и /cancel добавлены в группу 1.")

    # === ГРУППА 3: Админские команды и загрузка файлов ===
    application.add_handler(
        CommandHandler("view_reg_codes", view_registration_codes), group=3
    )
    application.add_handler(
        CommandHandler("add_reg_codes_file", ask_for_codes_file), group=3
    )
    application.add_handler(
        CommandHandler("view_instructions", view_instructions), group=3
    )
    application.add_handler(
        CommandHandler("upload_instructions", ask_for_instructions_file), group=3
    )
    application.add_handler(
        CommandHandler("upload_scenario", ask_for_scenario_file), group=3
    )

    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.Document.MimeType("text/plain"),
            handle_codes_file,
        ),
        group=3,
    )
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.Document.MimeType("text/csv"),
            handle_instructions_file,
        ),
        group=3,
    )
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.Document.ALL, handle_scenario_file
        ),
        group=3,
    )
    logger.info("Админские обработчики и загрузчики файлов добавлены в группу 3.")

    application.add_error_handler(error_handler)
    logger.info("Обработчик ошибок error_handler добавлен.")

    try:
        logger.info(">>> Запуск инициализации и опроса обновлений...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("<<< Бот успешно запущен и получает обновления...")
        await asyncio.Future()
        logger.info("Получен сигнал на выход из ожидания asyncio.Future()")
    except Exception as e:
        logger.critical(f"Критическая ошибка в основном цикле: {e}", exc_info=True)
        await shutdown(f"Exception in main loop: {e}", None)
    finally:
        if application and application.running:
            logger.warning("Блок finally в main(): Попытка штатной остановки...")
            await shutdown("Reached finally in main", None)
    logger.info("<<< Функция main() завершила выполнение.")


# === END BLOCK 8 ===


# === BLOCK 9: Main Execution Block ===
if __name__ == "__main__":
    logger.info("================== ЗАПУСК БОТА ==================")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info(
            "Получено KeyboardInterrupt/SystemExit (завершение инициировано пользователем)."
        )
    except RuntimeError as e:
        if "Cannot close a running event loop" in str(
            e
        ) or "Event loop is closed" in str(e):
            logger.warning(
                f"Поймана ожидаемая ошибка RuntimeError event loop при завершении: {e}."
            )
        else:
            logger.critical(
                f"Критическая ошибка RuntimeError в asyncio.run(main): {e}",
                exc_info=True,
            )
    except Exception as e:
        logger.critical(
            f"Критическая ошибка верхнего уровня в __main__: {e}", exc_info=True
        )
    finally:
        logger.warning("Выполнение финального блока finally в __main__.")

    logger.info("================== БОТ ОСТАНОВЛЕН ==================")
# === END BLOCK 9 ===
