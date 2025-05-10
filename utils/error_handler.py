# Sprofy/utils/error_handler.py (Исправленная версия v2)
import html  # noqa: F401 - Оставлен для раскомментирования блока ниже
import logging
import traceback  # noqa: F401 - Оставлен для раскомментирования блока ниже

# Импорты Telegram Bot API
from telegram import Update  # noqa: F401 - Оставлен для раскомментирования блока ниже

# from telegram.constants import ParseMode # <- Не нужен, пока блок закомментирован
from telegram.ext import ContextTypes

# ---------------------------------------------------------

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирует ошибки и опционально отправляет сообщение разработчику."""

    err = context.error
    if err is None:
        logger.warning("Обработчик ошибок вызван с context.error == None")
        return

    # Логируем исключение с полным traceback уровнем ERROR
    logger.error("Исключение при обработке обновления:", exc_info=err)

    # --- Блок отправки traceback разработчику (можно раскомментировать) ---
    # Важно: Для раскомментирования потребуются импорты выше с noqa: F401
    # и импорт ADMIN_CHANNEL_ID из config.py, а также ParseMode.
    #
    # tb_list = traceback.format_exception(None, err, err.__traceback__)
    # tb_string = "".join(tb_list)
    # update_str = update.to_dict() if isinstance(update, Update) else str(update)
    # # Строка caption разбита для E501
    # caption = (
    #     f"Error: {html.escape(str(err))}\\n\\nUpdate:\n"
    #     f"<pre>{html.escape(str(update_str))}</pre>\\n\\n"
    # )
    # message = (
    #     f"Произошло исключение:\n"
    #     # Показываем конец traceback, обрезанный до лимита Telegram
    #     f"<pre>{html.escape(tb_string[-3500:])}</pre>"
    # )
    # try:
    #     from config import ADMIN_CHANNEL_ID
    #     await context.bot.send_message(
    #         chat_id=ADMIN_CHANNEL_ID, text=f"{caption}{message}",
    #         parse_mode=ParseMode.HTML
    #     )
    # except ImportError:
    #     logger.error("ADMIN_CHANNEL_ID не найден в config.py для отправки ошибки.")
    # except Exception as send_err:
    #     logger.error(
    #         f"Не удалось отправить traceback ошибки разработчику: {send_err}"
    #         )
    # --- Конец блока отправки разработчику ---

    # Обработка конкретных ошибок (можно добавить логику позже)
    # Например:
    # from telegram.error import TimedOut, NetworkError, BadRequest # Нужны импорты
    # if isinstance(err, TimedOut):
    #     logger.warning("Timeout error detected.")
    # elif isinstance(err, NetworkError):
    #     logger.warning("Network error detected.")
    # elif isinstance(err, BadRequest):
    #     logger.warning(f"Telegram API BadRequest: {err}")
    # else:
    #     # Неизвестная ошибка (уже залогирована выше с traceback)
    #     pass
