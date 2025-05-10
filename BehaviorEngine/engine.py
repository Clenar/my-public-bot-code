# BehaviorEngine/engine.py
# Версия с флагом process_only_on_entry для execute_state

# === BLOCK 1: Imports ===
import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import ContextTypes

# Импорты компонентов движка
try:
    from .executor import execute_state
    from .parser import load_and_parse_scenario
    from .state_manager import UserStates, get_user_state, reset_user_state
except ImportError as e:
    logging.critical(
        f"CRITICAL: Failed to import engine components: {e}", exc_info=True
    )
    raise
# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
# === END BLOCK 2 ===


# === BLOCK 3: Main Engine Handler Function (handle_update) - ОБНОВЛЕННЫЙ ===
async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Главный обработчик движка сценариев для входящих обновлений.
    Работает в цикле, пока происходят внутренние переходы состояний
    и есть on_entry для выполнения в новых состояниях.
    """
    user = update.effective_user
    if not user:
        logger.debug("Engine handle_update: No effective_user. Update not handled.")
        return False

    user_id = user.id
    original_update_id = update.update_id  # Сохраняем ID оригинального update
    logger.info(
        f"Engine: handle_update CALLED for user {user_id}, original_update_id: {original_update_id}"
    )

    session_maker: Optional[async_sessionmaker[AsyncSession]] = context.bot_data.get(
        "session_maker"
    )
    if not session_maker:
        logger.error(f"Engine handle_update: No session_maker for user {user_id}.")
        return False

    processed_by_engine_flag = False  # Флаг, что движок что-то сделал

    try:
        async with session_maker() as session:
            # Цикл для обработки последовательных on_entry после внутренних переходов
            # Максимум N итераций, чтобы избежать бесконечных циклов из-за ошибок в YAML
            MAX_INTERNAL_TRANSITIONS = 10
            for transition_attempt in range(MAX_INTERNAL_TRANSITIONS):
                logger.debug(
                    f"Engine: Iteration {transition_attempt + 1}/{MAX_INTERNAL_TRANSITIONS} for user {user_id}, original_update_id: {original_update_id}"
                )

                current_user_db_state = await get_user_state(user_id, session)
                if not current_user_db_state:
                    logger.debug(
                        f"Engine: No active state for user {user_id}. Ending internal loop."
                    )
                    break  # Выходим из цикла, если состояния больше нет

                current_state_key_before_execute = (
                    current_user_db_state.current_state_key
                )
                logger.debug(
                    f"Engine: User {user_id} in state '{current_state_key_before_execute}' of scenario '{current_user_db_state.scenario_key}'."
                )

                scenario_definition = await load_and_parse_scenario(
                    current_user_db_state.scenario_key, session
                )
                if not scenario_definition:
                    logger.error(
                        f"Engine: Failed to load scenario '{current_user_db_state.scenario_key}' for user {user_id}. Resetting state."
                    )
                    await reset_user_state(user_id, session)
                    # Коммит нужен здесь, чтобы reset_user_state применился до выхода из цикла/функции
                    await session.commit()
                    logger.info(
                        f"Engine: Committed after reset_user_state for user {user_id}."
                    )
                    processed_by_engine_flag = (
                        True  # Считаем, что обработали (сбросили состояние)
                    )
                    break  # Выходим из цикла

                # При первой итерации (transition_attempt == 0), это обработка реального update от пользователя.
                # process_only_on_entry будет False, чтобы input_handlers могли сработать.
                # При последующих итерациях (transition_attempt > 0), мы здесь потому, что был внутренний переход.
                # Мы хотим выполнить только on_entry нового состояния.
                # Оригинальный `update` остается тем же.
                should_process_only_on_entry = transition_attempt > 0

                logger.debug(
                    f"Engine: About to call execute_state for user {user_id} (process_only_on_entry={should_process_only_on_entry})."
                )
                await execute_state(
                    update=update,  # Всегда используем оригинальный update
                    context=context,
                    current_state_from_db=current_user_db_state,
                    scenario_definition=scenario_definition,
                    session=session,
                    process_only_on_entry=should_process_only_on_entry,
                )
                logger.debug(f"Engine: execute_state completed for user {user_id}.")
                processed_by_engine_flag = (
                    True  # Если execute_state был вызван, считаем обработанным
                )

                # Проверяем, изменилось ли состояние после execute_state
                # Это важно, так как execute_state мог сделать transition_to
                # и обновить current_state_from_db в сессии, но мы должны перечитать из сессии.
                # state_manager.update_user_state делает flush и refresh, так что объект current_user_db_state в сессии должен быть актуален.
                # Однако, для чистоты можно перечитать, но это лишний запрос.
                # Будем полагаться на то, что current_user_db_state обновляется в сессии.

                # Ключевая проверка: если состояние НЕ изменилось, значит, цикл внутренних переходов завершен.
                # Или если `executor` не вызвал `transition_to`.
                # `current_state_key_before_execute` сравниваем с тем, что стало ПОСЛЕ `execute_state`
                # (которое могло изменить `current_user_db_state.current_state_key` через `update_user_state`)
                if (
                    current_user_db_state.current_state_key
                    == current_state_key_before_execute
                ):
                    logger.debug(
                        f"Engine: State did not change from '{current_state_key_before_execute}' for user {user_id}. Ending internal loop."
                    )
                    break  # Состояние не изменилось, выходим из цикла
                else:
                    logger.info(
                        f"Engine: State changed for user {user_id} from '{current_state_key_before_execute}' to '{current_user_db_state.current_state_key}'. Continuing internal loop."
                    )

            if transition_attempt == MAX_INTERNAL_TRANSITIONS - 1:
                logger.warning(
                    f"Engine: Max internal transitions ({MAX_INTERNAL_TRANSITIONS}) reached for user {user_id}. Breaking loop to prevent infinite recursion."
                )
                # Возможно, стоит сбросить состояние пользователя или отправить сообщение об ошибке

            await session.commit()
            logger.info(
                f"Engine: Committed final state for user {user_id} after internal loop (if any), original_update_id: {original_update_id}."
            )
            return processed_by_engine_flag

    except asyncio.CancelledError:
        logger.error(
            f"Engine handle_update: asyncio.CancelledError for user {user_id}, original_update_id: {original_update_id}",
            exc_info=True,
        )
        raise
    except Exception as e:
        logger.error(
            f"Engine handle_update: Unhandled exception for user {user_id}, original_update_id: {original_update_id}: {e}",
            exc_info=True,
        )
        # session.rollback() будет вызван менеджером контекста `async with session:`
        return False  # При ошибке считаем, что не обработали, или PTB сам разберется
    finally:
        logger.info(
            f"Engine: handle_update FINISHING for user {user_id}, original_update_id: {original_update_id}. Returning: {processed_by_engine_flag}"
        )


# === END BLOCK 3 ===


# === BLOCK 4: NEW - Function to Process on_entry for a Newly Set State ===
async def trigger_on_entry_for_state(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_db_state: UserStates,
    session: AsyncSession,
) -> None:
    """
    Принудительно запускает обработку on_entry для указанного состояния пользователя.
    Предназначен для вызова сразу после установки нового начального состояния сценария.
    """
    user_id = user_db_state.user_id
    scenario_key = user_db_state.scenario_key
    state_key = user_db_state.current_state_key

    logger.info(
        f"Engine: Triggering on_entry for user {user_id}, scenario '{scenario_key}', state '{state_key}'."
    )

    scenario_definition = await load_and_parse_scenario(scenario_key, session)
    if not scenario_definition:
        logger.error(
            f"Engine trigger_on_entry: Failed to load/parse scenario '{scenario_key}' for user {user_id}. Cannot execute on_entry."
        )
        return

    states_definition = scenario_definition.get("states", {})
    current_state_config = states_definition.get(state_key)

    if not current_state_config or not isinstance(current_state_config, dict):
        logger.error(
            f"Engine trigger_on_entry: State '{state_key}' not found or invalid in scenario '{scenario_key}'. Resetting state."
        )
        await reset_user_state(user_id, session)
        try:
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Произошла ошибка инициализации сценария. Попробуйте снова.",
                )
        except Exception as e_send:
            logger.error(
                f"Failed to send error message during trigger_on_entry: {e_send}"
            )
        return

    logger.debug(
        f"Engine: About to call execute_state from trigger_on_entry for user {user_id} (on_entry focus)."
    )
    await execute_state(
        update=update,
        context=context,
        current_state_from_db=user_db_state,
        scenario_definition=scenario_definition,
        session=session,
        process_only_on_entry=True,  # <--- ПЕРЕДАЕМ НОВЫЙ ФЛАГ КАК True
    )
    logger.info(
        f"Engine: on_entry processing for user {user_id}, state '{state_key}' (triggered by trigger_on_entry_for_state) completed."
    )


# === END BLOCK 4 ===
