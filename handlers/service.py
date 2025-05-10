# Sprofy/handlers/service.py (Исправленная версия)
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import CHOOSE_SUBSERVICE, CHOOSE_SUBSUBSERVICE, COMMENT

logger = logging.getLogger(__name__)


async def service_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор основной услуги (заглушка)."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    # Строка лога разбита для E501
    logger.warning(
        "Обработчик service_choice еще не реализован полностью. "
        f"User: {user.id}, Data: {query.data}"
    )
    await query.edit_message_text(
        "Обрано послугу (детальна логіка в розробці). Перехід до підпослуг..."
    )
    # TODO: Сохранить выбор, сгенерировать клавиатуру под-услуг
    return CHOOSE_SUBSERVICE  # Пример


async def subservice_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор подуслуги (заглушка)."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    # Строка лога разбита для E501
    logger.warning(
        "Обработчик subservice_choice еще не реализован полностью. "
        f"User: {user.id}, Data: {query.data}"
    )
    await query.edit_message_text(
        "Обрано підпослугу (детальна логіка в розробці). " "Перехід до під-підпослуг..."
    )
    # TODO: Сохранить выбор, сгенерировать клавиатуру под-под-услуг
    return CHOOSE_SUBSUBSERVICE  # Пример


async def subsubservice_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обрабатывает выбор под-подуслуги (заглушка)."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    # Строка лога разбита для E501
    logger.warning(
        "Обработчик subsubservice_choice еще не реализован полностью. "
        f"User: {user.id}, Data: {query.data}"
    )
    await query.edit_message_text(
        "Обрано фінальну послугу (детальна логіка в розробці). "
        "Перехід до коментаря..."
    )
    # TODO: Сохранить финальный выбор, запросить комментарий/фото
    return COMMENT  # Пример
