# BehaviorEngine/state_manager.py

# === BLOCK 1: Imports ===
import logging
import time # <--- ДОБАВЬТЕ ЭТУ СТРОКУ
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from database.models import UserStates  # <--- UserData УДАЛЕН ОТСЮДА
except ImportError as e:
    logging.critical(
        f"CRITICAL: Failed to import DB models in state_manager: {e}", exc_info=True
    )
    raise
# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
# === END BLOCK 2 ===


# === BLOCK 3: Get User State ===
async def get_user_state(user_id: int, session: AsyncSession) -> Optional[UserStates]:
    func_start_time = time.monotonic()
    logger.debug(f"StateMgr: Запрос состояния для user_id={user_id}")
    if not isinstance(user_id, int) or user_id <= 0:
        logger.warning(f"StateMgr: Получен некорректный user_id: {user_id}")
        logger.debug(f"StateMgr: get_user_state for {user_id} (invalid ID) took {time.monotonic() - func_start_time:.4f}s")
        return None
    try:
        stmt = select(UserStates).where(UserStates.user_id == user_id)

        db_call_start_time = time.monotonic()
        result = await session.execute(stmt)
        user_state = result.scalar_one_or_none()
        logger.debug(f"StateMgr: DB select in get_user_state for {user_id} took {time.monotonic() - db_call_start_time:.4f}s")

        if user_state:
            logger.debug(
                f"StateMgr: Найдено состояние для user_id={user_id}: scenario='{user_state.scenario_key}', state='{user_state.current_state_key}'"
            )
        else:
            logger.debug(f"StateMgr: Активное состояние для user_id={user_id} не найдено.")

        logger.debug(f"StateMgr: get_user_state for {user_id} total took {time.monotonic() - func_start_time:.4f}s. Found: {'Yes' if user_state else 'No'}")
        return user_state
    except Exception as e:
        logger.error(
            f"StateMgr: Ошибка БД при получении состояния для user_id={user_id}: {e}",
            exc_info=True,
        )
        logger.debug(f"StateMgr: get_user_state for {user_id} (exception) took {time.monotonic() - func_start_time:.4f}s")
        return None
# === END BLOCK 3 ===

# === BLOCK 4: Update User State (Implementation) ===
async def update_user_state(
    user_id: int,
    scenario_key: str,
    state_key: str,
    context_data: Optional[Dict[str, Any]],
    session: AsyncSession,
) -> Optional[UserStates]:
    func_start_time = time.monotonic()
    logger.debug(f"StateMgr: update_user_state called for user_id={user_id}, scenario='{scenario_key}', state='{state_key}'")
    if not all([isinstance(user_id, int), user_id > 0, scenario_key, state_key]):
        logger.warning(
            f"StateMgr: Получены некорректные аргументы для update_user_state: user_id={user_id}, scenario='{scenario_key}', state='{state_key}'"
        )
        logger.debug(f"StateMgr: update_user_state for {user_id} (invalid args) took {time.monotonic() - func_start_time:.4f}s")
        return None

    updated_or_created_state: Optional[UserStates] = None
    try:
        get_existing_start_time = time.monotonic()
        existing_state = await get_user_state(user_id, session) # get_user_state уже логирует свое время
        logger.debug(f"StateMgr: get_user_state inside update_user_state took {time.monotonic() - get_existing_start_time:.4f}s")

        db_op_type = ""
        db_op_start_time = time.monotonic()

        if existing_state:
            db_op_type = "update"
            logger.debug(
                f"StateMgr: Updating state for user_id={user_id} to scenario='{scenario_key}', state='{state_key}'"
            )
            existing_state.scenario_key = scenario_key
            existing_state.current_state_key = state_key
            existing_state.state_context = context_data
            session.add(existing_state) # Важно для отслеживания изменений SQLAlchemy
            updated_or_created_state = existing_state
        else:
            db_op_type = "create"
            logger.debug(
                f"StateMgr: Creating new state for user_id={user_id}: scenario='{scenario_key}', state='{state_key}'"
            )
            new_state = UserStates(
                user_id=user_id,
                scenario_key=scenario_key,
                current_state_key=state_key,
                state_context=context_data,
            )
            session.add(new_state)
            updated_or_created_state = new_state

        await session.flush()
        if updated_or_created_state: # Проверка, что объект существует перед refresh
             await session.refresh(updated_or_created_state)

        logger.debug(f"StateMgr: DB {db_op_type} (flush+refresh) in update_user_state for {user_id} took {time.monotonic() - db_op_start_time:.4f}s")

        if db_op_type == "update":
             logger.debug(f"StateMgr: State updated successfully for user_id={user_id}")
        else:
             logger.info(f"StateMgr: New state created successfully for user_id={user_id}, state_id={getattr(updated_or_created_state, 'user_state_id', 'N/A')}")

    except Exception as e:
        logger.error(
            f"StateMgr: DB error updating/creating state for user_id={user_id}: {e}",
            exc_info=True,
        )
        updated_or_created_state = None # Сбрасываем в случае ошибки

    logger.debug(f"StateMgr: update_user_state for {user_id} total took {time.monotonic() - func_start_time:.4f}s. Success: {'Yes' if updated_or_created_state else 'No'}")
    return updated_or_created_state
# === END BLOCK 4 ===

# === BLOCK 5: Reset User State (Implementation) ===
async def reset_user_state(user_id: int, session: AsyncSession) -> bool:
    func_start_time = time.monotonic()
    logger.debug(f"StateMgr: reset_user_state called for user_id={user_id}")
    if not isinstance(user_id, int) or user_id <= 0:
        logger.warning(f"StateMgr: Получен некорректный user_id для сброса состояния: {user_id}")
        logger.debug(f"StateMgr: reset_user_state for {user_id} (invalid ID) took {time.monotonic() - func_start_time:.4f}s")
        return True # Считаем успешным, т.к. нет состояния для сброса

    success = False
    try:
        get_existing_start_time = time.monotonic()
        existing_state = await get_user_state(user_id, session)
        logger.debug(f"StateMgr: get_user_state inside reset_user_state took {time.monotonic() - get_existing_start_time:.4f}s")

        if existing_state:
            logger.debug(
                f"StateMgr: Deleting state for user_id={user_id} (State ID: {existing_state.user_state_id})"
            )
            db_delete_start_time = time.monotonic()
            await session.delete(existing_state)
            await session.flush() # Применяем удаление
            logger.debug(f"StateMgr: DB delete+flush in reset_user_state for {user_id} took {time.monotonic() - db_delete_start_time:.4f}s")
            logger.info(f"StateMgr: State successfully marked for deletion for user_id={user_id}")
        else:
            logger.debug(
                f"StateMgr: No state found to delete for user_id={user_id}. Reset considered successful."
            )
        success = True
    except Exception as e:
        logger.error(
            f"StateMgr: DB error resetting state for user_id={user_id}: {e}", exc_info=True
        )
        success = False

    logger.debug(f"StateMgr: reset_user_state for {user_id} total took {time.monotonic() - func_start_time:.4f}s. Success: {success}")
    return success
# === END BLOCK 5 ===