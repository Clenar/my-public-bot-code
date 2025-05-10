# handlers/custom_test_handlers.py
import logging
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

# Импорты, которые могут понадобиться вашей функции
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


# === BLOCK 1: Тестовый обработчик ===
async def simple_test_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],  # Принимаем state_context
) -> Dict[str, Any]:  # Возвращаем словарь для обновления контекста
    """
    Простой тестовый обработчик, вызываемый через call_handler.
    Логирует информацию и возвращает данные для state_context.
    """
    user = update.effective_user
    user_id = user.id if user else "Unknown"

    logger.info(f"[Custom Handler] simple_test_handler called for user {user_id}.")
    logger.info(f"[Custom Handler] Received state_context: {state_context}")

    # Пример простой логики: добавляем что-то в контекст
    handler_result = {
        "handler_message": f"simple_test_handler executed successfully for user {user_id}!",
        "handler_input_context": state_context.copy(),  # Копируем входной контекст для примера
    }

    # Возвращаем словарь, который executor должен будет смержить с state_context
    # так как мы не указываем save_result_to в YAML (позже)
    return handler_result


# === END BLOCK 1 ===
