# === BLOCK: BehaviorEngine/executor.py (Начало файла) ===
# BehaviorEngine/executor.py
# Версия с флагом process_only_on_entry, обработкой handler_initiated_scenario_switch,
# новой обработкой _trigger_state_transition_to от call_handler и ЛОГИРОВАНИЕМ ВРЕМЕНИ

# === BLOCK 1: Imports ===
import importlib
import inspect
import logging
import re
import time # <--- ДОБАВЛЕН IMPORT TIME
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
)

# Используем стандартные Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

try:
    from ai.interaction import _get_instruction_text, generate_text_response
    from database.models import (
        UserData,
        UserStates,
    )

    from .state_manager import (
        reset_user_state,
        update_user_state,
    )
except ImportError as e:
    logging.getLogger(__name__).critical(
        f"CRITICAL: Failed to import modules/models/helpers in executor: {e}",
        exc_info=True,
    )
    raise
# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
_ON_ENTRY_DONE_FLAG = "_internal_on_entry_actions_done"
_HANDLER_INITIATED_SWITCH_FLAG = "handler_initiated_scenario_switch"
_TRIGGER_STATE_TRANSITION_KEY = "_trigger_state_transition_to"
# === END BLOCK 2 ===


# === BLOCK 2.5: Helper function for formatting action params ===
def _format_action_params(
    params: Dict[str, Any],
    state_context: Dict[str, Any],
    update: Update,
    ptb_context: ContextTypes.DEFAULT_TYPE,
) -> Dict[str, Any]:
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
    process_only_on_entry: bool = False,
) -> None:
    func_total_start_time = time.monotonic()
    state_key = current_state_from_db.current_state_key
    user_id = current_state_from_db.user_id
    scenario_key = current_state_from_db.scenario_key

    local_state_context = (current_state_from_db.state_context or {}).copy()
    handler_switched_scenario = local_state_context.pop(
        _HANDLER_INITIATED_SWITCH_FLAG, False
    )

    transition_occurred = False

    logger.info(
        f"Executor: Executing state '{state_key}' for scenario '{scenario_key}' for user {user_id} (process_only_on_entry={process_only_on_entry}, handler_switched_scenario_before_actions={handler_switched_scenario})"
    )
    # logger.debug( # Слишком многословно для каждого вызова, но полезно при глубокой отладке контекста
    #     f"Executor: Initial local_state_context for '{state_key}' (after popping flag): {local_state_context}"
    # )

    states_definition = scenario_definition.get("states", {})
    current_state_config = states_definition.get(state_key)

    if not current_state_config or not isinstance(current_state_config, dict):
        logger.error(
            f"Executor: State key '{state_key}' not found or invalid in scenario '{scenario_definition.get('scenario_key', 'UNKNOWN_SCENARIO')}'. Resetting state for user {user_id}."
        )
        await reset_user_state(user_id, session) # reset_user_state теперь тоже с логированием времени
        try:
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Произошла ошибка сценария (состояние не найдено). Попробуйте /start.",
                )
        except Exception as e_send:
            logger.error(f"Executor: Failed to send error message: {e_send}")
        logger.debug(f"Executor: execute_state (state not found path) took {time.monotonic() - func_total_start_time:.4f}s")
        return

    if handler_switched_scenario:
        logger.info(
            f"Executor: Skipping on_entry and input_handlers for YAML state '{state_key}' because handler initiated scenario switch earlier."
        )
        logger.debug(f"Executor: execute_state (handler_switched_scenario path) took {time.monotonic() - func_total_start_time:.4f}s")
        return

    on_entry_actions_done_in_context = local_state_context.get(
        _ON_ENTRY_DONE_FLAG, False
    )
    if not on_entry_actions_done_in_context:
        on_entry_block_start_time = time.monotonic()
        logger.debug(
            f"Executor: Flag '{_ON_ENTRY_DONE_FLAG}' is False. Executing on_entry actions for '{state_key}'."
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

                action_handler_func = ACTION_HANDLERS.get(action_type)
                if action_handler_func:
                    action_specific_start_time = time.monotonic()
                    try:
                        logger.info(
                            f"Executor: Executing on_entry action #{action_index} for '{state_key}': {action_type} with params {action_params}"
                        )
                        if action_type == "transition_to":
                            if local_state_context.get(_HANDLER_INITIATED_SWITCH_FLAG):
                                logger.info(
                                    f"Executor: on_entry: YAML transition_to for '{state_key}' skipped because '{_HANDLER_INITIATED_SWITCH_FLAG}' is true in context."
                                )
                            else:
                                await action_handler_func(
                                    params=action_params, update=update, context=context,
                                    state_context=local_state_context, session=session,
                                    current_state_from_db=current_state_from_db,
                                )
                                transition_occurred = True
                            if transition_occurred:
                                logger.debug(f"Executor: on_entry action '{action_type}' (idx {action_index}) resulted in YAML transition, took {time.monotonic() - action_specific_start_time:.4f}s")
                                break
                        else:
                            current_action_handler_params = {
                                "params": action_params, "update": update, "context": context,
                                "state_context": local_state_context, "session": session,
                            }
                            if action_type == "call_handler":
                                current_action_handler_params["current_state_from_db"] = current_state_from_db

                            context_updates = await action_handler_func(**current_action_handler_params)
                            logger.debug(f"Executor: on_entry action '{action_type}' (idx {action_index}) handler func took {time.monotonic() - action_specific_start_time:.4f}s")


                            if isinstance(context_updates, dict):
                                local_state_context.update(context_updates)
                                if local_state_context.get(_HANDLER_INITIATED_SWITCH_FLAG):
                                    logger.info(
                                        f"Executor: on_entry: call_handler '{action_params.get('function_name')}' initiated scenario switch. Ending on_entry actions for '{state_key}'."
                                    )
                                    transition_occurred = True
                                    break
                                elif not transition_occurred:
                                    triggered_next_state = local_state_context.pop(_TRIGGER_STATE_TRANSITION_KEY, None)
                                    if triggered_next_state:
                                        logger.info(
                                            f"Executor: on_entry: call_handler '{action_params.get('function_name')}' for state '{state_key}' "
                                            f"returned '{_TRIGGER_STATE_TRANSITION_KEY}': '{triggered_next_state}'. Initiating transition."
                                        )
                                        await _handle_transition_to(
                                            params={"next_state": triggered_next_state, "set_context": {}},
                                            update=update, context=context, state_context=local_state_context,
                                            session=session, current_state_from_db=current_state_from_db,
                                        )
                                        transition_occurred = True
                                        break
                    except Exception as e:
                        logger.error(
                            f"Executor: Error in on_entry action {action_type} for '{state_key}': {e}",
                            exc_info=True,
                        )
            if transition_occurred:
                logger.info(
                    f"Executor: Transition occurred during on_entry for '{state_key}'. Further on_entry actions skipped."
                )
            else:
                local_state_context[_ON_ENTRY_DONE_FLAG] = True
                logger.debug(
                    f"Executor: Flag '{_ON_ENTRY_DONE_FLAG}' set True after on_entry for '{state_key}' (no transition occurred)."
                )
            logger.debug(f"Executor: on_entry actions block for '{state_key}' took {time.monotonic() - on_entry_block_start_time:.4f}s")
        else: # No on_entry_actions list
            local_state_context[_ON_ENTRY_DONE_FLAG] = True
            logger.debug(
                f"Executor: No on_entry list or not a list for '{state_key}'. Flag '{_ON_ENTRY_DONE_FLAG}' set True."
            )
    else: # on_entry_actions_done_in_context was True
        logger.debug(
            f"Executor: Flag '{_ON_ENTRY_DONE_FLAG}' is True for '{state_key}'. Skipping on_entry actions."
        )

    if transition_occurred:
        logger.info(
            f"Executor: Transition in on_entry for '{state_key}'. State execution for this YAML state ended."
        )
        logger.debug(f"Executor: execute_state (on_entry transition path) took {time.monotonic() - func_total_start_time:.4f}s")
        return

    if not process_only_on_entry:
        input_handlers_block_start_time = time.monotonic()
        logger.debug(
            f"Executor: process_only_on_entry is False for '{state_key}'. Proceeding to input_handlers."
        )
        input_handlers_list = current_state_config.get("input_handlers")
        if isinstance(input_handlers_list, list):
            for handler_index, handler_definition in enumerate(input_handlers_list):
                if transition_occurred:
                    break

                if not isinstance(handler_definition, dict):
                    continue
                handler_filters = handler_definition.get("filters", [])
                handler_actions = handler_definition.get("actions", [])
                
                match_filters_start_time = time.monotonic()
                match = await _match_filters(update, context, handler_filters)
                logger.debug(f"Executor: _match_filters for handler #{handler_index} took {time.monotonic() - match_filters_start_time:.4f}s. Match: {match}")

                if match:
                    logger.info(
                        f"Executor: Input matches handler #{handler_index} for state '{state_key}'. Executing actions..."
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

                            action_handler_func = ACTION_HANDLERS.get(action_type)
                            if action_handler_func:
                                action_specific_start_time = time.monotonic()
                                try:
                                    logger.info(
                                        f"Executor: Executing input_handler action #{action_index} for '{state_key}': {action_type} with params {action_params}"
                                    )
                                    if action_type == "transition_to":
                                        if local_state_context.get(_HANDLER_INITIATED_SWITCH_FLAG):
                                            logger.info(
                                                f"Executor: input_handler: YAML transition_to for '{state_key}' skipped because '{_HANDLER_INITIATED_SWITCH_FLAG}' is true in context."
                                            )
                                        else:
                                            await action_handler_func(
                                                params=action_params, update=update, context=context,
                                                state_context=local_state_context, session=session,
                                                current_state_from_db=current_state_from_db,
                                            )
                                            transition_occurred = True
                                        if transition_occurred:
                                            logger.debug(f"Executor: input_handler action '{action_type}' (idx {action_index}) resulted in YAML transition, took {time.monotonic() - action_specific_start_time:.4f}s")
                                            break
                                    else:
                                        current_action_handler_params = {
                                            "params": action_params, "update": update, "context": context,
                                            "state_context": local_state_context, "session": session,
                                        }
                                        if action_type == "call_handler":
                                            current_action_handler_params["current_state_from_db"] = current_state_from_db

                                        context_updates = await action_handler_func(**current_action_handler_params)
                                        logger.debug(f"Executor: input_handler action '{action_type}' (idx {action_index}) handler func took {time.monotonic() - action_specific_start_time:.4f}s")


                                        if isinstance(context_updates, dict):
                                            local_state_context.update(context_updates)
                                            if local_state_context.get(_HANDLER_INITIATED_SWITCH_FLAG):
                                                logger.info(
                                                    f"Executor: input_handler: call_handler '{action_params.get('function_name')}' initiated scenario switch. Ending actions for this handler."
                                                )
                                                transition_occurred = True
                                                break
                                            elif not transition_occurred:
                                                triggered_next_state = local_state_context.pop(_TRIGGER_STATE_TRANSITION_KEY, None)
                                                if triggered_next_state:
                                                    logger.info(
                                                        f"Executor: input_handler: call_handler '{action_params.get('function_name')}' for state '{state_key}' "
                                                        f"returned '{_TRIGGER_STATE_TRANSITION_KEY}': '{triggered_next_state}'. Initiating transition."
                                                    )
                                                    await _handle_transition_to(
                                                        params={"next_state": triggered_next_state, "set_context": {}},
                                                        update=update, context=context, state_context=local_state_context,
                                                        session=session, current_state_from_db=current_state_from_db,
                                                    )
                                                    transition_occurred = True
                                                    break
                                except Exception as e:
                                    logger.error(
                                        f"Executor: Error in input_handler action {action_type} for '{state_key}': {e}", exc_info=True,
                                    )
                    if transition_occurred:
                        break
                    logger.debug(
                        f"Executor: Matched input_handler #{handler_index} for '{state_key}' did not result in transition. Processing of input_handlers for this update complete."
                    )
                    break 
            logger.debug(f"Executor: input_handlers block for '{state_key}' took {time.monotonic() - input_handlers_block_start_time:.4f}s")
        else:
            logger.debug(f"Executor: No input_handlers defined for state '{state_key}'.")

        if transition_occurred:
            logger.info(
                f"Executor: Transition in input_handler for '{state_key}'. State execution for this YAML state ended."
            )
            logger.debug(f"Executor: execute_state (input_handler transition path) took {time.monotonic() - func_total_start_time:.4f}s")
            return
    else: # process_only_on_entry is True
        logger.info(
            f"Executor: process_only_on_entry is True for '{state_key}'. Skipping input_handlers."
        )

    if not transition_occurred:
        original_db_context = current_state_from_db.state_context or {}
        context_to_compare_local = local_state_context.copy()
        context_to_compare_local.pop(_HANDLER_INITIATED_SWITCH_FLAG, None)
        context_to_compare_local.pop(_TRIGGER_STATE_TRANSITION_KEY, None)

        if context_to_compare_local != original_db_context:
            logger.debug(
                f"Executor: No transition in '{state_key}'. Saving updated local_state_context for user {user_id}. Context: {local_state_context}"
            )
            context_to_save = local_state_context.copy()
            context_to_save.pop(_HANDLER_INITIATED_SWITCH_FLAG, None)
            context_to_save.pop(_TRIGGER_STATE_TRANSITION_KEY, None)

            save_context_start_time = time.monotonic()
            save_success = await update_user_state(
                user_id=user_id,
                scenario_key=scenario_key,
                state_key=state_key,
                context_data=context_to_save,
                session=session,
            )
            logger.debug(f"Executor: update_user_state (save context) took {time.monotonic() - save_context_start_time:.4f}s")
            if not save_success:
                logger.error(
                    f"Executor: Failed to save context for user {user_id} in state '{state_key}'."
                )
        else:
            logger.debug(
                f"Executor: No transition and local_state_context was not changed "
                f"since DB load for '{state_key}'. Skipping context save."
            )

    logger.info(
        f"Executor: Finished execution for state '{state_key}' (YAML state) for user {user_id}. Total time for this execute_state call: {time.monotonic() - func_total_start_time:.4f}s"
    )
# === END BLOCK 3 ===

# === BLOCK 4: Action Handlers ===
async def _handle_send_message(
    params: Dict[str, Any],
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_context: Dict[str, Any],
    session: AsyncSession,
) -> Optional[Dict[str, Any]]:
    action_start_time = time.monotonic()
    logger.debug(
        f"Executor: Executing action 'send_message' with (already formatted) params: {params}"
    )
    message_key = params.get("message_key")
    text_override = params.get("text")
    parse_mode = params.get("parse_mode")

    user = update.effective_user
    if not user:
        logger.error("Executor: Action 'send_message': Cannot determine user.")
        logger.debug(f"Executor: Action 'send_message' took {time.monotonic() - action_start_time:.4f}s (early exit)")
        return None

    final_text_to_send = None
    try:
        if text_override is not None:
            final_text_to_send = text_override
        elif message_key:
            db_call_start_time = time.monotonic()
            db_user = await session.get(UserData, user.id) # Potential DB call
            user_lang_code = db_user.language_code if db_user else None
            text_from_db = await _get_instruction_text(session, message_key, user_lang_code) # DB call
            logger.debug(f"Executor: _get_instruction_text for '{message_key}' took {time.monotonic() - db_call_start_time:.4f}s")

            if text_from_db:
                format_args_for_db_text = {
                    "first_name": user.first_name or "", "last_name": user.last_name or "",
                    "username": user.username or "", **(state_context or {}),
                }
                try:
                    final_text_to_send = text_from_db.format(**format_args_for_db_text)
                except KeyError as e:
                    logger.warning(f"Executor: KeyError formatting DB message '{message_key}': {e}. Using unformatted.")
                    final_text_to_send = text_from_db
                except Exception as fmt_e:
                    logger.error(f"Executor: Error formatting DB message '{message_key}': {fmt_e}", exc_info=True)
                    final_text_to_send = text_from_db
            else:
                final_text_to_send = f"Error: Message key '{message_key}' not found."
        else:
            logger.error("Executor: Action 'send_message' requires either 'text' or 'message_key'.")
            logger.debug(f"Executor: Action 'send_message' took {time.monotonic() - action_start_time:.4f}s (early exit)")
            return None

        if final_text_to_send is None:
            logger.error("Executor: final_text_to_send is None before sending.")
            logger.debug(f"Executor: Action 'send_message' took {time.monotonic() - action_start_time:.4f}s (early exit)")
            return None

        chat_id = update.effective_chat.id
        if chat_id:
            # Здесь можно добавить логику для reply_markup, если params его содержат
            reply_markup_params = params.get("reply_markup")
            final_reply_markup = None
            if isinstance(reply_markup_params, dict):
                logger.warning(
                    "Executor: reply_markup from YAML params not yet fully implemented in send_message action."
                )
            
            api_call_start_time = time.monotonic()
            await context.bot.send_message(chat_id=chat_id, text=final_text_to_send, parse_mode=parse_mode, reply_markup=final_reply_markup)
            logger.debug(f"Executor: Telegram API context.bot.send_message took {time.monotonic() - api_call_start_time:.4f}s")
            logger.info(f"Executor: Sent message to chat {chat_id}.")
        else: 
            logger.error("Executor: Cannot send message: chat_id is missing.")
    except Exception as e: 
        logger.error(f"Executor: Error in _handle_send_message: {e}", exc_info=True)
    logger.debug(f"Executor: Action 'send_message' total took {time.monotonic() - action_start_time:.4f}s")
    return None


async def _handle_call_ai(
    params: Dict[str, Any],
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_context: Dict[str, Any],
    session: AsyncSession,
) -> Optional[Dict[str, Any]]:
    action_start_time = time.monotonic()
    logger.debug(f"Executor: Executing action 'call_ai' with (already formatted) params: {params}")
    prompt_key = params.get("prompt_key")
    system_prompt_override = params.get("system_prompt_override")
    save_to = params.get("save_to")
    history_context_key = params.get("history_context_key")
    user_reply_for_format = params.get("user_reply_for_format")

    if not (prompt_key or system_prompt_override) or not save_to:
        logger.error("Executor: 'call_ai' action requires 'save_to' and ('prompt_key' or 'system_prompt_override').")
        logger.debug(f"Executor: Action 'call_ai' took {time.monotonic() - action_start_time:.4f}s (early exit)")
        return {save_to: "ERROR: AI call misconfigured"}
    
    user = update.effective_user
    if not user: 
        logger.error("Executor: Action 'call_ai': Cannot determine user.")
        logger.debug(f"Executor: Action 'call_ai' took {time.monotonic() - action_start_time:.4f}s (early exit)")
        return {save_to: "ERROR: User not found"}
    
    returned_payload = {save_to: None} # Default payload in case of issues
    try:
        db_user_call_start_time = time.monotonic()
        db_user = await session.get(UserData, user.id) # Potential DB call
        logger.debug(f"Executor: session.get(UserData) for call_ai took {time.monotonic() - db_user_call_start_time:.4f}s")
        user_lang_code = db_user.language_code if db_user else None

        messages_history = []
        if history_context_key:
            history_from_context = state_context.get(history_context_key)
            if isinstance(history_from_context, list): messages_history.extend(history_from_context)
        
        if not messages_history:
            current_user_input_text = getattr(getattr(update, "message", None), "text", None) or getattr(getattr(update, "callback_query", None), "data", None)
            if current_user_input_text: messages_history.append({"role": "user", "content": str(current_user_input_text)})
            elif user_reply_for_format: messages_history.append({"role": "user", "content": str(user_reply_for_format)})
        
        ai_call_start_time = time.monotonic()
        ai_response = await generate_text_response(
            messages=messages_history, instruction_key=prompt_key, 
            user_lang_code=user_lang_code, session=session, 
            system_prompt_override=system_prompt_override, 
            user_reply_for_format=user_reply_for_format
        )
        logger.debug(f"Executor: AI call (generate_text_response internal) took {time.monotonic() - ai_call_start_time:.4f}s")

        if ai_response is not None:
            logger.info(f"Executor: AI response received: '{ai_response[:70]}...'")
            returned_payload = {save_to: ai_response}
        else:
            logger.error("Executor: AI call returned None.")
            returned_payload = {save_to: None}
    except Exception as e:
        logger.error(f"Executor: Error in _handle_call_ai: {e}", exc_info=True)
        returned_payload = {save_to: f"ERROR_AI_CALL: {type(e).__name__}"}
    
    logger.debug(f"Executor: Action 'call_ai' total took {time.monotonic() - action_start_time:.4f}s")
    return returned_payload


async def _handle_call_handler(
    params: Dict[str, Any],
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_context: Dict[str, Any],
    session: AsyncSession,
    current_state_from_db: UserStates,
) -> Optional[Dict[str, Any]]:
    action_start_time = time.monotonic()
    function_name_str = params.get("function_name")
    save_result_to = params.get("save_result_to")
    logger.debug(f"Executor: Executing action 'call_handler' for '{function_name_str}' with params: {params}")
    
    if not function_name_str:
        logger.error("Executor: 'call_handler' requires 'function_name' parameter.")
        error_payload = {"error_calling_handler": "Missing function_name"}
        if save_result_to: error_payload[save_result_to] = "ERROR: Missing function_name"
        logger.debug(f"Executor: Action 'call_handler' for '{function_name_str}' took {time.monotonic() - action_start_time:.4f}s (early exit)")
        return error_payload

    returned_payload = {}
    try:
        module_path, func_name = function_name_str.rsplit(".", 1)
        module = importlib.import_module(module_path)
        handler_func_to_call = getattr(module, func_name)

        if not inspect.iscoroutinefunction(handler_func_to_call):
            logger.error(f"Executor: Handler function '{function_name_str}' is not an async function.")
            error_val = f"ERROR: Handler '{function_name_str}' not async"
            returned_payload = {"error_calling_handler": error_val}
            if save_result_to: returned_payload[save_result_to] = error_val
            raise TypeError(error_val) # Raise to be caught by generic exception

        sig = inspect.signature(handler_func_to_call)
        handler_kwargs = {}
        if "update" in sig.parameters: handler_kwargs["update"] = update
        if "context" in sig.parameters: handler_kwargs["context"] = context
        if "session" in sig.parameters: handler_kwargs["session"] = session
        if "state_context" in sig.parameters: handler_kwargs["state_context"] = state_context.copy()
        if "current_state_from_db" in sig.parameters: handler_kwargs["current_state_from_db"] = current_state_from_db

        logger.info(f"Executor: Calling custom handler: {function_name_str} with args: {list(handler_kwargs.keys())}")
        
        handler_call_start_time = time.monotonic()
        returned_value_from_handler = await handler_func_to_call(**handler_kwargs)
        logger.debug(f"Executor: Custom handler '{function_name_str}' execution took {time.monotonic() - handler_call_start_time:.4f}s")
        
        logger.info(f"Executor: Custom handler '{function_name_str}' returned type: {type(returned_value_from_handler)}, value: '{str(returned_value_from_handler)[:100]}...'")

        if isinstance(returned_value_from_handler, dict):
            returned_payload.update(returned_value_from_handler)
        elif returned_value_from_handler is not None and not save_result_to:
            logger.warning(f"Executor: Handler '{function_name_str}' returned a non-dict/non-None value but no 'save_result_to' was specified. Return value ignored: {returned_value_from_handler}")
        
        if save_result_to:
            returned_payload[save_result_to] = returned_value_from_handler
            logger.debug(f"Executor: Result from handler '{function_name_str}' will be saved to context key '{save_result_to}'.")
        
    except (ModuleNotFoundError, AttributeError) as e_import:
        logger.error(f"Executor: Could not import/find handler '{function_name_str}': {e_import}")
        error_val = f"ERROR: Handler not found - {function_name_str}"
        returned_payload = {save_result_to: error_val} if save_result_to else {"error_calling_handler": error_val}
    except TypeError as e_type:
        logger.error(f"Executor: TypeError executing custom handler '{function_name_str}': {e_type}", exc_info=True)
        error_val = f"ERROR: Handler TypeError - {type(e_type).__name__}"
        returned_payload = {save_result_to: error_val} if save_result_to else {"error_calling_handler": error_val}
    except Exception as e:
        logger.error(f"Executor: Error executing custom handler '{function_name_str}': {e}", exc_info=True)
        error_val = f"ERROR: Handler execution failed - {type(e).__name__}"
        returned_payload = {save_result_to: error_val} if save_result_to else {"error_calling_handler": error_val}
    
    logger.debug(f"Executor: Action 'call_handler' for '{function_name_str}' total took {time.monotonic() - action_start_time:.4f}s")
    return returned_payload


async def _handle_transition_to(
    params: Dict[str, Any],
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_context: Dict[str, Any],
    session: AsyncSession,
    current_state_from_db: UserStates,
) -> None:
    action_start_time = time.monotonic()
    next_state_key = params.get("next_state")
    context_to_set_from_yaml = params.get("set_context", {})
    logger.debug(
        f"Executor: Executing action 'transition_to' to '{next_state_key}' with params: {params}"
    )

    if not next_state_key or not isinstance(next_state_key, str):
        logger.error(f"Executor: 'transition_to' action requires a valid 'next_state' string parameter. Got: {next_state_key}")
        logger.debug(f"Executor: Action 'transition_to' took {time.monotonic() - action_start_time:.4f}s (early exit)")
        return

    if not isinstance(context_to_set_from_yaml, dict):
        logger.warning("Executor: 'set_context' for transition_to should be a dict. Using empty.")
        context_to_set_from_yaml = {}

    final_context_for_next_state = state_context.copy()
    final_context_for_next_state.update(context_to_set_from_yaml)
    
    final_context_for_next_state.pop(_ON_ENTRY_DONE_FLAG, None)
    final_context_for_next_state.pop(_HANDLER_INITIATED_SWITCH_FLAG, None)
    final_context_for_next_state.pop(_TRIGGER_STATE_TRANSITION_KEY, None)

    logger.info(
        f"Executor: Transitioning user {current_state_from_db.user_id} from (YAML state) '{current_state_from_db.current_state_key}' "
        f"in scenario '{current_state_from_db.scenario_key}' to (new state) '{next_state_key}'. "
        f"Context for new state (after YAML set_context and flag clearing): {final_context_for_next_state}"
    )
    
    update_db_start_time = time.monotonic()
    updated_db_state = await update_user_state(
        user_id=current_state_from_db.user_id,
        scenario_key=current_state_from_db.scenario_key,
        state_key=next_state_key,
        context_data=final_context_for_next_state,
        session=session,
    )
    logger.debug(f"Executor: DB update_user_state in transition_to took {time.monotonic() - update_db_start_time:.4f}s")

    if not updated_db_state:
        logger.error(f"Executor: Transition failed for user {current_state_from_db.user_id}: state update error in DB (target state: '{next_state_key}').")
    else:
        logger.info(f"Executor: Transition successful for user {current_state_from_db.user_id}, DB state updated to: scenario='{updated_db_state.scenario_key}', state='{updated_db_state.current_state_key}'.")
    logger.debug(f"Executor: Action 'transition_to' to '{next_state_key}' total took {time.monotonic() - action_start_time:.4f}s")

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
    # Этот блок не изменялся для логирования времени, т.к. обычно он очень быстрый.
    # Если есть подозрения, можно добавить аналогичное логирование.
    if not isinstance(filters_config, list):
        logger.warning(
            f"Executor: Filter matching failed: filters_config is not a list: {filters_config}"
        )
        return False
    if not filters_config:
        logger.debug("Executor: Empty filter list in input_handler matches any input by default.")
        return True

    all_match = True
    for filter_index, filter_item in enumerate(filters_config):
        if not isinstance(filter_item, dict):
            logger.warning(
                f"Executor: Invalid filter item format #{filter_index} (expected dict): {filter_item}"
            )
            all_match = False
            break

        filter_type = filter_item.get("type")
        # logger.debug(f"Executor: Checking filter #{filter_index}: {filter_item}") # Может быть слишком многословно
        match_this_filter = False

        if filter_type == "message":
            if update.message:
                content_type = filter_item.get("content_type")
                content_type_matched = False
                if (
                    not content_type
                    or (
                        content_type == "text"
                        and getattr(update.message, "text", None) is not None
                    )
                    or (
                        content_type == "photo"
                        and getattr(update.message, "photo", None)
                    ) 
                    or ( 
                        content_type == "document"
                        and getattr(update.message, "document", None)
                    )
                ):
                    content_type_matched = True
                elif content_type: 
                    # logger.debug(f"Executor: Filter type 'message': content_type '{content_type}' mismatch.") # Многословно
                    pass


                if not content_type_matched:
                    all_match = False
                    break

                if content_type == "text" or not content_type: # Process text conditions only if it's a text message or no content_type specified
                    message_text = getattr(update.message, "text", None)
                    if message_text is not None: # Text message exists
                        text_exact = filter_item.get("text")
                        if text_exact is not None and message_text != text_exact:
                            all_match = False; break
                        text_regex_str = filter_item.get("regex")
                        if text_regex_str is not None:
                            try:
                                if not re.fullmatch(text_regex_str, message_text):
                                    all_match = False; break
                            except re.error as re_err:
                                logger.error(f"Executor: Invalid regex pattern '{text_regex_str}': {re_err}")
                                all_match = False; break
                    elif (filter_item.get("text") is not None or filter_item.get("regex") is not None): # Text conditions exist but it's not a text message
                        all_match = False; break
                match_this_filter = True
            else: 
                all_match = False; break
        elif filter_type == "callback_query":
            callback_data_val = getattr(getattr(update, "callback_query", None), "data", None)
            if update.callback_query and callback_data_val is not None:
                data_exact = filter_item.get("data")
                if data_exact is not None and callback_data_val != data_exact:
                    all_match = False; break
                data_pattern_str = filter_item.get("pattern")
                if data_pattern_str is not None:
                    try:
                        if not re.fullmatch(data_pattern_str, callback_data_val):
                            all_match = False; break
                    except re.error as re_err:
                        logger.error(f"Executor: Invalid regex pattern for callback_data '{data_pattern_str}': {re_err}")
                        all_match = False; break
                match_this_filter = True
            else: 
                all_match = False; break
        elif filter_type == "command":
            message_text = getattr(getattr(update, "message", None), "text", None)
            if update.message and message_text and message_text.startswith("/"):
                command_expected = filter_item.get("command")
                if command_expected:
                    command_expected_clean = command_expected.lstrip("/")
                    actual_command_parts = message_text.split(maxsplit=1)
                    actual_command = actual_command_parts[0][1:]
                    if actual_command == command_expected_clean:
                        match_this_filter = True
                    else:
                        all_match = False; break
                else:
                    logger.warning("Executor: Filter type 'command' but 'command' parameter missing.")
                    all_match = False; break
            else: 
                all_match = False; break
        else:
            logger.warning(f"Executor: Unknown filter type '{filter_type}'.")
            all_match = False; break

        if not match_this_filter: # Should be redundant if breaks are used above, but as a safeguard
            all_match = False; break

    if all_match:
        logger.info(f"Executor: Update {update.update_id} MATCHED ALL filters in the list.")
    # else: # Этот лог может быть слишком частым, если фильтры не совпали
        # logger.debug(f"Executor: Update {update.update_id} did NOT match all filters in the list.")
    return all_match
# === END BLOCK 5 ===

# === END BLOCK: BehaviorEngine/executor.py (Конец файла) ===