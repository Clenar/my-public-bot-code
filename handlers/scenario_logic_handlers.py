# handlers/scenario_logic_handlers.py

# === BLOCK 1: Imports ===
import logging
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
# === END BLOCK 2 ===


# === BLOCK 3: Evaluate Role and Get Next State ===
async def evaluate_role_and_get_next_state(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Dict[str, Any]:
    user = update.effective_user
    user_id_log = user.id if user else "Unknown"
    logger.info(
        f"[evaluate_role_and_get_next_state] Called for user {user_id_log}. "
        f"Current state_context: {state_context}"
    )

    classified_role_key = "classified_role"

    next_state_master = "START_MASTER_REGISTRATION"
    next_state_client = "START_CLIENT_SEARCH"
    next_state_ask_again = "ASK_ROLE_AGAIN"

    role_master_value = "MASTER"
    role_client_value = "CLIENT"
    role_unclear_value = "UNCLEAR"  # Латинская 'E'

    classified_role = state_context.get(classified_role_key)
    logger.debug(
        f"User {user_id_log}: Classified role from context = '{classified_role}' (type: {type(classified_role)})"
    )

    return_payload: Dict[str, Any] = {}

    if isinstance(classified_role, str):
        processed_role = classified_role.strip().upper()
        if processed_role == role_master_value:
            logger.info(
                f"User {user_id_log} classified as MASTER. Transitioning to {next_state_master}."
            )
            return_payload["next_state_key"] = next_state_master
        elif processed_role == role_client_value:
            logger.info(
                f"User {user_id_log} classified as CLIENT. Transitioning to {next_state_client}."
            )
            return_payload["next_state_key"] = next_state_client
        elif processed_role == role_unclear_value:
            logger.warning(
                f"User {user_id_log}: Role classified as UNCLEAR. "
                f"Transitioning to {next_state_ask_again}."
            )
            return_payload["next_state_key"] = next_state_ask_again
        else:
            logger.warning(
                f"User {user_id_log}: Role not matched (classified_role='{classified_role}'). "
                f"Transitioning to {next_state_ask_again} as fallback."
            )
            return_payload["next_state_key"] = next_state_ask_again
    else:
        logger.warning(
            f"User {user_id_log}: Classified role is not a string or is missing "
            f"(value='{classified_role}'). Transitioning to {next_state_ask_again}."
        )
        return_payload["next_state_key"] = next_state_ask_again

    logger.debug(f"User {user_id_log}: Returning payload: {return_payload}")
    return return_payload


# === END BLOCK 3 ===
