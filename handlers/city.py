# Sprofy/handlers/city.py (Исправленная версия)
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import CHOOSE_SERVICE  # Следующее состояние

# Импорт клавиатуры УСЛUG (а не городов!)
from keyboards.services_keyboard import create_service_keyboard

logger = logging.getLogger(__name__)


async def city_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор города."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    # Получаем выбранный город из callback_data (убираем префикс "city_")
    chosen_city = (
        query.data.split("_", 1)[1] if query.data.startswith("city_") else "Невідомо"
    )

    logger.info(f">>> User {user.id} выбрал город: {chosen_city}")
    # Сохраняем выбор пользователя
    context.user_data["chosen_city"] = chosen_city

    message_text = f"Ви обрали місто: {chosen_city}.\nТепер оберіть категорію послуг:"
    # Генерируем клавиатуру УСЛУГ для следующего шага
    reply_markup = create_service_keyboard()

    try:
        await query.edit_message_text(text=message_text, reply_markup=reply_markup)
        logger.debug(
            f"Сообщение {query.message.message_id} отредактировано для выбора услуги"
        )
    except Exception as e:
        logger.warning(f"Не удалось отредактировать сообщение в city_choice: {e}")

    logger.info("<<< Вышел из функции city_choice (возвращаем CHOOSE_SERVICE)")
    return CHOOSE_SERVICE  # Переходим к выбору услуги


# Заглушка для обработчика кнопки "Сменить город",
# если она используется вне ConversationHandler (Комментарий разбит E501)
# Эта функция здесь не используется самим диалогом,
# но может быть нужна для отдельной кнопки (Комментарий разбит E501)
async def change_city_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для кнопки смены города (заглушка)."""
    query = update.callback_query
    if query:
        await query.answer("Функція зміни міста ще не реалізована.")
    logger.warning("Вызван необработанный обработчик change_city_callback")
    # return CHOOSE_CITY # Возможно, нужно вернуть это состояние?
