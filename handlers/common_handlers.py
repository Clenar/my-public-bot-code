# Sprofy/handlers/common_handlers.py

# === BLOCK (cancel function): Обновленная логика /cancel для BehaviorEngine ===
import logging
import typing

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import ContextTypes

from BehaviorEngine.state_manager import reset_user_state

logger = logging.getLogger(__name__)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Отменяет текущий сценарий BehaviorEngine для пользователя и отправляет сообщение.
    """
    if not update.effective_user:
        logger.warning("Команда /cancel вызвана без пользователя.")
        if update.effective_chat:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Діалог скасовано. Помилка: не вдалося визначити користувача.",
                )
            except Exception as send_e:
                logger.error(
                    f"Не удалось отправить сообщение об ошибке отмены (нет пользователя): {send_e}"
                )
        return

    user = update.effective_user
    user_id = user.id
    logger.info(
        f">>> Пользователь {user_id} ({user.username or 'N/A'}) отменил диалог командой /cancel."
    )

    session_maker: typing.Optional[async_sessionmaker[AsyncSession]] = (
        context.bot_data.get("session_maker")
    )
    if not session_maker:
        logger.error(
            f"Фабрика сессий 'session_maker' не найдена в bot_data для /cancel user {user_id}!"
        )
        if update.message:
            await update.message.reply_text(
                "Помилка сервера при скасуванні. Спробуйте пізніше."
            )
        elif (
            update.callback_query
        ):  # Добавил проверку перед использованием update.callback_query
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Помилка сервера при скасуванні. Спробуйте пізніше.",
            )
        return

    try:
        async with session_maker() as session, session.begin():  # <--- ИСПРАВЛЕНО ЗДЕСЬ
            reset_success = await reset_user_state(user_id, session)
            if reset_success:
                logger.info(
                    f"Состояние BehaviorEngine для user {user_id} успешно сброшено."
                )
            else:
                logger.warning(
                    f"Произошла ошибка при сбросе состояния для user {user_id} или состояние уже было сброшено."
                )

        cancel_message = "Діалог скасовано. Щоб почати знову, натисніть /start"
        if update.message:
            await update.message.reply_text(cancel_message)
        elif update.callback_query:
            try:
                await update.callback_query.answer()
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=cancel_message
                )
            except Exception as e:
                logger.debug(
                    f"Не удалось ответить на callback_query в /cancel: {e}. Отправка нового сообщения."
                )
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=cancel_message
                )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=cancel_message
            )
    except Exception as e:
        logger.error(
            f"Ошибка в обработчике /cancel для user {user_id}: {e}", exc_info=True
        )
        try:
            fallback_message = "Під час скасування сталася помилка. Спробуйте /start."
            if update.message:
                await update.message.reply_text(fallback_message)
            elif update.callback_query:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=fallback_message
                )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=fallback_message
                )
        except Exception as send_e:
            logger.error(
                f"Не удалось отправить fallback сообщение об ошибке отмены: {send_e}"
            )

    context.user_data.clear()
    logger.info(f"<<< Завершение обработки /cancel для user {user_id}.")


# === END BLOCK (cancel function) ===
