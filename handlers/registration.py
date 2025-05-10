# handlers/registration.py (Исправленная версия)

# === BLOCK 1: Imports ===
import logging
import typing

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

# Импорты из других модулей
try:
    from ai.interaction import generate_text_response  # Функция вызова AI
    from config import (
        REGISTER_ASK_CITY,
        REGISTER_ASK_SERVICES,  # Оставлен F401, т.к. используется ниже
        REGISTER_CONFIRM_CITY,
    )

    # Состояния
    from database.models import UserData  # Модель пользователя для получения языка
except ImportError as e:
    # Используем имя логгера текущего модуля
    logging.getLogger(__name__).critical(
        f"Критическая ошибка импорта в registration.py: {e}", exc_info=True
    )
    raise

# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
# === END BLOCK 2 ===


# === BLOCK 3: City Confirmation Keyboard ===
# Префикс для callback_data кнопки подтверждения города
CALLBACK_CONFIRM_CITY_PREFIX = "confirm_city:"


def create_city_confirm_keyboard(city_name: str) -> InlineKeyboardMarkup:
    """Создает инлайн-клавиатуру с кнопкой подтверждения города."""
    keyboard = [
        [
            # В callback_data передаем распознанное имя города
            InlineKeyboardButton(
                f"✅ Так, це {city_name}",
                callback_data=f"{CALLBACK_CONFIRM_CITY_PREFIX}{city_name}",
            )
        ],
        # Можно добавить кнопку "Ввести інше місто"? Пока нет.
    ]
    return InlineKeyboardMarkup(keyboard)


# === END BLOCK 3 ===


# === BLOCK 4: handle_city_input (РЕАЛИЗОВАННАЯ ВЕРСИЯ) ===
async def handle_city_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает ввод города от Мастера, используя AI для интерпретации и валидации.
    """
    if not update.message or not update.message.text:  # Проверка наличия сообщения
        logger.warning("handle_city_input вызван без текстового сообщения.")
        return REGISTER_ASK_CITY  # Остаемся в том же состоянии

    user = update.effective_user
    user_text = update.message.text
    # Удалена неиспользуемая переменная chat_id (F841)
    # chat_id = update.effective_chat.id
    logger.info(f"[REGISTRATION] User {user.id} ввел текст для города: '{user_text}'")

    session_maker: typing.Optional[async_sessionmaker[AsyncSession]] = (
        context.bot_data.get("session_maker")
    )
    if not session_maker:  # Стандартная проверка сессии
        logger.error(
            f"Фабрика сессий не найдена в handle_city_input для user {user.id}"
        )
        await update.message.reply_text(
            "Вибачте, технічна помилка (сесія). Спробуйте /start."
        )
        return ConversationHandler.END

    # Получаем пользователя для языка
    db_user: typing.Optional[UserData] = None
    try:
        async with session_maker() as temp_session:
            db_user = await temp_session.get(UserData, user.id)
        if not db_user:
            # Используем стандартный Exception, т.к. это не ошибка БД, а логики
            raise ValueError(f"Не удалось получить пользователя {user.id} из БД")
    except Exception as e:
        logger.error(
            f"Ошибка получения пользователя {user.id} в handle_city_input: {e}",
            exc_info=True,
        )
        await update.message.reply_text(
            "Вибачте, помилка бази даних. Спробуйте /start."
        )
        return ConversationHandler.END

    # Вызываем AI с промптом interpret_and_validate_city
    # Строка лога разбита для E501
    logger.info(
        f"Вызов AI (prompt 'interpret_and_validate_city') для user {user.id} "
        f"с текстом '{user_text}'"
    )
    ai_response: typing.Optional[str] = None
    prompt_key = "interpret_and_validate_city"

    try:
        # Собираем историю (минимальную)
        ai_last_question = context.user_data.get(
            "registration_last_question", "В каком городе вы работаете?"
        )
        history_for_ai = [
            {"role": "assistant", "content": ai_last_question},
            {"role": "user", "content": user_text},
        ]

        async with session_maker() as session:
            ai_response = await generate_text_response(
                messages=history_for_ai,
                instruction_key=prompt_key,
                user_reply_for_format=user_text,  # Подставляем ответ в промпт
                user_lang_code=db_user.language_code,
                session=session,
                # fallback_system_message="Не удалось загрузить промпт..."
            )
    except Exception as ai_error:
        logger.error(
            f"Ошибка при вызове AI в handle_city_input для user {user.id}: {ai_error}",
            exc_info=True,
        )
        ai_response = None

    # Обрабатываем ответ AI
    if ai_response:
        logger.debug(f"Ответ AI на город для user {user.id}: '{ai_response}'")
        response_text = ai_response.strip()

        # Проверяем, вернул ли AI метку CITY_FOUND:
        if response_text.startswith("CITY_FOUND:"):
            try:
                # Парсим результат: CITY_FOUND: Город | Страна | Регион
                parts_str = response_text.split("CITY_FOUND:")[1].strip()
                parts = [p.strip() for p in parts_str.split("|")]
                city_name = parts[0]
                country_name = parts[1] if len(parts) > 1 else "N/A"
                region_name = parts[2] if len(parts) > 2 else "N/A"

                if not city_name:  # Если AI вернул метку, но пустой город
                    raise ValueError("AI вернул CITY_FOUND, но имя города пустое.")

                # Строка лога разбита для E501
                logger.info(
                    f"AI распознал город '{city_name}' для user {user.id}. "
                    "Отправляем подтверждение."
                )
                # Сохраняем распознанный город в контекст для следующего шага
                context.user_data["registration_city_pending"] = city_name
                context.user_data["registration_country_pending"] = country_name
                context.user_data["registration_region_pending"] = region_name

                # Формируем сообщение и клавиатуру
                confirmation_message = (
                    f"Здається, ви вказали місто: **{city_name}** ({country_name}).\n"
                    f"Це вірно?"
                )
                reply_markup = create_city_confirm_keyboard(city_name)
                await update.message.reply_text(
                    text=confirmation_message,
                    reply_markup=reply_markup,
                    parse_mode="Markdown",  # Используем Markdown для **
                )

                return REGISTER_CONFIRM_CITY  # Переходим к состоянию подтверждения

            except Exception as parse_error:
                # Если AI вернул CITY_FOUND, но в неправильном формате
                # Строка лога разбита для E501
                logger.error(
                    f"Ошибка парсинга ответа AI '{response_text}' от user "
                    f"{user.id}: {parse_error}"
                )
                await update.message.reply_text(
                    "Не вдалося обробити відповідь AI. Спробуйте назвати місто ще раз."
                )
                return REGISTER_ASK_CITY  # Возвращаемся к запросу города
        else:
            # AI сгенерировал текстовый ответ (уточнение/парирование)
            # Строка лога разбита для E501
            logger.info(
                "AI сгенерировал текстовый ответ на ввод города для user "
                f"{user.id}. Отправляем его."
            )
            await update.message.reply_text(response_text)
            # Сохраняем вопрос AI для возможного использования в следующем запросе
            context.user_data["registration_last_question"] = response_text
            return REGISTER_ASK_CITY  # Остаемся в том же состоянии, ждем новой попытки

    else:
        # AI не ответил или произошла ошибка
        # Строка лога разбита для E501
        logger.error(
            f"AI не вернул ответ в handle_city_input для user {user.id}. "
            "Отправляем fallback."
        )
        # Строка ответа разбита для E501
        await update.message.reply_text(
            "Вибачте, сталася помилка обробки вашого запиту. "
            "Спробуйте назвати місто ще раз."
        )
        return REGISTER_ASK_CITY  # Остаемся в том же состоянии


# === END BLOCK 4 ===


# === BLOCK 5: handle_city_button === (Перенумерован)
async def handle_city_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает нажатие кнопки подтверждения города.
    """
    query = update.callback_query
    user = update.effective_user
    if not user:  # Добавлена проверка user
        logger.warning("Не удалось определить пользователя в handle_city_button")
        if query:
            await query.answer("Не удалось определить пользователя", show_alert=True)
        return ConversationHandler.END

    user_id = user.id
    if query:
        await query.answer()  # Отвечаем на callback
    else:
        logger.warning("handle_city_button вызван без query")
        return ConversationHandler.END  # Не должно происходить

    callback_data = query.data
    # Строка лога разбита для E501
    logger.info(
        "[REGISTRATION - STUB] User {user_id} нажал кнопку подтверждения города: "
        f"{callback_data}"
    )

    # --- Логика-заглушка ---
    # TODO: Распарсить callback_data, получить город, сохранить в user_data/БД
    # TODO: Запросить категории услуг, создать клавиатуру
    if callback_data.startswith(CALLBACK_CONFIRM_CITY_PREFIX):
        confirmed_city = callback_data.split(CALLBACK_CONFIRM_CITY_PREFIX)[1]
        context.user_data["registration_city"] = confirmed_city
        logger.info(f"Город '{confirmed_city}' подтвержден для user {user_id}.")

        # Строка ответа разбита для E501
        message_text = (
            f"Місто **{confirmed_city}** підтверджено (ЗАГЛУШКА).\n\n"
            "Тепер розкажіть, за якими основними напрямками послуг ви хотіли б "
            "отримувати заявки? (Наприклад: Манікюр, Стрижка, Ремонт)"
        )
        await query.edit_message_text(text=message_text, parse_mode="Markdown")

        # Строка лога разбита для E501
        logger.info(
            "[REGISTRATION - STUB] Возвращаем состояние REGISTER_ASK_SERVICES для user "
            f"{user.id}"
        )
        # Важно вернуть правильное состояние, ожидаемое ConversationHandler
        # Импорт уже есть в начале файла
        return REGISTER_ASK_SERVICES  # Переходим к запросу услуг
    else:
        logger.warning(f"Неверный callback_data в handle_city_button: {callback_data}")
        await query.edit_message_text("Сталася помилка обробки кнопки.")
        return REGISTER_ASK_CITY  # Возврат к запросу города при ошибке?


# === END BLOCK 5 ===
