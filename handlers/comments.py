# Sprofy/handlers/comments.py (Исправленная версия)
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from config import FINISH, PHOTO

logger = logging.getLogger(__name__)


async def handle_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает введенный пользователем комментарий."""
    user = update.effective_user
    # Строка лога разбита для E501
    logger.warning(
        f"Обработчик handle_comment еще не реализован полностью. "
        f"User: {user.id}, Text: {update.message.text[:20]}"
    )
    await update.message.reply_text(
        "Коментар отримано (детальна логіка в розробці). Перехід до фото..."
    )
    # TODO: Сохранить комментарий в user_data или БД
    # TODO: Запросить фото или предложить пропустить/завершить
    return PHOTO  # Пример перехода к шагу фото


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает отправленное фото или нажатие кнопки 'Добавить фото'."""
    user = update.effective_user
    if update.message and update.message.photo:
        # Строка лога разбита для E501
        logger.warning(
            "Обработчик handle_photo (фото) еще не реализован полностью. "
            f"User: {user.id}"
        )
        await update.message.reply_text(
            "Фото отримано (детальна логіка в розробці). Завершення..."
        )
        # TODO: Сохранить file_id фото в user_data или БД
        # TODO: Показать финальное сообщение перед завершением
        return FINISH  # Пример завершения после фото

    elif update.callback_query:  # Обработка нажатия кнопки "Добавить фото"
        query = update.callback_query
        await query.answer()
        # Строка лога разбита для E501
        logger.warning(
            "Обработчик handle_photo (кнопка 'Добавить фото') еще не реализован. "
            f"User: {user.id}, Data: {query.data}"
        )
        await query.edit_message_text("Очікую фото...")
        return PHOTO  # Остаемся ждать фото

    # Сюда не должны попадать, но на всякий случай
    logger.warning(f"Неожиданное обновление в handle_photo для user {user.id}")
    return ConversationHandler.END


async def skip_comment_or_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Обрабатывает нажатие кнопок 'Пропустить комментарий' или 'Пропустить фото'."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    # Строка лога разбита для E501
    logger.warning(
        f"Обработчик skip_comment_or_photo еще не реализован полностью. "
        f"User: {user.id}, Data: {query.data}"
    )
    if query.data == "skip_comment":
        await query.edit_message_text(
            "Пропуск коментаря (детальна логіка в розробці). Перехід до фото..."
        )
        # TODO: Отправить сообщение с запросом фото или кнопкой "Завершить без фото"
        return PHOTO  # Пример перехода к шагу фото
    elif query.data == "skip_photo":
        await query.edit_message_text(
            "Пропуск фото (детальна логіка в розробці). Завершення..."
        )
        # Тут по идее нужно показать финальное сообщение и кнопку отправки?
        # Пока просто завершим
        # TODO: Показать финальное сообщение перед завершением
        return ConversationHandler.END  # Пример

    logger.warning(f"Неизвестные данные в skip_comment_or_photo: {query.data}")
    return ConversationHandler.END  # На всякий случай
