# Sprofy/handlers/finish.py
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

logger = logging.getLogger(__name__)


async def finish_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает диалог и отправляет заявку администратору (ЗАГЛУШКА)."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    logger.warning(
        f"Обработчик finish_application еще не реализован полностью. User: {user.id}"
    )
    await query.edit_message_text(
        "Заявка відправлена (детальна логіка в розробці). Дякуємо!"
    )
    context.user_data.clear()  # Очищаем данные в конце
    return ConversationHandler.END  # Завершаем диалог
