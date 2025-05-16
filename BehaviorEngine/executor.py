# === BLOCK: BehaviorEngine/executor.py (Начало файла) ===
# BehaviorEngine/executor.py
# Версия с флагом process_only_on_entry и обработкой handler_initiated_scenario_switch

# === BLOCK 1: Imports ===
import importlib
import inspect
import logging
import re
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

    # UserStates нужен для type hint current_state_from_db
    from .state_manager import (
        reset_user_state,
        update_user_state,
    )
except ImportError as e:
    logging.getLogger(__name__).critical(  # Используем getLogger(__name__)
        f"CRITICAL: Failed to import modules/models/helpers in executor: {e}",
        exc_info=True,
    )
    raise
# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
_ON_ENTRY_DONE_FLAG = "_internal_on_entry_actions_done"
_HANDLER_INITIATED_SWITCH_FLAG = "handler_initiated_scenario_switch"  # Новый флаг
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
    state_key = current_state_from_db.current_state_key
    user_id = current_state_from_db.user_id
    scenario_key = current_state_from_db.scenario_key

    local_state_context = (current_state_from_db.state_context or {}).copy()
    # Этот флаг будет установлен хэндлером, если он сам переключил сценарий/состояние
    handler_switched_scenario = local_state_context.pop(
        _HANDLER_INITIATED_SWITCH_FLAG, False
    )

    transition_occurred = False  # Флаг для внутренних переходов этого состояния YAML

    logger.info(
        f"Executing state '{state_key}' for scenario '{scenario_key}' for user {user_id} (process_only_on_entry={process_only_on_entry}, handler_switched_scenario_before_actions={handler_switched_scenario})"
    )
    logger.debug(
        f"Initial local_state_context for '{state_key}' (after popping flag): {local_state_context}"
    )

    states_definition = scenario_definition.get("states", {})
    current_state_config = states_definition.get(state_key)

    if not current_state_config or not isinstance(current_state_config, dict):
        logger.error(
            f"State key '{state_key}' not found or invalid in scenario '{scenario_definition.get('scenario_key', 'UNKNOWN_SCENARIO')}'. Resetting state for user {user_id}."
        )  # Добавил имя сценария в лог
        await reset_user_state(user_id, session)
        try:
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Произошла ошибка сценария (состояние не найдено). Попробуйте /start.",
                )
        except Exception as e_send:
            logger.error(f"Failed to send error message: {e_send}")
        return

    # --- Обработка on_entry ---
    # Если хэндлер (например, из предыдущего состояния) уже переключил сценарий,
    # то on_entry этого "промежуточного" состояния YAML не должен выполняться.
    # Однако, on_entry НОВОГО состояния (в новом сценарии) ДОЛЖЕН выполниться.
    # Это управляется циклом в engine.py и флагом process_only_on_entry.
    # Здесь handler_switched_scenario означает, что хэндлер, вызванный *из предыдущего* YAML состояния, уже всё сделал.

    if handler_switched_scenario:
        logger.info(
            f"Skipping on_entry and input_handlers for YAML state '{state_key}' because handler initiated scenario switch earlier."
        )
        # Контекст уже должен быть сохранен или будет сохранен для нового состояния.
        # Ничего не делаем здесь, engine.py перейдет к обработке нового состояния пользователя.
        return

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

                action_handler_func = ACTION_HANDLERS.get(
                    action_type
                )  # Переименовал для ясности
                if action_handler_func:
                    try:
                        logger.info(
                            f"Executing on_entry action #{action_index} for '{state_key}': {action_type} with params {action_params}"
                        )
                        if action_type == "transition_to":
                            # ИЗМЕНЕНИЕ: Проверяем флаг перед YAML-переходом
                            if local_state_context.get(_HANDLER_INITIATED_SWITCH_FLAG):
                                logger.info(
                                    f"on_entry: YAML transition_to for '{state_key}' skipped because '{_HANDLER_INITIATED_SWITCH_FLAG}' is true in context."
                                )
                            else:
                                await action_handler_func(
                                    params=action_params,
                                    update=update,
                                    context=context,
                                    state_context=local_state_context,
                                    session=session,
                                    current_state_from_db=current_state_from_db,
                                )
                                transition_occurred = True
                            if transition_occurred:  # Если был YAML переход
                                break  # Выходим из цикла on_entry_actions
                        else:  # send_message, call_ai, call_handler
                            current_action_handler_params = {
                                "params": action_params,
                                "update": update,
                                "context": context,
                                "state_context": local_state_context,
                                "session": session,
                            }
                            if action_type == "call_handler":
                                current_action_handler_params[
                                    "current_state_from_db"
                                ] = current_state_from_db

                            context_updates = await action_handler_func(
                                **current_action_handler_params
                            )

                            if isinstance(context_updates, dict):
                                local_state_context.update(context_updates)
                                # ПРОВЕРКА: если call_handler сам переключил сценарий
                                if local_state_context.get(
                                    _HANDLER_INITIATED_SWITCH_FLAG
                                ):
                                    logger.info(
                                        f"on_entry: call_handler '{action_params.get('function_name')}' initiated scenario switch. Ending on_entry actions for '{state_key}'."
                                    )
                                    transition_occurred = True  # Особый вид перехода - за пределы этого YAML
                                    # Важно: handler_switched_scenario будет true для следующей итерации engine
                                    # но здесь мы просто прерываем дальнейшие действия в этом YAML-состоянии
                                    break  # Выходим из цикла on_entry_actions
                    except Exception as e:
                        logger.error(
                            f"Error in on_entry action {action_type} for '{state_key}': {e}",
                            exc_info=True,
                        )
            if transition_occurred:  # Если любой переход произошел (YAML или хэндлер)
                logger.info(
                    f"Transition occurred during on_entry for '{state_key}'. Further on_entry actions skipped."
                )
                # Если переход был инициирован хэндлером, local_state_context[_HANDLER_INITIATED_SWITCH_FLAG] уже должен быть True
                # и будет сохранен с новым состоянием пользователя.
                # Если переход был через YAML transition_to, то _HANDLER_INITIATED_SWITCH_FLAG не будет.
                # Флаг _ON_ENTRY_DONE_FLAG для текущего состояния не ставим, т.к. мы его покидаем.
            else:  # Перехода не было, on_entry завершен для этого состояния
                local_state_context[_ON_ENTRY_DONE_FLAG] = True
                logger.debug(
                    f"Flag '{_ON_ENTRY_DONE_FLAG}' set True after on_entry for '{state_key}' (no transition occurred)."
                )
        else:  # Нет списка on_entry_actions
            local_state_context[_ON_ENTRY_DONE_FLAG] = True
            logger.debug(
                f"No on_entry list or not a list for '{state_key}'. Flag '{_ON_ENTRY_DONE_FLAG}' set True."
            )
    else:  # on_entry_actions_done_in_context был True
        logger.debug(
            f"Flag '{_ON_ENTRY_DONE_FLAG}' is True for '{state_key}'. Skipping on_entry actions."
        )

    if transition_occurred:  # Если переход был из on_entry (YAML или хэндлер)
        logger.info(
            f"Transition in on_entry for '{state_key}'. State execution for this YAML state ended."
        )
        return

    # --- Обработка input_handlers (только если process_only_on_entry is False) ---
    if not process_only_on_entry:
        logger.debug(
            f"process_only_on_entry is False for '{state_key}'. Proceeding to input_handlers."
        )
        input_handlers_list = current_state_config.get("input_handlers")
        if isinstance(input_handlers_list, list):
            for handler_index, handler_definition in enumerate(input_handlers_list):
                if transition_occurred:
                    break  # Если предыдущее действие в этом input_handler сделало переход

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

                            action_handler_func = ACTION_HANDLERS.get(action_type)
                            if action_handler_func:
                                try:
                                    logger.info(
                                        f"Executing input_handler action #{action_index} for '{state_key}': {action_type} with params {action_params}"
                                    )
                                    if action_type == "transition_to":
                                        # ИЗМЕНЕНИЕ: Проверяем флаг перед YAML-переходом
                                        if local_state_context.get(
                                            _HANDLER_INITIATED_SWITCH_FLAG
                                        ):
                                            logger.info(
                                                f"input_handler: YAML transition_to for '{state_key}' skipped because '{_HANDLER_INITIATED_SWITCH_FLAG}' is true in context."
                                            )
                                        else:
                                            await action_handler_func(
                                                params=action_params,
                                                update=update,
                                                context=context,
                                                state_context=local_state_context,
                                                session=session,
                                                current_state_from_db=current_state_from_db,
                                            )
                                            transition_occurred = True
                                        if transition_occurred:  # Если был YAML переход
                                            break  # Выходим из цикла handler_actions (этого input_handler)
                                    else:  # send_message, call_ai, call_handler
                                        current_action_handler_params = {
                                            "params": action_params,
                                            "update": update,
                                            "context": context,
                                            "state_context": local_state_context,
                                            "session": session,
                                        }
                                        if action_type == "call_handler":
                                            current_action_handler_params[
                                                "current_state_from_db"
                                            ] = current_state_from_db

                                        context_updates = await action_handler_func(
                                            **current_action_handler_params
                                        )

                                        if isinstance(context_updates, dict):
                                            local_state_context.update(context_updates)
                                            # ПРОВЕРКА: если call_handler сам переключил сценарий
                                            if local_state_context.get(
                                                _HANDLER_INITIATED_SWITCH_FLAG
                                            ):
                                                logger.info(
                                                    f"input_handler: call_handler '{action_params.get('function_name')}' initiated scenario switch. Ending actions for this handler."
                                                )
                                                transition_occurred = True
                                                break  # Выходим из цикла handler_actions (этого input_handler)
                                except Exception as e:
                                    logger.error(
                                        f"Error in input_handler action {action_type} for '{state_key}': {e}",
                                        exc_info=True,
                                    )
                    if (
                        transition_occurred
                    ):  # Если переход был из этого input_handler (YAML или хэндлер)
                        break  # Выходим из основного цикла input_handlers_list
                    # Если match, но не было transition_occurred, все равно выходим, т.к. один input_handler сработал
                    logger.debug(
                        f"Matched input_handler #{handler_index} for '{state_key}' did not result in transition. Processing of input_handlers for this update complete."
                    )
                    break
        else:  # Нет input_handlers_list
            logger.debug(f"No input_handlers defined for state '{state_key}'.")

        if transition_occurred:  # Если переход был из input_handlers (YAML или хэндлер)
            logger.info(
                f"Transition in input_handler for '{state_key}'. State execution for this YAML state ended."
            )
            return
    else:  # process_only_on_entry is True
        logger.info(
            f"process_only_on_entry is True for '{state_key}'. Skipping input_handlers."
        )

    # --- Сохранение контекста, если не было перехода И контекст изменился (и это не был handler_switched_scenario) ---
    # handler_switched_scenario уже проверен в самом начале функции.
    # Если мы дошли сюда, и transition_occurred (внутренний YAML переход) НЕ случился,
    # И on_entry был выполнен (или пропущен, если уже был выполнен ранее),
    # то сохраняем контекст.
    if not transition_occurred:
        # Сравниваем только те ключи, которые не являются внутренними флагами executor-а
        # (хотя _ON_ENTRY_DONE_FLAG мы хотим сохранять)
        # Если local_state_context был изменен (например, через call_ai или call_handler без перехода)
        # ИЛИ если _ON_ENTRY_DONE_FLAG был установлен впервые.
        original_db_context = current_state_from_db.state_context or {}

        # Создаем копии для сравнения, исключая наш временный флаг _HANDLER_INITIATED_SWITCH_FLAG, если он там остался
        # (хотя мы его должны были pop-нуть в начале)
        context_to_compare_local = local_state_context.copy()
        context_to_compare_local.pop(_HANDLER_INITIATED_SWITCH_FLAG, None)

        if context_to_compare_local != original_db_context:
            logger.debug(
                f"No transition in '{state_key}'. Saving updated local_state_context for user {user_id}. Context: {local_state_context}"
            )
            # Убираем флаг _HANDLER_INITIATED_SWITCH_FLAG перед сохранением, если он там каким-то образом остался
            context_to_save = local_state_context.copy()
            context_to_save.pop(_HANDLER_INITIATED_SWITCH_FLAG, None)

            save_success = await update_user_state(
                user_id=user_id,
                scenario_key=scenario_key,  # Используем scenario_key текущего YAML состояния
                state_key=state_key,  # Сохраняем для текущего YAML состояния
                context_data=context_to_save,
                session=session,
            )
            if not save_success:
                logger.error(
                    f"Failed to save context for user {user_id} in state '{state_key}'."
                )
        else:
            logger.debug(
                f"No transition and local_state_context was not changed (or only internal flags changed temporarily) "
                f"since DB load for '{state_key}'. Skipping context save."
            )

    logger.info(
        f"Finished execution for state '{state_key}' (YAML state) for user {user_id}."
    )


# === END BLOCK 3 ===


# === BLOCK 4: Action Handlers ===
async def _handle_send_message(
    params: Dict[str, Any],
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_context: Dict[str, Any],
    session: AsyncSession,
    # current_state_from_db не нужен для send_message
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
                    **(
                        state_context or {}
                    ),  # Добавляем весь state_context для форматирования
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
            # Здесь можно добавить логику для reply_markup, если params его содержат
            reply_markup_params = params.get("reply_markup")
            final_reply_markup = None
            if isinstance(reply_markup_params, dict):
                # TODO: Реализовать сборку InlineKeyboardMarkup из словаря reply_markup_params
                # Например: final_reply_markup = InlineKeyboardMarkup(...)
                logger.warning(
                    "reply_markup from YAML params not yet fully implemented in send_message action."
                )

            await context.bot.send_message(
                chat_id=chat_id,
                text=final_text_to_send,
                parse_mode=parse_mode,
                reply_markup=final_reply_markup,
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
    # current_state_from_db не нужен для call_ai
) -> Optional[Dict[str, Any]]:
    logger.debug(
        f"Executing action 'call_ai' with (already formatted) params: {params}"
    )
    prompt_key = params.get("prompt_key")
    system_prompt_override = params.get("system_prompt_override")
    save_to = params.get("save_to")
    history_context_key = params.get("history_context_key")
    user_reply_for_format = params.get(
        "user_reply_for_format"
    )  # Это уже отформатировано _format_action_params

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

        # Собираем историю сообщений
        messages_history = []
        if history_context_key:
            history_from_context = state_context.get(history_context_key)
            if isinstance(history_from_context, list):
                messages_history.extend(history_from_context)

        # Добавляем текущий ответ пользователя в историю, если он еще не там и это не первый ход
        # (Обычно user_reply_for_format используется для подстановки в системный промпт)
        # Для большинства классификаторов и простых вызовов, messages_history может быть просто текущим сообщением пользователя
        if not messages_history:
            current_user_input_text = getattr(
                getattr(update, "message", None), "text", None
            ) or getattr(getattr(update, "callback_query", None), "data", None)
            if current_user_input_text:
                messages_history.append(
                    {"role": "user", "content": str(current_user_input_text)}
                )
            elif (
                user_reply_for_format
            ):  # Если есть user_reply_for_format, но нет истории и нет текущего ввода
                messages_history.append(
                    {"role": "user", "content": str(user_reply_for_format)}
                )

        ai_response = await generate_text_response(
            messages=messages_history,  # Передаем историю
            instruction_key=prompt_key,
            user_lang_code=user_lang_code,
            session=session,
            system_prompt_override=system_prompt_override,
            user_reply_for_format=user_reply_for_format,  # Уже отформатированный из params
        )

        if ai_response is not None:
            logger.info(f"AI response received: '{ai_response[:70]}...'")
            return {save_to: ai_response}
        else:
            logger.error("AI call returned None.")
            return {save_to: None}
    except Exception as e:
        logger.error(f"Error in _handle_call_ai: {e}", exc_info=True)
        return {save_to: f"ERROR_AI_CALL: {type(e).__name__}"}


async def _handle_call_handler(
    params: Dict[str, Any],
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_context: Dict[str, Any],
    session: AsyncSession,
    current_state_from_db: UserStates,  # Добавлен для отслеживания изменений
) -> Optional[Dict[str, Any]]:
    logger.debug(
        f"Executing action 'call_handler' with (already formatted) params: {params}"
    )
    function_name_str = params.get("function_name")
    save_result_to = params.get("save_result_to")
    pass_state_context = params.get("pass_state_context", True)

    if not function_name_str:
        logger.error("'call_handler' requires 'function_name' parameter.")
        # Если save_result_to указан, возвращаем ошибку туда, иначе None
        return (
            {save_result_to: "ERROR: Missing function_name"} if save_result_to else None
        )

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

        sig = inspect.signature(handler_func_to_call)
        handler_kwargs = {}
        if "update" in sig.parameters:
            handler_kwargs["update"] = update
        if "context" in sig.parameters:
            handler_kwargs["context"] = context
        if "session" in sig.parameters:
            handler_kwargs["session"] = session
        if pass_state_context and "state_context" in sig.parameters:
            # Передаем копию, чтобы хэндлер не мог случайно изменить наш local_state_context напрямую,
            # а только через возвращаемое значение.
            handler_kwargs["state_context"] = state_context.copy()
        # Можно добавить передачу current_state_from_db, если хэндлер его ожидает
        # if "current_state_from_db" in sig.parameters:
        #    handler_kwargs["current_state_from_db"] = current_state_from_db

        logger.info(
            f"Calling custom handler: {function_name_str} with args: {list(handler_kwargs.keys())}"
        )
        returned_value = await handler_func_to_call(**handler_kwargs)
        logger.info(
            f"Custom handler '{function_name_str}' returned type: {type(returned_value)}, value: '{str(returned_value)[:100]}...'"
        )

        # ВАЖНО: `evaluate_role_and_get_next_state` теперь возвращает `handler_initiated_scenario_switch: True`
        # Это значение будет смержено в `local_state_context` в `execute_state`
        # И `execute_state` затем проверит этот флаг.

        if save_result_to:
            # Если хэндлер вернул словарь, и мы сохраняем в один ключ,
            # то значением этого ключа будет весь словарь от хэндлера.
            # Если хэндлер вернул не словарь, то просто это значение.
            return {save_result_to: returned_value}
        elif isinstance(returned_value, dict):
            # Если не указан save_result_to, но хэндлер вернул словарь,
            # этот словарь будет смержен с local_state_context в execute_state.
            return returned_value

        # Если хэндлер ничего не вернул (None) или вернул не словарь и нет save_result_to,
        # то контекст не изменится этим хэндлером (кроме флага, если он его установил).
        return None

    except (ModuleNotFoundError, AttributeError) as e_import:
        logger.error(f"Could not import/find handler '{function_name_str}': {e_import}")
        return (
            {save_result_to: f"ERROR: Handler not found - {function_name_str}"}
            if save_result_to
            else None
        )
    except TypeError as e_type:
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
    state_context: Dict[
        str, Any
    ],  # Этот state_context используется для формирования контекста нового состояния
    session: AsyncSession,
    current_state_from_db: UserStates,  # Используется для scenario_key и user_id
) -> None:  # Этот хэндлер не должен возвращать ничего для обновления контекста, он сам меняет состояние в БД
    logger.debug(
        f"Executing action 'transition_to' with (already formatted) params: {params}"
    )

    next_state_key = params.get(
        "next_state"
    )  # Это уже отформатировано (плейсхолдеры заменены)
    context_to_set_from_yaml = params.get("set_context", {})  # Это тоже отформатировано

    if not next_state_key or not isinstance(next_state_key, str):
        logger.error(
            f"'transition_to' action requires a valid 'next_state' string parameter. Got: {next_state_key}"
        )
        return
    if not isinstance(context_to_set_from_yaml, dict):
        logger.warning("'set_context' for transition_to should be a dict. Using empty.")
        context_to_set_from_yaml = {}

    # Формируем контекст для НОВОГО состояния:
    # 1. Берем текущий state_context (local_state_context из execute_state).
    # 2. Обновляем его тем, что указано в 'set_context' в YAML для этого transition_to.
    # 3. Очищаем флаг _ON_ENTRY_DONE_FLAG, чтобы on_entry нового состояния выполнился.
    # 4. Очищаем флаг _HANDLER_INITIATED_SWITCH_FLAG, если он там был.

    final_context_for_next_state = (
        state_context.copy()
    )  # local_state_context из execute_state
    final_context_for_next_state.update(context_to_set_from_yaml)
    final_context_for_next_state.pop(_ON_ENTRY_DONE_FLAG, None)
    final_context_for_next_state.pop(
        _HANDLER_INITIATED_SWITCH_FLAG, None
    )  # Убираем этот флаг

    # Важно: current_state_from_db.current_state_key здесь - это ключ ТЕКУЩЕГО YAML-состояния, из которого мы переходим.
    logger.info(
        f"Transitioning user {current_state_from_db.user_id} from (YAML state) '{current_state_from_db.current_state_key}' "
        f"in scenario '{current_state_from_db.scenario_key}' to (new state) '{next_state_key}'. "
        f"Context for new state: {final_context_for_next_state}"
    )

    updated_db_state = await update_user_state(
        user_id=current_state_from_db.user_id,
        scenario_key=current_state_from_db.scenario_key,  # Сценарий остается тот же, если не был изменен хэндлером ранее
        state_key=next_state_key,
        context_data=final_context_for_next_state,
        session=session,
    )
    if not updated_db_state:
        logger.error(
            f"Transition failed for user {current_state_from_db.user_id}: state update error in DB "
            f"(target state: '{next_state_key}')."
        )
    else:
        logger.info(
            f"Transition successful for user {current_state_from_db.user_id}, "
            f"DB state updated to: scenario='{updated_db_state.scenario_key}', state='{updated_db_state.current_state_key}'."
        )
        # Обновляем current_state_from_db, чтобы execute_state видел актуальное состояние
        # Это важно, если current_state_from_db передается по ссылке и используется дальше в execute_state
        # current_state_from_db = updated_db_state # Это не сработает, т.к. это локальная переменная.
        # Вместо этого, execute_state должен будет перечитать состояние или обновить свой объект current_state_from_db.
        # Но update_user_state делает refresh(), так что объект в сессии должен быть обновлен.


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
    if not filters_config:
        logger.debug("Empty filter list in input_handler matches any input by default.")
        return True

    all_match = True
    for filter_index, filter_item in enumerate(filters_config):
        if not isinstance(filter_item, dict):
            logger.warning(
                f"Invalid filter item format #{filter_index} (expected dict): {filter_item}"
            )
            all_match = False
            break

        filter_type = filter_item.get("type")
        logger.debug(f"Checking filter #{filter_index}: {filter_item}")
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
                        and getattr(
                            update.message, "photo", None
                        )  # Проверяем наличие фото
                    )  # Добавил скобку
                    or (  # Добавил OR и скобки для "document"
                        content_type == "document"
                        and getattr(update.message, "document", None)
                    )
                ):
                    content_type_matched = True
                elif content_type:  # Если content_type указан, но не совпал
                    logger.debug(
                        f"Filter type 'message': content_type '{content_type}' mismatch."
                    )

                if not content_type_matched:
                    all_match = False
                    break

                if content_type == "text" or not content_type:
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
                    elif (
                        filter_item.get("text") is not None
                        or filter_item.get("regex") is not None
                    ):
                        all_match = False
                        break
                match_this_filter = True
            else:  # update.message отсутствует
                all_match = False
                break
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
                match_this_filter = True
            else:  # update.callback_query отсутствует
                all_match = False
                break
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
            else:  # не сообщение или не команда
                all_match = False
                break
        else:
            logger.warning(f"Unknown filter type '{filter_type}'.")
            all_match = False
            break

        if not match_this_filter:
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

# === END BLOCK: BehaviorEngine/executor.py (Конец файла) ===
