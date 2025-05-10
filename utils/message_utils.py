# utils/message_utils.py

# === BLOCK 1: Imports === (Добавлен logging)
import logging  # <-- ДОБАВЛЕН ЭТОТ ИМПОРТ
import typing

# === END BLOCK 1 ===


# === BLOCK 2: MarkdownV2 Escaper === (Исправленная и финальная версия)
def escape_md(
    text: typing.Optional[typing.Any],
    version: int = 2,
    entity_type: typing.Optional[str] = None,
) -> str:
    """
    Helper function to escape text for MarkdownV2.
    Handles special characters including '.', '!', '-', '=', etc. and backslashes.

    Args:
        text: The text to escape.
        version: Markdown version (currently only 2 supported by bot API).
        entity_type: For escaping only inside specific entities like 'pre' or 'code'
                     (currently not used for full escaping).
    """
    if text is None:
        return ""
    text = str(text)  # Убедимся, что работаем со строкой

    if version == 2:
        # Символы для экранирования в MarkdownV2 согласно документации Telegram Bot API
        # и распространенным проблемам (например, с точкой)
        escape_chars = r"_*[]()~`>#+-=|{}.!"

        # Экранируем сначала сам символ бэкслэша, чтобы не удвоить экранирование позже
        text = text.replace("\\", "\\\\")

        # Экранируем остальные спецсимволы
        # Пока не делаем исключений для 'pre' или 'code' при полном экранировании
        for char in escape_chars:
            text = text.replace(char, f"\\{char}")

        return text
    else:
        # Логируем предупреждение, если запрошена другая версия Markdown
        # Теперь logging будет работать, так как он импортирован
        logger = logging.getLogger(__name__)  # Получаем логгер
        logger.warning(
            f"Unsupported Markdown version {version} requested for escaping."
        )
        return text  # Возвращаем текст без изменений


# === END BLOCK 2 ===

# --- Сюда можно добавлять другие утилиты для работы с сообщениями ---
