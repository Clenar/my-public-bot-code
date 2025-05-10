# Sprofy/keyboards/services_keyboard.py
import logging
from typing import Optional  # <-- Импорт для исправления ошибки

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Импортируем список городов
try:
    from data.cities import CITIES
except ImportError:
    logging.warning(
        "Не найден список CITIES в data/cities.py. Используется список по умолчанию."
    )
    CITIES = ["Київ", "Львів", "Одеса", "Харків", "Дніпро"]  # Запасной вариант

logger = logging.getLogger(__name__)


# --- Клавиатура Городов ---
# Исправлен тип возвращаемого значения -> Optional[InlineKeyboardMarkup]
def create_city_keyboard(
    page: int = 0, cities_per_page: int = 8
) -> Optional[InlineKeyboardMarkup]:
    """Создает клавиатуру для выбора города с пагинацией."""
    if not CITIES:
        logger.warning("Список CITIES пуст или не загружен.")
        return None

    start_index = page * cities_per_page
    end_index = start_index + cities_per_page
    paginated_cities = CITIES[start_index:end_index]

    if not paginated_cities:
        return None

    keyboard = []
    for city in paginated_cities:
        keyboard.append([InlineKeyboardButton(city, callback_data=f"city_{city}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton("⬅️ Назад", callback_data=f"citypage_{page - 1}")
        )
    if end_index < len(CITIES):
        nav_buttons.append(
            InlineKeyboardButton("Вперед ➡️", callback_data=f"citypage_{page + 1}")
        )

    if nav_buttons:
        keyboard.append(nav_buttons)

    return InlineKeyboardMarkup(keyboard)


# --- Клавиатуры Услуг (Пока Заглушки) ---
def create_service_keyboard(level=1, parent_category=None) -> InlineKeyboardMarkup:
    logger.debug(
        f"Создание заглушки клавиатуры услуг: level={level}, parent={parent_category}"
    )
    keyboard = [
        [
            InlineKeyboardButton(
                "💅 Манікюр/педикюр (Тест)", callback_data="service_Манікюр"
            )
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def create_subservice_keyboard(category) -> InlineKeyboardMarkup:
    logger.debug(f"Создание заглушки клавиатуры подуслуг для {category}")
    keyboard = [
        [
            InlineKeyboardButton(
                "Покриття гель-лак (Тест)", callback_data="subservice_ГельЛак"
            )
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def create_subsubservice_keyboard(sub_category) -> InlineKeyboardMarkup:
    logger.debug(f"Создание заглушки клавиатуры под-подуслуг для {sub_category}")
    keyboard = [
        [InlineKeyboardButton("Дизайн (Тест)", callback_data="subsubservice_Дизайн")]
    ]
    return InlineKeyboardMarkup(keyboard)


def create_comment_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("✍️ Без коментаря", callback_data="skip_comment")],
        [InlineKeyboardButton("📸 Додати фото", callback_data="go_to_photo")],
    ]
    return InlineKeyboardMarkup(keyboard)


def create_photo_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🚫 Пропустити фото", callback_data="skip_photo")],
        [InlineKeyboardButton("✅ Відправити заявку", callback_data="finish_order")],
    ]
    return InlineKeyboardMarkup(keyboard)
