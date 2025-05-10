# handlers/start.py
# Версия для интеграции с BehaviorEngine (BehaviorEngine отправляет первое сообщение)

# === BLOCK 1: Imports ===
import contextlib  # <--- ДОБАВЛЕН ИМПОРТ
import logging
import typing

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

try:
    from BehaviorEngine.engine import trigger_on_entry_for_state
except ImportError as e:
    logging.critical(
        f"CRITICAL: Failed to import trigger_on_entry_for_state from BehaviorEngine.engine: {e}",
        exc_info=True,
    )
    raise

from BehaviorEngine.state_manager import reset_user_state, update_user_state
from database.models import UserData, UserStates, get_or_create_user

# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
# === END BLOCK 2 ===


# === BLOCK 3: /start Command Handler (Интеграция с BehaviorEngine) ===
async def start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> typing.Optional[int]:
    """
    Обрабатывает команду /start.
    """
    if not update.message or not update.effective_user:
        logger.warning("Команда /start вызвана без сообщения или пользователя.")
        return ConversationHandler.END

    user = update.effective_user
    user_id = user.id
    logger.info(
        f">>> Команда /start от user {user_id} ({user.username or 'N/A'}). "
        "Инициализация сценария через BehaviorEngine."
    )

    session_maker: typing.Optional[async_sessionmaker[AsyncSession]] = (
        context.bot_data.get("session_maker")
    )
    if not session_maker:
        logger.critical(
            f"Фабрика сессий 'session_maker' не найдена в bot_data для /start user {user_id}!"
        )
        with contextlib.suppress(
            Exception
        ):  # <--- ИСПРАВЛЕНО ЗДЕСЬ (было try/except pass)
            await update.message.reply_text(
                "Вибачте, сталася критична помилка сервера (сесія)."
            )
        return ConversationHandler.END

    user_data_obj: typing.Optional[UserData] = None
    created: bool = False
    try:
        user_data_obj, created = await get_or_create_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            language_code=user.language_code,
        )
        if not user_data_obj:
            raise ValueError(
                "Функция get_or_create_user не вернула объект пользователя."
            )
        if created:
            logger.info(f"Пользователь {user_data_obj.user_id} создан.")
        else:
            logger.info(f"Пользователь {user_data_obj.user_id} найден.")

    except Exception as db_error:
        logger.error(
            f"!!! Ошибка БД при get_or_create_user для {user_id}: {db_error}",
            exc_info=True,
        )
        with contextlib.suppress(
            Exception
        ):  # <--- ИСПРАВЛЕНО ЗДЕСЬ (было try/except pass)
            await update.message.reply_text(
                "Вибачте, помилка бази даних. Спробуйте /start ще раз."
            )
        return ConversationHandler.END

    scenario_to_start = "main_start_v1"
    initial_state_key = "ASK_ROLE"
    initial_context = {}

    newly_set_user_state: typing.Optional[UserStates] = None
    try:
        async with session_maker() as session:
            async with session.begin():
                reset_ok = await reset_user_state(user_id, session)
                if reset_ok:
                    logger.info(
                        f"Предыдущее состояние BehaviorEngine для user {user_id} сброшено."
                    )
                else:
                    logger.warning(
                        f"Не удалось сбросить предыдущее состояние для user {user_id}. "
                        "(Это нормально, если его не было)."
                    )

                newly_set_user_state = await update_user_state(
                    user_id=user_id,
                    scenario_key=scenario_to_start,
                    state_key=initial_state_key,
                    context_data=initial_context,
                    session=session,
                )

                if not newly_set_user_state:
                    logger.error(
                        f"Не удалось установить состояние '{initial_state_key}' "
                        f"сценария '{scenario_to_start}' для user {user_id}."
                    )
                    raise ValueError("Ошибка установки начального состояния сценария")

                logger.info(
                    f"Установлено состояние '{initial_state_key}' (ID: {newly_set_user_state.user_state_id}) "
                    f"сценария '{scenario_to_start}' для user {user_id}."
                )

                logger.info(
                    f"Вызов trigger_on_entry_for_state для user {user_id}, состояние '{initial_state_key}'..."
                )
                await trigger_on_entry_for_state(
                    update=update,
                    context=context,
                    user_db_state=newly_set_user_state,
                    session=session,
                )
                logger.info(
                    f"Завершена обработка on_entry для user {user_id}, состояние '{initial_state_key}'."
                )
            logger.info(
                f"Транзакция для /start (user {user_id}, scenario '{scenario_to_start}') успешно закоммичена."
            )

    except ValueError as val_err:
        logger.error(
            f"Ошибка в логике /start для user {user_id}: {val_err}", exc_info=True
        )
        with contextlib.suppress(
            Exception
        ):  # <--- ИСПРАВЛЕНО ЗДЕСЬ (было try/except pass)
            await update.message.reply_text(
                "Вибачте, сталася помилка при запуску нового діалогу (ошибка значения)."
            )
        return ConversationHandler.END
    except Exception as e:
        logger.error(
            f"Критическая ошибка в /start (BehaviorEngine integration) для user {user_id}: {e}",
            exc_info=True,
        )
        with contextlib.suppress(
            Exception
        ):  # <--- ИСПРАВЛЕНО ЗДЕСЬ (было try/except pass)
            await update.message.reply_text(
                "Вибачте, сталася непередбачена помилка при запуску."
            )
        return ConversationHandler.END

    logger.info(f"<<< Завершение обработки /start (BehaviorEngine) для user {user_id}.")
    return None


# === END BLOCK 3 ===


# === BLOCK 4: Handle Role Response (Text) - СТАРЫЙ ===
async def handle_role_response(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    logger.warning(
        f"Вызван СТАРЫЙ обработчик handle_role_response для user "
        f"{update.effective_user.id if update.effective_user else 'Unknown'}"
    )
    if update.message:
        await update.message.reply_text(
            "Этот диалог был обновлен. Пожалуйста, используйте /start для начала."
        )
    return ConversationHandler.END


# === END BLOCK 4 ===


# === BLOCK 5: Handle Role Button Callback - СТАРЫЙ ===
async def handle_role_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.warning(
        f"Вызван СТАРЫЙ обработчик handle_role_button для user "
        f"{update.effective_user.id if update.effective_user else 'Unknown'}"
    )
    query = update.callback_query
    if query:
        try:
            await query.answer(
                "Эта кнопка больше не активна. Пожалуйста, используйте /start.",
                show_alert=True,
            )
            await query.edit_message_text(
                text="Диалог был обновлен. Пожалуйста, используйте /start."
            )
        except Exception as e:
            logger.error(f"Ошибка при обработке старой кнопки роли: {e}")
    return ConversationHandler.END


# === END BLOCK 5 ===
