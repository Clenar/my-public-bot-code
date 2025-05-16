# === BLOCK 1: Imports ===
import logging
from typing import (
    Any,
    Dict,
)

# Было Dict[str, Any], Ruff может предложить Dict, если версия Python позволяет
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

# Добавим импорт для update_user_state и reset_user_state, если потребуется сброс
try:
    from BehaviorEngine.state_manager import update_user_state  # <--- ДОБАВЛЕНО
except ImportError:
    # Обработка ошибки импорта, если потребуется
    logging.getLogger(__name__).critical(
        "Failed to import update_user_state for scenario_logic_handlers"
    )
    raise
# === END BLOCK 1 ===

# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
# === END BLOCK 2 ===


# === BLOCK 3: Evaluate Role and Get Next State === (в handlers.scenario_logic_handlers.py)
async def evaluate_role_and_get_next_state(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Dict[str, Any]:  # Возвращаемый тип теперь Dict[str, Any]
    user = update.effective_user
    user_id_log = user.id if user else "Unknown"
    logger.info(
        f"[evaluate_role_and_get_next_state] Called for user {user_id_log}. "
        f"Current state_context: {state_context}"
    )

    classified_role_key = "classified_role"

    # Ключ для "завершения" работы main_start_v1 после переключения сценария.
    # Это состояние ДОЛЖНО СУЩЕСТВОВАТЬ в main_start_v1.yaml и может ничего не делать.
    master_branch_handled_key = "MASTER_BRANCH_HANDLED_SWITCHED_SCENARIO"

    next_state_client = "START_CLIENT_SEARCH"
    next_state_ask_again = "ASK_ROLE_AGAIN"

    master_reg_scenario_key = "master_registration_v1"
    master_reg_entry_state = "REG_MASTER_ASK_CITY"

    role_master_value = "MASTER"
    role_client_value = "CLIENT"
    role_unclear_value = (
        "UNCLEAR"  # Убедись, что это значение AI возвращает для неясных случаев
    )

    classified_role = state_context.get(classified_role_key)
    return_payload: Dict[str, Any] = {}  # Используем Dict

    if isinstance(classified_role, str):
        processed_role = classified_role.strip().upper()
        if processed_role == role_master_value:
            logger.info(
                f"User {user_id_log} classified as MASTER. Attempting to switch to scenario '{master_reg_scenario_key}' state '{master_reg_entry_state}'."
            )
            # ПЕРЕКЛЮЧАЕМ СЦЕНАРИЙ И СОСТОЯНИЕ ПОЛЬЗОВАТЕЛЯ
            # Убедись, что update_user_state импортирован из BehaviorEngine.state_manager
            new_state_for_master = await update_user_state(
                user_id=user.id,
                scenario_key=master_reg_scenario_key,
                state_key=master_reg_entry_state,
                context_data={},  # Начинаем с чистого контекста для нового сценария регистрации
                session=session,
            )
            if new_state_for_master:
                logger.info(
                    f"User {user_id_log} successfully switched to master registration scenario '{master_reg_scenario_key}'."
                )
                # Возвращаем ключ состояния для main_start_v1 И флаг, что переход уже инициирован хэндлером
                return_payload["next_state_key"] = master_branch_handled_key
                return_payload["handler_initiated_scenario_switch"] = (
                    True  # ВАЖНЫЙ ФЛАГ для executor.py
                )
            else:
                logger.error(
                    f"User {user_id_log}: Failed to switch to master registration scenario. Asking role again."
                )
                return_payload["next_state_key"] = next_state_ask_again
                return_payload["handler_initiated_scenario_switch"] = False

        elif processed_role == role_client_value:
            logger.info(
                f"User {user_id_log} classified as CLIENT. Transitioning to {next_state_client} (within current scenario)."
            )
            return_payload["next_state_key"] = next_state_client
            return_payload["handler_initiated_scenario_switch"] = (
                False  # Явно указываем, что переключения сценария не было
            )
        elif processed_role == role_unclear_value:
            logger.warning(
                f"User {user_id_log}: Role classified as UNCLEAR. "
                f"Transitioning to {next_state_ask_again} (within current scenario)."
            )
            return_payload["next_state_key"] = next_state_ask_again
            return_payload["handler_initiated_scenario_switch"] = (
                False  # Явно указываем
            )
        else:  # Неизвестное значение от AI
            logger.warning(
                f"User {user_id_log}: Role not matched (classified_role='{classified_role}'). "
                f"Transitioning to {next_state_ask_again} as fallback (within current scenario)."
            )
            return_payload["next_state_key"] = next_state_ask_again
            return_payload["handler_initiated_scenario_switch"] = (
                False  # Явно указываем
            )
    else:  # classified_role не строка или отсутствует
        logger.warning(
            f"User {user_id_log}: Classified role is not a string or is missing "
            f"(value='{classified_role}'). Transitioning to {next_state_ask_again} (within current scenario)."
        )
        return_payload["next_state_key"] = next_state_ask_again
        return_payload["handler_initiated_scenario_switch"] = False  # Явно указываем

    logger.debug(
        f"User {user_id_log}: Returning payload for main_start_v1: {return_payload}"
    )
    return return_payload


# === END BLOCK 3 ===
