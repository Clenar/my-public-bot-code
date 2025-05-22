# BehaviorEngine/engine.py
# Версия с флагом process_only_on_entry для execute_state

# === BLOCK 1: Imports ===
import asyncio
import logging
import time  # <--- ДОБАВЛЕНА ЭТА СТРОКА
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


# === BLOCK 3: Main Engine Handler Function (handle_update) - ИСПРАВЛЕННЫЙ С ЛОГИРОВАНИЕМ ВРЕМЕНИ ===
async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Главный обработчик движка сценариев для входящих обновлений.
    Работает в цикле, пока происходят внутренние переходы состояний
    и есть on_entry для выполнения в новых состояниях.
    """
    total_handle_update_start_time = time.monotonic() # Начало замера общего времени

    user = update.effective_user
    if not user:
        logger.debug("Engine handle_update: No effective_user. Update not handled.")
        return False

    user_id = user.id
    original_update_id = update.update_id
    logger.info(
        f"Engine: handle_update CALLED for user {user_id}, original_update_id: {original_update_id}"
    )

    session_maker: Optional[async_sessionmaker[AsyncSession]] = context.bot_data.get(
        "session_maker"
    )
    if not session_maker:
        logger.error(f"Engine handle_update: No session_maker for user {user_id}.")
        return False

    processed_by_engine_flag = False
    # Константа для доступа к флагу из executor.py
    # Определена в executor.py, здесь используется для логики engine
    _ON_ENTRY_DONE_FLAG = "_internal_on_entry_actions_done" 

    try:
        async with session_maker() as session:
            MAX_INTERNAL_TRANSITIONS = 10
            for transition_attempt in range(MAX_INTERNAL_TRANSITIONS):
                iter_start_time = time.monotonic()
                logger.debug(
                    f"Engine: Iteration {transition_attempt + 1}/{MAX_INTERNAL_TRANSITIONS} for user {user_id}, original_update_id: {original_update_id}"
                )

                get_state_start_time = time.monotonic()
                current_user_db_state = await get_user_state(user_id, session)
                logger.debug(f"Engine: get_user_state (initial in iter) took {time.monotonic() - get_state_start_time:.4f}s")

                if not current_user_db_state:
                    logger.debug(
                        f"Engine: No active state for user {user_id}. Ending internal loop."
                    )
                    break

                current_state_key_before_execute = current_user_db_state.current_state_key
                current_context_before_execute = (current_user_db_state.state_context or {}).copy() 
                
                logger.debug(
                    f"Engine: User {user_id} in state '{current_state_key_before_execute}' of scenario '{current_user_db_state.scenario_key}'. Context before exec: {current_context_before_execute}"
                )

                load_scenario_start_time = time.monotonic()
                scenario_definition = await load_and_parse_scenario(
                    current_user_db_state.scenario_key, session
                )
                logger.debug(f"Engine: load_and_parse_scenario took {time.monotonic() - load_scenario_start_time:.4f}s")

                if not scenario_definition:
                    logger.error(
                        f"Engine: Failed to load scenario '{current_user_db_state.scenario_key}' for user {user_id}. Resetting state."
                    )
                    await reset_user_state(user_id, session)
                    commit_after_reset_start_time = time.monotonic()
                    await session.commit()
                    logger.debug(f"Engine: session.commit (after reset) took {time.monotonic() - commit_after_reset_start_time:.4f}s")
                    logger.info(
                        f"Engine: Committed after reset_user_state for user {user_id}."
                    )
                    processed_by_engine_flag = True
                    break

                should_process_only_on_entry = transition_attempt > 0

                logger.debug(
                    f"Engine: About to call execute_state for user {user_id} (process_only_on_entry={should_process_only_on_entry})."
                )
                execute_state_start_time = time.monotonic()
                await execute_state(
                    update=update,
                    context=context,
                    current_state_from_db=current_user_db_state, 
                    scenario_definition=scenario_definition,
                    session=session,
                    process_only_on_entry=should_process_only_on_entry,
                )
                logger.debug(f"Engine: execute_state for user {user_id} took {time.monotonic() - execute_state_start_time:.4f}s")
                processed_by_engine_flag = True
                
                # Повторно получаем состояние из БД ПОСЛЕ выполнения execute_state,
                # чтобы увидеть актуальные изменения ключа состояния И КОНТЕКСТА.
                get_state_post_exec_start_time = time.monotonic()
                post_execute_user_db_state = await get_user_state(user_id, session)
                logger.debug(f"Engine: get_user_state (post_execute in iter) took {time.monotonic() - get_state_post_exec_start_time:.4f}s")

                if not post_execute_user_db_state:
                    logger.debug(
                        f"Engine: No active state for user {user_id} after execute_state. Ending internal loop."
                    )
                    break 
                
                on_entry_done_in_post_execute_context = (post_execute_user_db_state.state_context or {}).get(_ON_ENTRY_DONE_FLAG, False)

                if post_execute_user_db_state.current_state_key != current_state_key_before_execute:
                    logger.info(
                        f"Engine: State key changed for user {user_id} from '{current_state_key_before_execute}' to '{post_execute_user_db_state.current_state_key}'. Continuing internal loop."
                    )
                    # Цикл продолжится
                elif not on_entry_done_in_post_execute_context:
                    # Ключ состояния тот же, но on_entry для нового/обновленного контекста еще не выполнен
                    logger.info(
                        f"Engine: State key '{post_execute_user_db_state.current_state_key}' is the same, "
                        f"but on_entry is not marked as done (flag is {on_entry_done_in_post_execute_context}). Continuing internal loop to process on_entry."
                    )
                    # Цикл продолжится, should_process_only_on_entry будет True на след. итерации
                else:
                    # Ключ состояния тот же, и on_entry для текущего контекста уже выполнен
                    logger.debug(
                        f"Engine: State key '{post_execute_user_db_state.current_state_key}' is the same, "
                        f"and on_entry actions are marked as done. Ending internal loop."
                    )
                    break 
                logger.debug(f"Engine: Iteration {transition_attempt + 1} for user {user_id} took {time.monotonic() - iter_start_time:.4f}s")

            if transition_attempt == MAX_INTERNAL_TRANSITIONS - 1 and MAX_INTERNAL_TRANSITIONS > 0 :
                logger.warning(
                    f"Engine: Max internal transitions ({MAX_INTERNAL_TRANSITIONS}) reached for user {user_id}. Breaking loop to prevent infinite recursion."
                )
            
            final_commit_start_time = time.monotonic()
            await session.commit()
            logger.info(
                f"Engine: Committed final state for user {user_id} after internal loop (if any), original_update_id: {original_update_id}. Commit took {time.monotonic() - final_commit_start_time:.4f}s"
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
        return False 
    finally:
        logger.info(
            f"Engine: handle_update FINISHING for user {user_id}, original_update_id: {original_update_id}. Total time: {time.monotonic() - total_handle_update_start_time:.4f}s. Returning: {processed_by_engine_flag}"
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
