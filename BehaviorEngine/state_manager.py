# BehaviorEngine/state_manager.py

# === BLOCK 1: Imports ===
import logging
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
    """
    Получает текущую запись состояния пользователя из БД.
    """
    if not isinstance(user_id, int) or user_id <= 0:
        logger.warning(f"Получен некорректный user_id: {user_id}")
        return None
    try:
        logger.debug(f"Запрос состояния для user_id={user_id}")
        stmt = select(UserStates).where(UserStates.user_id == user_id)
        result = await session.execute(stmt)
        user_state = result.scalar_one_or_none()
        if user_state:
            logger.debug(
                f"Найдено состояние для user_id={user_id}: scenario='{user_state.scenario_key}', state='{user_state.current_state_key}'"
            )
            return user_state
        else:
            logger.debug(f"Активное состояние для user_id={user_id} не найдено.")
            return None
    except Exception as e:
        logger.error(
            f"Ошибка БД при получении состояния для user_id={user_id}: {e}",
            exc_info=True,
        )
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
    """
    Создает или обновляет запись состояния пользователя в БД.
    """
    if not all([isinstance(user_id, int), user_id > 0, scenario_key, state_key]):
        logger.warning(
            f"Получены некорректные аргументы для update_user_state: user_id={user_id}, scenario='{scenario_key}', state='{state_key}'"
        )
        return None
    try:
        existing_state = await get_user_state(user_id, session)
        if existing_state:
            logger.debug(
                f"Updating state for user_id={user_id} to scenario='{scenario_key}', state='{state_key}'"
            )
            existing_state.scenario_key = scenario_key
            existing_state.current_state_key = state_key
            existing_state.state_context = context_data
            session.add(existing_state)
            await session.flush()
            await session.refresh(existing_state)
            logger.debug(f"State updated successfully for user_id={user_id}")
            return existing_state
        else:
            logger.debug(
                f"Creating new state for user_id={user_id}: scenario='{scenario_key}', state='{state_key}'"
            )
            new_state = UserStates(
                user_id=user_id,
                scenario_key=scenario_key,
                current_state_key=state_key,
                state_context=context_data,
            )
            session.add(new_state)
            await session.flush()
            await session.refresh(new_state)
            logger.info(
                f"New state created successfully for user_id={user_id}, state_id={new_state.user_state_id}"
            )
            return new_state
    except Exception as e:
        logger.error(
            f"DB error updating/creating state for user_id={user_id}: {e}",
            exc_info=True,
        )
        return None


# === END BLOCK 4 ===


# === BLOCK 5: Reset User State (Implementation) ===
async def reset_user_state(user_id: int, session: AsyncSession) -> bool:
    """
    Удаляет запись состояния пользователя из БД (если она существует).
    """
    if not isinstance(user_id, int) or user_id <= 0:
        logger.warning(f"Получен некорректный user_id для сброса состояния: {user_id}")
        return True
    try:
        existing_state = await get_user_state(user_id, session)
        if existing_state:
            logger.debug(
                f"Deleting state for user_id={user_id} (State ID: {existing_state.user_state_id})"
            )
            await session.delete(existing_state)
            await session.flush()
            logger.info(f"State successfully marked for deletion for user_id={user_id}")
        else:
            logger.debug(
                f"No state found to delete for user_id={user_id}. Reset considered successful."
            )
        return True
    except Exception as e:
        logger.error(
            f"DB error resetting state for user_id={user_id}: {e}", exc_info=True
        )
        return False


# === END BLOCK 5 ===
