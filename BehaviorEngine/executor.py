# BehaviorEngine/executor.py
# Версия с флагом process_only_on_entry

# === BLOCK 1: Imports ===
import importlib  # Для динамического импорта в call_handler
import inspect  # Для проверки async в call_handler
import logging
import re  # Для обработки regex в фильтрах
from typing import Any, Callable, Coroutine, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

# Импорты для работы с Telegram и БД
from telegram import Update
from telegram.ext import ContextTypes

# Импорты моделей и других частей движка
try:
    from ai.interaction import _get_instruction_text, generate_text_response
    from database.models import UserData, UserStates

    from .state_manager import reset_user_state, update_user_state
except ImportError as e:
    logging.critical(
        f"CRITICAL: Failed to import modules/models/helpers in executor: {e}",
        exc_info=True,
    )
    raise
# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
_ON_ENTRY_DONE_FLAG = "_internal_on_entry_actions_done"
# === END BLOCK 2 ===


# === BLOCK 2.5: Helper function for formatting action params ===
def _format_action_params(
    params: Dict[str, Any],
    state_context: Dict[str, Any],
    update: Update,
    ptb_context: ContextTypes.DEFAULT_TYPE,
) -> Dict[str, Any]:
    """
    Форматирует строковые значения в словаре параметров, используя state_context
    и некоторые значения из update.
    """
    if not isinstance(params, dict):
        return params

    available_format_data = {
        **(state_context or {}),
        "message_text": getattr(getattr(update, "message", None), "text", None),
        "callback_data": getattr(getattr(update, "callback_query", None), "data", None),
        "user_id": getattr(getattr(update, "effective_user", None), "id", None),
        "first_name": getattr(
            getattr(update, "effective_user", None), "first_name", None
        ),
        "username": getattr(getattr(update, "effective_user", None), "username", None),
    }

    formatted_params = {}
    for key, value in params.items():
        if isinstance(value, str) and "{" in value and "}" in value:
            try:
                formatted_value = value.format(**available_format_data)
                formatted_params[key] = formatted_value
                if value != formatted_value:
                    logger.debug(
                        f"Formatted param '{key}': from '{value}' to '{formatted_value}'"
                    )
            except KeyError as e:
                logger.warning(
                    f"KeyError formatting param '{key}' for value '{value}': Missing key {e} in available_format_data. Using original value."
                )
                formatted_params[key] = value
            except Exception as e:
                logger.error(
                    f"Error formatting param '{key}' for value '{value}': {e}. Using original value."
                )
                formatted_params[key] = value
        else:
            formatted_params[key] = value
    return formatted_params


# === END BLOCK 2.5 ===


# === BLOCK 3: Execute State Function ===
async def execute_state(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    current_state_from_db: UserStates,
    scenario_definition: Dict[str, Any],
    session: AsyncSession,
    process_only_on_entry: bool = False,  # <--- НОВЫЙ ПАРАМЕТР
) -> None:
    state_key = current_state_from_db.current_state_key
    user_id = current_state_from_db.user_id
    scenario_key = current_state_from_db.scenario_key

    local_state_context = (current_state_from_db.state_context or {}).copy()

    transition_occurred = False

    logger.info(
        f"Executing state '{state_key}' for scenario '{scenario_key}' for user {user_id} (process_only_on_entry={process_only_on_entry})"
    )  # Добавил флаг в лог
    logger.debug(
        f"Initial local_state_context for '{state_key}': {local_state_context}"
    )

    states_definition = scenario_definition.get("states", {})
    current_state_config = states_definition.get(state_key)

    if not current_state_config or not isinstance(current_state_config, dict):
        logger.error(
            f"State key '{state_key}' not found or invalid. Resetting state for user {user_id}."
        )
        await reset_user_state(user_id, session)
        try:
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Произошла ошибка сценария. Попробуйте /start.",
                )
        except Exception as e_send:
            logger.error(f"Failed to send error message: {e_send}")
        return

    # --- Обработка on_entry ---
    on_entry_actions_done_in_context = local_state_context.get(
        _ON_ENTRY_DONE_FLAG, False
    )
    if not on_entry_actions_done_in_context:
        logger.debug(
            f"Flag '{_ON_ENTRY_DONE_FLAG}' is False. Executing on_entry actions for '{state_key}'."
        )
        on_entry_actions = current_state_config.get("on_entry")
        if isinstance(on_entry_actions, list):
            for action_index, action_data in enumerate(on_entry_actions):
                if not isinstance(action_data, dict):
                    continue
                action_type = action_data.get("action")
                raw_action_params = action_data.get("params", {})
                action_params = _format_action_params(
                    raw_action_params, local_state_context, update, context
                )

                if not action_type:
                    continue
                handler_func = ACTION_HANDLERS.get(action_type)
                if handler_func:
                    try:
                        logger.info(
                            f"Executing on_entry action #{action_index} for '{state_key}': {action_type} with params {action_params}"
                        )
                        if action_type == "transition_to":
                            await handler_func(
                                params=action_params,
                                update=update,
                                context=context,
                                state_context=local_state_context,
                                session=session,
                                current_state_from_db=current_state_from_db,
                            )
                            transition_occurred = True
                            break
                        else:
                            context_updates = await handler_func(
                                params=action_params,
                                update=update,
                                context=context,
                                state_context=local_state_context,
                                session=session,
                            )
                            if isinstance(context_updates, dict):
                                local_state_context.update(context_updates)
                    except Exception as e:
                        logger.error(
                            f"Error in on_entry action {action_type} for '{state_key}': {e}",
                            exc_info=True,
                        )

            if not transition_occurred:
                local_state_context[_ON_ENTRY_DONE_FLAG] = True
                logger.debug(
                    f"Flag '{_ON_ENTRY_DONE_FLAG}' set True after on_entry for '{state_key}'."
                )
        else:
            local_state_context[_ON_ENTRY_DONE_FLAG] = True
            logger.debug(
                f"No on_entry list or not a list for '{state_key}'. Flag '{_ON_ENTRY_DONE_FLAG}' set True."
            )
    else:
        logger.debug(
            f"Flag '{_ON_ENTRY_DONE_FLAG}' is True for '{state_key}'. Skipping on_entry actions."
        )

    if transition_occurred:
        logger.info(f"Transition in on_entry for '{state_key}'. State execution ended.")
        return  # Важно выйти здесь, чтобы не обрабатывать input_handlers, если переход был из on_entry

    # --- Обработка input_handlers (только если process_only_on_entry is False) ---
    if not process_only_on_entry:  # <--- НОВАЯ ПРОВЕРКА
        logger.debug(
            f"process_only_on_entry is False for '{state_key}'. Proceeding to input_handlers."
        )
        input_handlers_list = current_state_config.get("input_handlers")
        if isinstance(input_handlers_list, list):
            for handler_index, handler_definition in enumerate(input_handlers_list):
                if not isinstance(handler_definition, dict):
                    continue
                handler_filters = handler_definition.get("filters", [])
                handler_actions = handler_definition.get("actions", [])

                match = await _match_filters(update, context, handler_filters)
                if match:
                    logger.info(
                        f"Input matches handler #{handler_index} for state '{state_key}'. Executing actions..."
                    )
                    if isinstance(handler_actions, list):
                        for action_index, action_data in enumerate(handler_actions):
                            if not isinstance(action_data, dict):
                                continue
                            action_type = action_data.get("action")
                            raw_action_params = action_data.get("params", {})
                            action_params = _format_action_params(
                                raw_action_params, local_state_context, update, context
                            )

                            if not action_type:
                                continue
                            handler_func = ACTION_HANDLERS.get(action_type)
                            if handler_func:
                                try:
                                    logger.info(
                                        f"Executing input_handler action #{action_index} for '{state_key}': {action_type} with params {action_params}"
                                    )
                                    if action_type == "transition_to":
                                        await handler_func(
                                            params=action_params,
                                            update=update,
                                            context=context,
                                            state_context=local_state_context,
                                            session=session,
                                            current_state_from_db=current_state_from_db,
                                        )
                                        transition_occurred = True
                                        break
                                    else:
                                        context_updates = await handler_func(
                                            params=action_params,
                                            update=update,
                                            context=context,
                                            state_context=local_state_context,
                                            session=session,
                                        )
                                        if isinstance(context_updates, dict):
                                            local_state_context.update(context_updates)
                                except Exception as e:
                                    logger.error(
                                        f"Error in input_handler action {action_type} for '{state_key}': {e}",
                                        exc_info=True,
                                    )
                    if transition_occurred:
                        break
                    break  # Выходим из цикла input_handlers, так как один сработал

        if transition_occurred:
            logger.info(
                f"Transition in input_handler for '{state_key}'. State execution ended."
            )
            return
    else:
        logger.info(
            f"process_only_on_entry is True for '{state_key}'. Skipping input_handlers."
        )

    # --- Сохранение контекста, если не было перехода И контекст изменился ---
    if local_state_context != (current_state_from_db.state_context or {}):
        logger.debug(
            f"No transition in '{state_key}'. Saving updated local_state_context for user {user_id}. Context: {local_state_context}"
        )
        save_success = await update_user_state(
            user_id=user_id,
            scenario_key=scenario_key,
            state_key=state_key,  # Сохраняем для текущего состояния
            context_data=local_state_context,
            session=session,
        )
        if not save_success:
            logger.error(
                f"Failed to save context for user {user_id} in state '{state_key}'."
            )
    else:
        logger.debug(
            f"No transition and local_state_context was not changed since DB load for '{state_key}'. Skipping context save."
        )

    logger.info(f"Finished execution for state '{state_key}' for user {user_id}.")


# === END BLOCK 3 ===


# === BLOCK 4: Action Handlers ===
async def _handle_send_message(
    params: Dict[str, Any],
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_context: Dict[str, Any],
    session: AsyncSession,
) -> Optional[Dict[str, Any]]:
    logger.debug(
        f"Executing action 'send_message' with (already formatted) params: {params}"
    )
    message_key = params.get("message_key")
    text_override = params.get("text")
    parse_mode = params.get("parse_mode")

    user = update.effective_user
    if not user:
        logger.error("Action 'send_message': Cannot determine user.")
        return None

    final_text_to_send = None

    try:
        if text_override is not None:
            final_text_to_send = text_override
            logger.debug(
                f"Using 'text' (already formatted) for send_message: '{str(final_text_to_send)[:70]}...'"
            )
        elif message_key:
            db_user = await session.get(UserData, user.id)
            user_lang_code = db_user.language_code if db_user else None
            text_from_db = await _get_instruction_text(
                session, message_key, user_lang_code
            )

            if text_from_db:
                format_args_for_db_text = {
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                    "username": user.username or "",
                    **(state_context or {}),
                }
                try:
                    final_text_to_send = text_from_db.format(**format_args_for_db_text)
                except KeyError as e:
                    logger.warning(
                        f"KeyError formatting DB message '{message_key}': {e}. Using unformatted."
                    )
                    final_text_to_send = text_from_db
                except Exception as fmt_e:
                    logger.error(
                        f"Error formatting DB message '{message_key}': {fmt_e}",
                        exc_info=True,
                    )
                    final_text_to_send = text_from_db
                logger.debug(
                    f"Formatted text from DB for key '{message_key}': '{str(final_text_to_send)[:70]}...'"
                )
            else:
                logger.warning(
                    f"Text for message_key '{message_key}' not found in DB. Sending error."
                )
                final_text_to_send = f"Error: Message key '{message_key}' not found."
        else:
            logger.error(
                "Action 'send_message' requires either 'text' or 'message_key' parameter in YAML."
            )
            return None

        if final_text_to_send is None:
            logger.error("final_text_to_send is None before sending.")
            return None

        chat_id = update.effective_chat.id
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id, text=final_text_to_send, parse_mode=parse_mode
            )
            logger.info(f"Sent message to chat {chat_id}.")
        else:
            logger.error("Cannot send message: chat_id is missing.")
    except Exception as e:
        logger.error(f"Error in _handle_send_message: {e}", exc_info=True)
    return None


async def _handle_call_ai(
    params: Dict[str, Any],
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_context: Dict[str, Any],
    session: AsyncSession,
) -> Optional[Dict[str, Any]]:
    logger.debug(
        f"Executing action 'call_ai' with (already formatted) params: {params}"
    )
    prompt_key = params.get("prompt_key")
    system_prompt_override = params.get("system_prompt_override")
    save_to = params.get("save_to")
    history_context_key = params.get("history_context_key")
    user_reply_for_format = params.get("user_reply_for_format")

    if not (prompt_key or system_prompt_override) or not save_to:
        logger.error(
            "'call_ai' action requires 'save_to' and ('prompt_key' or 'system_prompt_override')."
        )
        return {save_to: "ERROR: AI call misconfigured"}

    user = update.effective_user
    if not user:
        logger.error("Action 'call_ai': Cannot determine user.")
        return {save_to: "ERROR: User not found"}

    try:
        db_user = await session.get(UserData, user.id)
        user_lang_code = db_user.language_code if db_user else None

        current_user_reply_for_history = None
        if update.message and update.message.text:
            current_user_reply_for_history = update.message.text
        elif update.callback_query and update.callback_query.data:
            current_user_reply_for_history = update.callback_query.data

        final_user_reply_for_format = user_reply_for_format
        if (
            final_user_reply_for_format is None
            and current_user_reply_for_history is not None
        ):
            final_user_reply_for_format = current_user_reply_for_history
            logger.debug(
                f"Using current user input as 'user_reply_for_format': '{final_user_reply_for_format}'"
            )

        messages_history = []
        if history_context_key:
            history_from_context = state_context.get(history_context_key)
            if isinstance(history_from_context, list):
                messages_history.extend(history_from_context)

        # Не добавляем current_user_reply_for_history в history, если он уже есть (часто бывает)
        # Логика добавления в историю должна быть более продуманной, если это полноценный чат-бот.
        # Для классификатора обычно достаточно текущего ответа.
        # Если `final_user_reply_for_format` уже содержит то, что нужно,
        # и `messages` передается извне (например, из предыдущего шага)
        # то дублировать не нужно. Пока оставим как есть, но это место для улучшений.
        # Для простоты классификатора, history может быть пустой, а final_user_reply_for_format - текстом для промпта

        if not messages_history and current_user_reply_for_history is not None:
            messages_history.append(
                {"role": "user", "content": str(current_user_reply_for_history)}
            )

        ai_response = await generate_text_response(
            messages=messages_history,
            instruction_key=prompt_key,
            user_lang_code=user_lang_code,
            session=session,
            system_prompt_override=system_prompt_override,
            user_reply_for_format=final_user_reply_for_format,
        )

        if ai_response is not None:
            logger.info(f"AI response received: '{ai_response[:70]}...'")
            return {save_to: ai_response}
        else:
            logger.error("AI call returned None.")
            return {save_to: None}  # Явно возвращаем None в контекст
    except Exception as e:
        logger.error(f"Error in _handle_call_ai: {e}", exc_info=True)
        return {save_to: f"ERROR_AI_CALL: {type(e).__name__}"}


async def _handle_call_handler(
    params: Dict[str, Any],
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_context: Dict[str, Any],
    session: AsyncSession,
) -> Optional[Dict[str, Any]]:
    logger.debug(
        f"Executing action 'call_handler' with (already formatted) params: {params}"
    )
    function_name_str = params.get("function_name")
    save_result_to = params.get("save_result_to")
    pass_state_context = params.get("pass_state_context", True)  # По умолчанию передаем

    if not function_name_str:
        logger.error("'call_handler' requires 'function_name' parameter.")
        return None  # Или {save_result_to: "ERROR: Missing function_name"} если save_result_to есть

    try:
        module_path, func_name = function_name_str.rsplit(".", 1)
        module = importlib.import_module(module_path)
        handler_func_to_call = getattr(module, func_name)

        if not inspect.iscoroutinefunction(handler_func_to_call):
            logger.error(
                f"Handler function '{function_name_str}' is not an async function."
            )
            return (
                {save_result_to: f"ERROR: Handler '{function_name_str}' not async"}
                if save_result_to
                else None
            )

        # Определяем, какие аргументы принимает функция
        sig = inspect.signature(handler_func_to_call)
        handler_kwargs = {}
        if "update" in sig.parameters:
            handler_kwargs["update"] = update
        if "context" in sig.parameters:
            handler_kwargs["context"] = context
        if "session" in sig.parameters:
            handler_kwargs["session"] = session
        if pass_state_context and "state_context" in sig.parameters:
            handler_kwargs["state_context"] = state_context
        # Можно добавить передачу других параметров из YAML, если они есть в params
        # и функция их принимает

        logger.info(
            f"Calling custom handler: {function_name_str} with args: {list(handler_kwargs.keys())}"
        )
        returned_value = await handler_func_to_call(**handler_kwargs)
        logger.info(
            f"Custom handler '{function_name_str}' returned type: {type(returned_value)}, value: '{str(returned_value)[:100]}...'"
        )

        if save_result_to:
            return {save_result_to: returned_value}
        elif isinstance(
            returned_value, dict
        ):  # Если функция вернула словарь, мержим его
            return returned_value
        return None  # Если ничего не сохраняем и не словарь, то ничего не возвращаем в контекст
    except (ModuleNotFoundError, AttributeError) as e_import:
        logger.error(f"Could not import/find handler '{function_name_str}': {e_import}")
        return (
            {save_result_to: f"ERROR: Handler not found - {function_name_str}"}
            if save_result_to
            else None
        )
    except TypeError as e_type:  # Ловим TypeError, если передали лишние/не те аргументы
        logger.error(
            f"TypeError executing custom handler '{function_name_str}': {e_type}",
            exc_info=True,
        )
        return (
            {save_result_to: f"ERROR: Handler TypeError - {type(e_type).__name__}"}
            if save_result_to
            else None
        )
    except Exception as e:
        logger.error(
            f"Error executing custom handler '{function_name_str}': {e}", exc_info=True
        )
        return (
            {save_result_to: f"ERROR: Handler execution failed - {type(e).__name__}"}
            if save_result_to
            else None
        )


async def _handle_transition_to(
    params: Dict[str, Any],
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_context: Dict[str, Any],
    session: AsyncSession,
    current_state_from_db: UserStates,
) -> None:
    logger.debug(
        f"Executing action 'transition_to' with (already formatted) params: {params}"
    )

    next_state_key = params.get("next_state")
    context_to_set_from_yaml = params.get("set_context", {})

    if not next_state_key or not isinstance(next_state_key, str):
        logger.error(
            f"'transition_to' action requires a valid 'next_state' string parameter. Got: {next_state_key}"
        )
        return
    if not isinstance(context_to_set_from_yaml, dict):
        logger.warning("'set_context' for transition_to should be a dict. Using empty.")
        context_to_set_from_yaml = {}

    final_context_for_next_state = state_context.copy()
    final_context_for_next_state.update(context_to_set_from_yaml)
    final_context_for_next_state.pop(
        _ON_ENTRY_DONE_FLAG, None
    )  # Сбрасываем флаг для нового состояния

    logger.info(
        f"Transitioning user {current_state_from_db.user_id} from '{current_state_from_db.current_state_key}' to '{next_state_key}'. Context for new state: {final_context_for_next_state}"
    )

    updated = await update_user_state(
        user_id=current_state_from_db.user_id,
        scenario_key=current_state_from_db.scenario_key,  # Сценарий остается тот же
        state_key=next_state_key,
        context_data=final_context_for_next_state,
        session=session,
    )
    if not updated:
        logger.error("Transition failed (state update error in DB).")
    else:
        logger.info("Transition successful, state updated in DB.")


ActionHandlerType = Callable[..., Coroutine[Any, Any, Optional[Dict[str, Any]]]]
ACTION_HANDLERS: Dict[str, ActionHandlerType] = {
    "send_message": _handle_send_message,
    "call_ai": _handle_call_ai,
    "call_handler": _handle_call_handler,
    "transition_to": _handle_transition_to,
}
# === END BLOCK 4 ===


# === BLOCK 5: Filter Matching Helper ===
async def _match_filters(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    filters_config: List[Dict[str, Any]],
) -> bool:
    if not isinstance(filters_config, list):
        logger.warning(
            f"Filter matching failed: filters_config is not a list: {filters_config}"
        )
        return False
    if (
        not filters_config
    ):  # Если список фильтров пуст, считаем, что это универсальный обработчик
        logger.debug("Empty filter list in input_handler matches any input by default.")
        return True

    all_match = True  # Флаг, что ВСЕ фильтры в списке должны совпасть
    for filter_index, filter_item in enumerate(filters_config):
        if not isinstance(filter_item, dict):
            logger.warning(
                f"Invalid filter item format #{filter_index} (expected dict): {filter_item}"
            )
            all_match = False
            break  # Если один фильтр невалиден, вся группа не совпадает

        filter_type = filter_item.get("type")
        logger.debug(f"Checking filter #{filter_index}: {filter_item}")
        match_this_filter = False  # Флаг для текущего проверяемого фильтра

        if filter_type == "message":
            if update.message:
                content_type = filter_item.get("content_type")
                content_type_matched = False  # Флаг совпадения content_type
                if (
                    not content_type
                    or (
                        content_type == "text"
                        and getattr(update.message, "text", None) is not None
                    )
                    or (
                        content_type == "photo"
                        and getattr(update.message, "photo", None)
                        or content_type == "document"
                        and getattr(update.message, "document", None)
                    )
                ):  # Если content_type не указан, считаем, что подходит любой тип сообщения
                    content_type_matched = True
                elif content_type:
                    logger.debug(
                        f"Filter type 'message': content_type '{content_type}' mismatch or not checked."
                    )

                if not content_type_matched:
                    all_match = False
                    break  # Если тип контента не совпал, вся группа не совпадает

                # Если тип контента совпал или не был важен, проверяем дальше (текст, regex)
                if (
                    content_type == "text" or not content_type
                ):  # Проверяем текст, если это текстовое сообщение или content_type не указан
                    message_text = getattr(update.message, "text", None)
                    if message_text is not None:
                        text_exact = filter_item.get("text")
                        if text_exact is not None and message_text != text_exact:
                            all_match = False
                            break
                        text_regex_str = filter_item.get("regex")
                        if text_regex_str is not None:
                            try:
                                if not re.fullmatch(text_regex_str, message_text):
                                    logger.debug(
                                        f"Filter regex mismatch: pattern='{text_regex_str}', text='{message_text}'"
                                    )
                                    all_match = False
                                    break
                            except re.error as re_err:
                                logger.error(
                                    f"Invalid regex pattern '{text_regex_str}': {re_err}"
                                )
                                all_match = False
                                break
                    # Если в фильтре есть text или regex, а сообщения нет или оно не текстовое
                    elif (
                        filter_item.get("text") is not None
                        or filter_item.get("regex") is not None
                    ):
                        all_match = False
                        break
                match_this_filter = True  # Если дошли сюда, этот message-фильтр совпал
            else:
                all_match = False
                break  # Если тип фильтра "message", а update.message нет
        elif filter_type == "callback_query":
            callback_data_val = getattr(
                getattr(update, "callback_query", None), "data", None
            )
            if update.callback_query and callback_data_val is not None:
                data_exact = filter_item.get("data")
                if data_exact is not None and callback_data_val != data_exact:
                    all_match = False
                    break

                data_pattern_str = filter_item.get("pattern")
                if data_pattern_str is not None:
                    try:
                        if not re.fullmatch(data_pattern_str, callback_data_val):
                            logger.debug(
                                f"Filter callback_data pattern mismatch: pattern='{data_pattern_str}', data='{callback_data_val}'"
                            )
                            all_match = False
                            break
                    except re.error as re_err:
                        logger.error(
                            f"Invalid regex pattern for callback_data '{data_pattern_str}': {re_err}"
                        )
                        all_match = False
                        break
                match_this_filter = (
                    True  # Если дошли сюда, этот callback_query-фильтр совпал
                )
            else:
                all_match = False
                break  # Если тип фильтра "callback_query", а update.callback_query нет
        elif filter_type == "command":
            message_text = getattr(getattr(update, "message", None), "text", None)
            if update.message and message_text and message_text.startswith("/"):
                command_expected = filter_item.get("command")
                if command_expected:
                    command_expected_clean = command_expected.lstrip("/")
                    actual_command = message_text.split(maxsplit=1)[0][
                        1:
                    ]  # Извлекаем команду без /
                    if actual_command == command_expected_clean:
                        match_this_filter = True
                    else:
                        logger.debug(
                            f"Filter command mismatch: expected '{command_expected_clean}', got '{actual_command}'."
                        )
                        all_match = False
                        break
                else:
                    logger.warning(
                        "Filter type 'command' but 'command' parameter missing."
                    )
                    all_match = False
                    break
            else:
                all_match = False
                break  # Если тип "command", но это не сообщение или не начинается с /
        else:
            logger.warning(f"Unknown filter type '{filter_type}'.")
            all_match = False
            break  # Неизвестный тип фильтра - группа не совпадает

        if (
            not match_this_filter
        ):  # Если хотя бы один конкретный фильтр из списка не совпал
            all_match = False
            break

    if all_match:
        logger.info(f"Update {update.update_id} MATCHED ALL filters in the list.")
    else:
        logger.debug(
            f"Update {update.update_id} did NOT match all filters in the list."
        )
    return all_match


# === END BLOCK 5 ===
