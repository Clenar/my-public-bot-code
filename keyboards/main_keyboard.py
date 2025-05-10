# Sprofy/keyboards/main_keyboard.py (Исправленная версия v2)

# === BLOCK 1: Imports ===
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# === END BLOCK 1 ===


# === BLOCK 2: Start Keyboard ===
def create_start_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру с кнопкой 'Начать поиск мастера'."""
    keyboard = [
        # Текст кнопки и ее callback_data (уникальный идентификатор нажатия)
        [
            InlineKeyboardButton(  # Строка разбита для E501
                "🔎 Почати пошук майстра", callback_data="search_master"
            )
        ],
        # Сюда позже можно добавить другие кнопки главного меню,
        # например "О боте", "Помощь"
        # [InlineKeyboardButton("ℹ️ Про бота", callback_data="about")],
    ]
    return InlineKeyboardMarkup(keyboard)


# === END BLOCK 2 ===


# === BLOCK 3: Role Choice Keyboard === (НОВЫЙ БЛОК)
# Префиксы для callback_data, чтобы легко их различать
CALLBACK_ROLE_PREFIX = "role_choice:"


def create_role_choice_keyboard() -> InlineKeyboardMarkup:
    """Создает инлайн-клавиатуру с выбором роли Мастер/Клиент."""
    keyboard = [
        [
            # Текст кнопки и callback_data с префиксом и значением
            InlineKeyboardButton(
                "Я Мастер", callback_data=f"{CALLBACK_ROLE_PREFIX}master"
            ),
            InlineKeyboardButton(
                "Я Клиент", callback_data=f"{CALLBACK_ROLE_PREFIX}client"
            ),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# === END BLOCK 3 ===


# === BLOCK 4: Other commented examples ===
# --- Другие основные клавиатуры (добавим по мере необходимости) ---

# def create_main_menu_keyboard() -> InlineKeyboardMarkup:
#     """Клавиатура для кнопки 'Главное меню' (пример)"""
#     keyboard = [
#         [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")],
#     ]
#     return InlineKeyboardMarkup(keyboard)

# def create_cancel_keyboard() -> InlineKeyboardMarkup:
#     """Клавиатура для кнопки 'Отмена' (пример)"""
#     keyboard = [
#         [InlineKeyboardButton("❌ Скасувати", callback_data="cancel_action")],
#     ]
#     return InlineKeyboardMarkup(keyboard)

# def create_options_keyboard() -> InlineKeyboardMarkup:
#     """Пример клавиатуры опций, если нужна"""
#     keyboard = [
#         [InlineKeyboardButton("Опция 1", callback_data="option_1")],
#         [InlineKeyboardButton("Опция 2", callback_data="option_2")],
#         [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")],
#     ]
#     return InlineKeyboardMarkup(keyboard)
# === END BLOCK 4 ===
