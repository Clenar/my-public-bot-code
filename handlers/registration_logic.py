# === BLOCK: handlers/registration_logic.py (Начало файла - Полная версия с исправлением NameError, оптимизацией и логированием времени) ===
# handlers/registration_logic.py

# === BLOCK 1: Imports ===
import json
import logging
import time 
from contextlib import suppress
from typing import Any, Dict, List, Optional

import telegram 

from sqlalchemy import select, func
from sqlalchemy.sql.expression import literal_column

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

try:
    from ai.interaction import _get_instruction_text, generate_text_response
    _HANDLER_INITIATED_SWITCH_FLAG = "handler_initiated_scenario_switch" 
except ImportError:
    logging.getLogger(__name__).error("Failed to import from ai.interaction for registration_logic")
    async def generate_text_response(*args, **kwargs) -> Optional[str]: 
        logger_mock = logging.getLogger(__name__) 
        logger_mock.error("Using MOCK generate_text_response due to import error.")
        if kwargs.get("instruction_key") == "classify_master_services_prompt":
            user_input = kwargs.get("user_reply_for_format", "")
            if "маникюр" in user_input and "брови" in user_input:
                return json.dumps({"matched_services": [{"name_key": "beauty_services.nail_service.manicure", "user_provided_text": "маникюр"}, {"name_key": "beauty_services.eyebrows", "user_provided_text": "брови"}], "unmatched_phrases": [], "needs_clarification": False})
            elif "брови" in user_input and "ресницы" in user_input:
                 return json.dumps({"matched_services": [{"name_key": "beauty_services.eyebrows", "user_provided_text": "брови"}, {"name_key": "beauty_services.eyelashes", "user_provided_text": "ресницы"}], "unmatched_phrases": [], "needs_clarification": False})
            return json.dumps({"matched_services": [], "unmatched_phrases": [user_input], "needs_clarification": True})
        return "Mocked AI Response"
    async def _get_instruction_text(*args, **kwargs) -> Optional[str]: 
        return "Mocked instruction text"

try:
    from BehaviorEngine.state_manager import reset_user_state, update_user_state
    from database.models import Services, UserData, UserStates 
    if '_HANDLER_INITIATED_SWITCH_FLAG' not in globals(): 
        _HANDLER_INITIATED_SWITCH_FLAG = "handler_initiated_scenario_switch"
except ImportError:
    if '_HANDLER_INITIATED_SWITCH_FLAG' not in globals():
        _HANDLER_INITIATED_SWITCH_FLAG = "handler_initiated_scenario_switch"
    logging.getLogger(__name__).error("Failed to import DB models or state_manager for registration_logic")
    class Services: pass
    class UserData: pass
    class UserStates: pass
    async def update_user_state(*args, **kwargs): pass
    async def reset_user_state(*args, **kwargs): pass


CALLBACK_CONFIRM_CITY_PREFIX = "confirm_city_reg:"
# === END BLOCK 1 ===

# === BLOCK 2: Вспомогательная функция для получения дочерних услуг (ОПТИМИЗИРОВАННАЯ с логированием времени) ===
async def get_service_children(
    session: AsyncSession, parent_service_id: Optional[int], lang_code: str
) -> List[Dict[str, Any]]:
    func_start_time = time.monotonic()
    logger_func = logging.getLogger(__name__) 
    children_services = []
    if not parent_service_id:
        logger_func.warning("RegLogic: get_service_children: parent_service_id не предоставлен.")
        logger_func.debug(f"RegLogic: get_service_children (no parent_id) took {time.monotonic() - func_start_time:.4f}s")
        return children_services
    
    try:
        db_call_children_start_time = time.monotonic()
        # 1. Получаем всех прямых выбираемых детей
        stmt_children = (
            select(Services)
            .where(
                Services.parent_id == parent_service_id,
                Services.is_selectable_by_master.is_(True)
            )
            .order_by(Services.service_id)
        )
        children_result = await session.execute(stmt_children)
        db_children_services = children_result.scalars().all()
        logger_func.debug(f"RegLogic: get_service_children - DB select children took {time.monotonic() - db_call_children_start_time:.4f}s. Found {len(db_children_services)} children.")
        
        parents_with_grand_children_ids = set()
        if db_children_services:
            child_ids = [child.service_id for child in db_children_services]
            
            db_call_grandchildren_start_time = time.monotonic()
            # 2. Одним запросом проверяем, у каких из этих детей есть выбираемые внуки
            stmt_grand_children_parents = (
                select(Services.parent_id.distinct()) 
                .where(
                    Services.parent_id.in_(child_ids), 
                    Services.is_selectable_by_master.is_(True) 
                )
            )
            grand_children_parents_result = await session.execute(stmt_grand_children_parents)
            parents_with_grand_children_ids = set(grand_children_parents_result.scalars().all())
            logger_func.debug(f"RegLogic: get_service_children - DB select grandchildren existence took {time.monotonic() - db_call_grandchildren_start_time:.4f}s. Parents with grandchildren: {len(parents_with_grand_children_ids)}")

            for child_service in db_children_services:
                display_name = (
                    getattr(child_service, f"name_{lang_code.lower()}", None)
                    or getattr(child_service, "name_en", None)
                    or child_service.name_key
                )
                has_grand_children_flag = child_service.service_id in parents_with_grand_children_ids
                
                children_services.append(
                    {
                        "service_id": child_service.service_id,
                        "name_key": child_service.name_key,
                        "display_name": display_name,
                        "has_children": has_grand_children_flag,
                        "is_selectable_by_master": child_service.is_selectable_by_master
                    }
                )
    except Exception as e:
        logger_func.error(
            f"RegLogic: Error fetching children for parent_id {parent_service_id}: {e}",
            exc_info=True,
        )
    logger_func.debug(f"RegLogic: get_service_children for parent {parent_service_id} total took {time.monotonic() - func_start_time:.4f}s. Found: {len(children_services)}")
    return children_services
# === END BLOCK 2 ===

# === BLOCK 3: Logger Definition ===
logger = logging.getLogger(__name__)
# === END BLOCK 3 ===

# === BLOCK 4: prepare_city_confirmation ===
async def prepare_city_confirmation( 
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    func_start_time = time.monotonic()
    user = update.effective_user
    if not user or not update.effective_chat:
        logger.warning("RegLogic: [prepare_city_confirmation] User or chat_id not found.")
        logger.debug(f"RegLogic: prepare_city_confirmation took {time.monotonic() - func_start_time:.4f}s (early exit)")
        return {"error": "User or chat_id not found, cannot proceed."}

    user_id_log = user.id
    chat_id = update.effective_chat.id
    logger.info(f"RegLogic: [prepare_city_confirmation] Called for user {user_id_log}. State_context: {state_context}")
    ai_response_text = state_context.get("city_ai_response")
    context_updates_to_return = {} 
    parsed_city_name: Optional[str] = None
    parsed_country_name: str = "N/A"
    parsed_region_name: str = "N/A"
    city_found_marker = "CITY_FOUND:"

    if (ai_response_text and isinstance(ai_response_text, str) and city_found_marker in ai_response_text):
        try:
            parts_str = ai_response_text.split(city_found_marker, 1)[1].strip()
            first_line_of_city_data = parts_str.split("\n")[0]
            parts = [p.strip() for p in first_line_of_city_data.split("|")]
            city_name_from_ai = parts[0]
            country_name_from_ai = parts[1] if len(parts) > 1 else "N/A"
            region_name_from_ai = parts[2] if len(parts) > 2 else "N/A"
            if not city_name_from_ai: raise ValueError("AI returned CITY_FOUND, but the city name is empty.")
            parsed_city_name = city_name_from_ai
            parsed_country_name = country_name_from_ai
            parsed_region_name = region_name_from_ai
            logger.info(f"RegLogic: User {user_id_log}: AI response parsed. City: '{parsed_city_name}', Country: '{parsed_country_name}', Region: '{parsed_region_name}'.")
        except Exception as parse_error:
            logger.error(f"RegLogic: User {user_id_log}: Error parsing '{city_found_marker}' AI response '{ai_response_text}': {parse_error}")
            parsed_city_name = None
            try:
                send_error_msg_start_time = time.monotonic()
                await context.bot.send_message(chat_id=chat_id, text="Вибачте, не вдалося точно розпізнати місто. Спробуйте, будь ласка, ввести його ще раз.")
                logger.debug(f"RegLogic: send_message (city parsing error) took {time.monotonic() - send_error_msg_start_time:.4f}s")
            except Exception as e_msg: logger.error(f"RegLogic: Failed to send city parsing error message to user {user_id_log}: {e_msg}")
            
            context_updates_to_return["city_ai_response"] = None 
            context_updates_to_return["last_ai_clarification"] = "Ошибка парсинга ответа AI по городу"
            context_updates_to_return["error_message"] = "AI response (CITY_FOUND) parsing failed"
            logger.debug(f"RegLogic: prepare_city_confirmation took {time.monotonic() - func_start_time:.4f}s (parse error path)")
            return context_updates_to_return

    if parsed_city_name:
        confirmation_text = (f"Здається, ви вказали місто: **{parsed_city_name}**{f' ({parsed_country_name})' if parsed_country_name and parsed_country_name != 'N/A' else ''}.\nЦе вірно?")
        safe_city_name_for_callback = parsed_city_name.replace(":", "_").replace("|", "_").replace(" ", "+")
        keyboard = [[InlineKeyboardButton(f"✅ Так, це {parsed_city_name}", callback_data=f"{CALLBACK_CONFIRM_CITY_PREFIX}{safe_city_name_for_callback}"), InlineKeyboardButton("🔄 Інше місто", callback_data="change_city_reg")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            send_confirm_msg_start_time = time.monotonic()
            await context.bot.send_message(chat_id=chat_id,text=confirmation_text,reply_markup=reply_markup,parse_mode="Markdown")
            logger.debug(f"RegLogic: send_message (city confirmation) took {time.monotonic() - send_confirm_msg_start_time:.4f}s")
            logger.info(f"RegLogic: User {user_id_log}: Sent city confirmation for '{parsed_city_name}'.")
            context_updates_to_return["proposed_city_for_confirmation"] = parsed_city_name
            context_updates_to_return["proposed_country"] = parsed_country_name
            context_updates_to_return["proposed_region"] = parsed_region_name
            context_updates_to_return["message_with_buttons_sent"] = True
        except Exception as e:
            logger.error(f"RegLogic: User {user_id_log}: Failed to send city confirmation message with keyboard: {e}")
            with suppress(Exception): await context.bot.send_message(chat_id=chat_id, text="Вибачте, сталася помилка. Спробуйте ввести місто ще раз.")
            context_updates_to_return["city_ai_response"] = None
            context_updates_to_return["error_message"] = "Failed to send city confirmation message."
    else: 
        clarification_message = (ai_response_text if (ai_response_text and isinstance(ai_response_text, str) and len(ai_response_text) < 200) else "Будь ласка, уточніть назву міста або введіть її ще раз.")
        if not ai_response_text or not isinstance(ai_response_text, str): logger.warning(f"RegLogic: User {user_id_log}: No valid 'city_ai_response' in state_context for clarification. Using default message.")
        else: logger.info(f"RegLogic: User {user_id_log}: AI did not return 'CITY_FOUND:'. AI response used as clarification: '{ai_response_text}'")
        try:
            send_clarify_msg_start_time = time.monotonic()
            await context.bot.send_message(chat_id=chat_id, text=clarification_message)
            logger.debug(f"RegLogic: send_message (AI city clarification) took {time.monotonic() - send_clarify_msg_start_time:.4f}s")
        except Exception as e: logger.error(f"RegLogic: Failed to send AI's clarification/response to user {user_id_log}: {e}")
        
        context_updates_to_return["city_ai_response"] = None
        context_updates_to_return["last_ai_clarification"] = ai_response_text if ai_response_text else "N/A"
        context_updates_to_return["ai_clarification_sent"] = True
    logger.debug(f"RegLogic: prepare_city_confirmation total took {time.monotonic() - func_start_time:.4f}s")
    return context_updates_to_return
# === END BLOCK 4 ===

# === BLOCK 5: handle_city_confirmation_callback ===
async def handle_city_confirmation_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]: 
    func_start_time = time.monotonic()
    query = update.callback_query
    if not query or not query.data:
        logger.warning("RegLogic: [handle_city_confirmation_callback] No callback query or data.")
        logger.debug(f"RegLogic: handle_city_confirmation_callback took {time.monotonic() - func_start_time:.4f}s (no query data)")
        return None 
    
    try:
        answer_start_time = time.monotonic()
        await query.answer()
        logger.debug(f"RegLogic: query.answer() in handle_city_confirmation_callback took {time.monotonic() - answer_start_time:.4f}s")
    except Exception as e_ans: 
        logger.warning(f"RegLogic: Could not answer callback in handle_city_confirmation_callback: {e_ans}")

    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    callback_data = query.data
    logger.info(f"RegLogic: [handle_city_confirmation_callback] User {user_id_log} pressed callback: '{callback_data}'")
    context_updates_to_return = {}
    if callback_data.startswith(CALLBACK_CONFIRM_CITY_PREFIX):
        confirmed_city = callback_data[len(CALLBACK_CONFIRM_CITY_PREFIX):].replace("+", " ")
        logger.info(f"RegLogic: User {user_id_log}: Confirmed city '{confirmed_city}'.")
        try:
            if query.message: 
                edit_msg_start_time = time.monotonic()
                await query.edit_message_text(text=f"Місто **{confirmed_city}** підтверджено. Чудово!", parse_mode="Markdown")
                logger.debug(f"RegLogic: query.edit_message_text (city confirmed) took {time.monotonic() - edit_msg_start_time:.4f}s")
        except Exception as e: logger.error(f"RegLogic: Error editing message after city confirmation for user {user_id_log}: {e}")
        
        context_updates_to_return["master_reg_confirmed_city"] = confirmed_city
        context_updates_to_return["master_reg_confirmed_country"] = state_context.get("proposed_country")
        context_updates_to_return["master_reg_confirmed_region"] = state_context.get("proposed_region")
        context_updates_to_return["city_confirmation_status"] = "confirmed"
        context_updates_to_return["next_state_for_yaml"] = "REG_MASTER_ASK_SERVICES_INITIAL"
        
    elif callback_data == "change_city_reg":
        logger.info(f"RegLogic: User {user_id_log}: Chose to change city.")
        try:
            if query.message:
                edit_msg_start_time = time.monotonic()
                await query.edit_message_text(text="Добре, давайте спробуємо ввести місто ще раз.")
                logger.debug(f"RegLogic: query.edit_message_text (change city) took {time.monotonic() - edit_msg_start_time:.4f}s")
        except Exception as e: logger.error(f"RegLogic: Error editing message for city change request by user {user_id_log}: {e}")
        
        context_updates_to_return["city_ai_response"] = None 
        context_updates_to_return["proposed_city_for_confirmation"] = None
        context_updates_to_return["proposed_country"] = None
        context_updates_to_return["proposed_region"] = None
        context_updates_to_return["city_confirmation_status"] = "change_requested"
        context_updates_to_return["next_state_for_yaml"] = "REG_MASTER_ASK_CITY"

    else:
        logger.warning(f"RegLogic: User {user_id_log}: Received unknown callback_data in city confirmation: '{callback_data}'")
        logger.debug(f"RegLogic: handle_city_confirmation_callback took {time.monotonic() - func_start_time:.4f}s (unknown callback)")
        return None 
    
    logger.debug(f"RegLogic: handle_city_confirmation_callback for '{callback_data}' total took {time.monotonic() - func_start_time:.4f}s")
    return context_updates_to_return
# === END BLOCK 5 ===

# === BLOCK 6: reset_user_state_handler ===
async def reset_user_state_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any], 
) -> Optional[Dict[str, Any]]: 
    func_start_time = time.monotonic()
    user = update.effective_user
    if not user:
        logger.warning("RegLogic: [reset_user_state_handler] User not found.")
        logger.debug(f"RegLogic: reset_user_state_handler took {time.monotonic() - func_start_time:.4f}s (no user)")
        return {"error": "User not found, cannot reset state."}
    user_id = user.id
    logger.info(f"RegLogic: [reset_user_state_handler] Attempting to reset state for user {user_id}.")
    context_updates_to_return = {}
    try:
        reset_call_start_time = time.monotonic()
        reset_success = await reset_user_state(user_id, session) 
        logger.debug(f"RegLogic: reset_user_state call took {time.monotonic() - reset_call_start_time:.4f}s") # reset_user_state is logged by StateMgr
        if reset_success:
            logger.info(f"RegLogic: User {user_id} state has been reset successfully via handler.")
            context_updates_to_return["state_reset_status"] = "success"
        else:
            logger.warning(f"RegLogic: Failed to reset state for user {user_id} via handler (reset_user_state returned False or no state found).")
            context_updates_to_return["state_reset_status"] = "no_state_to_reset_or_failed"
    except Exception as e:
        logger.error(f"RegLogic: Error in reset_user_state_handler for user {user_id}: {e}", exc_info=True)
        context_updates_to_return["state_reset_status"] = "error"
        context_updates_to_return["error_message"] = str(e)
    logger.debug(f"RegLogic: reset_user_state_handler total took {time.monotonic() - func_start_time:.4f}s")
    return context_updates_to_return
# === END BLOCK 6 ===

# === BLOCK 7: analyze_and_match_services_initial ===
async def analyze_and_match_services_initial(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    func_start_time = time.monotonic()
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        logger.warning("RegLogic: [analyze_and_match_services_initial] User or message text not found.")
        logger.debug(f"RegLogic: analyze_and_match_services_initial took {time.monotonic() - func_start_time:.4f}s (no user/text)")
        return {"next_step_recommendation": "REG_MASTER_ASK_SERVICES_AGAIN", "error_message": "No message text from user"}
    
    user_id_log = user.id
    master_services_text_input = update.message.text
    logger.info(f"RegLogic: [analyze_and_match_services_initial] User {user_id_log} entered services: '{master_services_text_input}'")
    instruction_key_to_test = "classify_master_services_prompt"
    
    db_user_get_start_time = time.monotonic()
    db_user = await session.get(UserData, user.id)
    logger.debug(f"RegLogic: session.get(UserData) in analyze_services took {time.monotonic() - db_user_get_start_time:.4f}s")
    
    user_lang_code_for_display = "ru"
    if db_user and db_user.language_code:
        if db_user.language_code.startswith("uk"): user_lang_code_for_display = "uk"
        elif db_user.language_code.startswith("en"): user_lang_code_for_display = "en"
    logger.debug(f"RegLogic: User {user_id_log} language for service display: {user_lang_code_for_display}")
    
    ai_response_json_str: Optional[str] = None
    ai_call_start_time = time.monotonic()
    try:
        logger.info(f"RegLogic: Calling AI with instruction_key='{instruction_key_to_test}' and user_reply_for_format='{master_services_text_input}' for lang='ru'")
        ai_response_json_str = await generate_text_response(messages=[], instruction_key=instruction_key_to_test, user_reply_for_format=master_services_text_input, session=session, user_lang_code="ru")
        logger.info(f"RegLogic: Raw AI response string for services (user {user_id_log}): \n---\n{ai_response_json_str}\n---")
    except Exception as e:
        logger.error(f"RegLogic: Error calling AI for service classification (user {user_id_log}): {e}", exc_info=True)
        analysis_result = {"services_text_input": master_services_text_input, "ai_raw_response": None, "ai_parsed_data": None, "matched_services_info": [], "unmatched_phrases": [master_services_text_input], "needs_clarification": True, "next_step_recommendation": "REG_MASTER_ASK_SERVICES_AGAIN", "error_message": f"AI call failed: {str(e)}"}
        logger.debug(f"RegLogic: analyze_and_match_services_initial (AI error) took {time.monotonic() - func_start_time:.4f}s. AI call part took {time.monotonic() - ai_call_start_time:.4f}s")
        return analysis_result
    
    logger.debug(f"RegLogic: generate_text_response in analyze_services took {time.monotonic() - ai_call_start_time:.4f}s")

    if not ai_response_json_str:
        logger.warning(f"RegLogic: AI returned no response string for service classification (user {user_id_log}).")
        analysis_result = {"services_text_input": master_services_text_input, "ai_raw_response": None, "ai_parsed_data": None, "matched_services_info": [], "unmatched_phrases": [master_services_text_input], "needs_clarification": True, "next_step_recommendation": "REG_MASTER_ASK_SERVICES_AGAIN", "error_message": "AI did not respond"}
        logger.debug(f"RegLogic: analyze_and_match_services_initial (no AI response) took {time.monotonic() - func_start_time:.4f}s")
        return analysis_result
        
    ai_parsed_data: Optional[Dict[str, Any]] = None
    processed_ai_response_str_for_json = ai_response_json_str 
    try:
        temp_str = ai_response_json_str.strip()
        json_prefix = "Ответ JSON:"
        if temp_str.startswith(json_prefix): temp_str = temp_str[len(json_prefix):].lstrip()
        if temp_str.startswith("```json"): temp_str = temp_str[len("```json"):].strip()
        if temp_str.endswith("```"): temp_str = temp_str[:-len("```")].strip()
        processed_ai_response_str_for_json = temp_str
        logger.debug(f"RegLogic: Attempting to parse JSON from AI after pre-processing: '{processed_ai_response_str_for_json}'")
        ai_parsed_data = json.loads(processed_ai_response_str_for_json)
        if (not isinstance(ai_parsed_data, dict) or 
            not isinstance(ai_parsed_data.get("matched_services"), list) or 
            not isinstance(ai_parsed_data.get("unmatched_phrases"), list) or 
            not isinstance(ai_parsed_data.get("needs_clarification"), bool)):
            raise ValueError("AI response JSON structure is invalid after parsing.")
        for item in ai_parsed_data.get("matched_services", []):
            if not (isinstance(item, dict) and "name_key" in item and "user_provided_text" in item):
                raise ValueError("Invalid item structure in 'matched_services'.")
        logger.info(f"RegLogic: AI response for services (user {user_id_log}) successfully parsed: {ai_parsed_data}")
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"RegLogic: Error parsing AI JSON response for services (user {user_id_log}). Original: '{ai_response_json_str}'. Processed for json.loads: '{processed_ai_response_str_for_json}'. Error: {e}")
        analysis_result = {"services_text_input": master_services_text_input, "ai_raw_response": ai_response_json_str, "ai_parsed_data": None, "matched_services_info": [], "unmatched_phrases": [master_services_text_input], "needs_clarification": True, "next_step_recommendation": "REG_MASTER_ASK_SERVICES_AGAIN", "error_message": f"Invalid JSON from AI: {str(e)}"}
        logger.debug(f"RegLogic: analyze_and_match_services_initial (JSON parse error) took {time.monotonic() - func_start_time:.4f}s")
        return analysis_result

    enriched_matched_services = []
    enrich_start_time = time.monotonic()
    if ai_parsed_data:
        matched_services_from_ai = ai_parsed_data.get("matched_services", [])
        for ai_service in matched_services_from_ai:
            if isinstance(ai_service, dict) and "name_key" in ai_service:
                name_key = ai_service["name_key"]
                user_provided_text = ai_service.get("user_provided_text", "")
                service_id_db: Optional[int] = None; display_name_db: str = f"Услуга ({name_key})"; parent_id_db: Optional[int] = None; has_children_db: bool = False; is_selectable_by_master_db: bool = False
                try:
                    stmt_service = select(Services).where(Services.name_key == name_key)
                    result_service = await session.execute(stmt_service)
                    db_service_obj = result_service.scalar_one_or_none()
                    if db_service_obj:
                        service_id_db = db_service_obj.service_id
                        display_name_db = (getattr(db_service_obj, f"name_{user_lang_code_for_display.lower()}", None) or db_service_obj.name_en or name_key)
                        parent_id_db = db_service_obj.parent_id
                        is_selectable_by_master_db = (db_service_obj.is_selectable_by_master)
                        stmt_children = (select(Services.service_id).where(Services.parent_id == service_id_db, Services.is_selectable_by_master.is_(True)).limit(1))
                        result_children = await session.execute(stmt_children)
                        if result_children.scalar_one_or_none() is not None: has_children_db = True
                        logger.info(f"RegLogic: Enriched service '{name_key}': ID={service_id_db}, Name='{display_name_db}', HasChildren={has_children_db}, SelectableByMaster={is_selectable_by_master_db}, ParentID={parent_id_db}")
                    else: logger.warning(f"RegLogic: Service with name_key '{name_key}' not found in DB for enrichment.")
                except Exception as db_exc: logger.error(f"RegLogic: DB error enriching service '{name_key}': {db_exc}", exc_info=True)
                enriched_matched_services.append({"name_key": name_key, "service_id": service_id_db, "display_name": display_name_db, "has_children": has_children_db, "parent_id": parent_id_db, "user_provided_text": user_provided_text, "is_selectable_by_master": is_selectable_by_master_db})
    logger.debug(f"RegLogic: Service enrichment loop took {time.monotonic() - enrich_start_time:.4f}s")

    next_step = "REG_MASTER_ASK_SERVICES_AGAIN" 
    if ai_parsed_data:
        if not ai_parsed_data.get("needs_clarification", True) and enriched_matched_services: next_step = "REG_MASTER_SHOW_SERVICE_SUGGESTIONS"
        elif enriched_matched_services and ai_parsed_data.get("needs_clarification", True): next_step = "REG_MASTER_ASK_SERVICES_AGAIN" 
        elif not enriched_matched_services: next_step = "REG_MASTER_ASK_SERVICES_AGAIN"
    
    analysis_result = {
        "services_text_input": master_services_text_input, 
        "ai_raw_response": ai_response_json_str, 
        "ai_parsed_data": ai_parsed_data, 
        "matched_services_info": enriched_matched_services, 
        "unmatched_phrases": ai_parsed_data.get("unmatched_phrases", []) if ai_parsed_data else [master_services_text_input], 
        "needs_clarification": ai_parsed_data.get("needs_clarification", True) if ai_parsed_data else True, 
        "next_step_recommendation": next_step
    }
    logger.debug(f"RegLogic: analyze_and_match_services_initial total took {time.monotonic() - func_start_time:.4f}s")
    return analysis_result
# === END BLOCK 7 ===

# === BLOCK 8: prepare_service_suggestions_message (С ЛОГИРОВАНИЕМ ВРЕМЕНИ) ===
async def prepare_service_suggestions_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any], 
) -> Optional[Dict[str, Any]]: 
    func_start_time = time.monotonic()
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    chat_id = update.effective_chat.id if update.effective_chat else None
    query = update.callback_query

    logger.info(f"RegLogic: [prepare_service_suggestions_message] Called for user {user_id_log}.")
    # logger.debug(f"RegLogic: User {user_id_log}: Incoming state_context: {state_context}") # Очень многословно

    context_updates_to_return = {}

    current_category_id_detailed = state_context.get("current_category_being_detailed_id")
    service_processing_queue = state_context.get("service_processing_queue") 
    master_selected_services = state_context.get("master_selected_services", []).copy() 
    current_category_selections = state_context.get("current_category_selections", {}).copy()
    processed_for_auto_detail = state_context.get("processed_for_auto_detail", []).copy()
    service_suggestion_message_id = state_context.get("service_suggestion_message_id")

    init_logic_start_time = time.monotonic()
    if "service_analysis_result" in state_context and service_processing_queue is None:
        logger.info(f"RegLogic: User {user_id_log}: 'service_processing_queue' is None/not set. Performing FULL initialization.")
        service_analysis_result = state_context.get("service_analysis_result", {})
        initial_matched_services = service_analysis_result.get("matched_services_info", [])
        
        service_processing_queue = [s for s in initial_matched_services if s.get("service_id")]
        master_selected_services = [] 
        current_category_selections = {} 
        current_category_id_detailed = None 
        processed_for_auto_detail = [] 
        
        context_updates_to_return["service_processing_queue"] = service_processing_queue
        context_updates_to_return["master_selected_services"] = master_selected_services
        context_updates_to_return["current_category_selections"] = current_category_selections
        context_updates_to_return["current_category_being_detailed_id"] = current_category_id_detailed
        context_updates_to_return["processed_for_auto_detail"] = processed_for_auto_detail
        logger.info(f"RegLogic: User {user_id_log}: FULL initialization done. Queue: {len(service_processing_queue)} services.")
    elif service_processing_queue is not None:
        logger.info(f"RegLogic: User {user_id_log}: Skipping full initialization. Using existing service context. Queue: {len(service_processing_queue)}, CatDetailedID: {current_category_id_detailed}")
    else: 
        logger.warning(f"RegLogic: User {user_id_log}: service_processing_queue is None and service_analysis_result not in context. Assuming empty queue.")
        service_processing_queue = [] 
        context_updates_to_return["service_processing_queue"] = service_processing_queue
    logger.debug(f"RegLogic: Initialization logic in prepare_suggestions took {time.monotonic() - init_logic_start_time:.4f}s")

    auto_detail_start_time = time.monotonic()
    if not current_category_id_detailed and service_processing_queue: 
        first_service_in_queue = service_processing_queue[0]
        first_service_id = first_service_in_queue.get("service_id")

        if (first_service_id and 
            first_service_id not in processed_for_auto_detail and 
            first_service_in_queue.get("has_children") and 
            not first_service_in_queue.get("is_selectable_by_master")):
            
            current_category_id_detailed = first_service_id 
            context_updates_to_return["current_category_being_detailed_id"] = current_category_id_detailed
            
            if str(current_category_id_detailed) not in current_category_selections:
                current_category_selections[str(current_category_id_detailed)] = []
            context_updates_to_return["current_category_selections"] = current_category_selections 
            
            if first_service_id not in processed_for_auto_detail:
                processed_for_auto_detail.append(first_service_id)
            context_updates_to_return["processed_for_auto_detail"] = processed_for_auto_detail
            
            logger.info(f"RegLogic: User {user_id_log}: Auto-detailing first category from queue: '{first_service_in_queue.get('display_name')}' (ID: {current_category_id_detailed}).")
    logger.debug(f"RegLogic: Auto-detailing logic in prepare_suggestions took {time.monotonic() - auto_detail_start_time:.4f}s")
        
    get_user_db_start_time = time.monotonic()
    db_user = await session.get(UserData, user.id)
    logger.debug(f"RegLogic: session.get(UserData) in prepare_suggestions took {time.monotonic() - get_user_db_start_time:.4f}s")
    user_lang_code_for_display = "ru" 
    if db_user and db_user.language_code:
        if db_user.language_code.startswith("uk"): user_lang_code_for_display = "uk"
        elif db_user.language_code.startswith("en"): user_lang_code_for_display = "en"

    message_text = ""
    keyboard_buttons = []
    
    if query: 
        try:
            q_answer_start_time = time.monotonic()
            await query.answer()
            logger.debug(f"RegLogic: query.answer() in prepare_service_suggestions_message took {time.monotonic() - q_answer_start_time:.4f}s")
        except Exception as e_ans:
            logger.warning(f"RegLogic: prepare_service_suggestions_message: Could not answer query: {e_ans}")

    # --- Логика отображения текущей детализируемой категории ---
    build_kbd_start_time = time.monotonic()
    if current_category_id_detailed:
        get_parent_start_time = time.monotonic()
        parent_service_obj = await session.get(Services, current_category_id_detailed)
        logger.debug(f"RegLogic: session.get(Services) for parent took {time.monotonic() - get_parent_start_time:.4f}s")

        if not parent_service_obj:
            logger.error(f"RegLogic: User {user_id_log}: Parent service ID {current_category_id_detailed} for detailing not found. Clearing detail state.")
            context_updates_to_return["current_category_being_detailed_id"] = None
            logger.debug(f"RegLogic: prepare_service_suggestions_message total took {time.monotonic() - func_start_time:.4f}s (parent not found)")
            return context_updates_to_return

        parent_display_name = (getattr(parent_service_obj, f"name_{user_lang_code_for_display.lower()}", None) or getattr(parent_service_obj, "name_en", None) or parent_service_obj.name_key)
        
        get_children_start_time = time.monotonic()
        children_services = await get_service_children(session, current_category_id_detailed, user_lang_code_for_display) # Уже логирует время внутри
        logger.debug(f"RegLogic: Call to get_service_children in prepare_suggestions took {time.monotonic() - get_children_start_time:.4f}s")

        if not children_services:
            logger.info(f"RegLogic: User {user_id_log}: Category '{parent_display_name}' (ID: {current_category_id_detailed}) has no selectable children.")
            if (parent_service_obj.is_selectable_by_master and parent_service_obj.service_id not in master_selected_services):
                master_selected_services.append(parent_service_obj.service_id)
            context_updates_to_return["master_selected_services"] = master_selected_services
            context_updates_to_return["current_category_being_detailed_id"] = None
            current_category_id_detailed = None 
            current_category_selections.pop(str(parent_service_obj.service_id), None)
            context_updates_to_return["current_category_selections"] = current_category_selections
            if (service_processing_queue and service_processing_queue[0].get("service_id") == parent_service_obj.service_id):
                service_processing_queue.pop(0)
            context_updates_to_return["service_processing_queue"] = service_processing_queue
        else:
            message_text = f"Категория: **{parent_display_name}**.\nВыберите уточняющие услуги (можно несколько, повторное нажатие меняет выбор):"
            selections_for_this_cat = current_category_selections.get(str(current_category_id_detailed), [])
            logger.debug(f"RegLogic: User {user_id_log}: Rendering sub-services for {parent_display_name} (ID {current_category_id_detailed}). Current selections for it: {selections_for_this_cat}")
            for child in children_services:
                is_selected = child["service_id"] in selections_for_this_cat
                button_text = f"{'✅ ' if is_selected else '☑️ '} {child['display_name']}"
                keyboard_buttons.append([InlineKeyboardButton(button_text, callback_data=f"reg_toggle_sub_service:{child['service_id']}:{current_category_id_detailed}")])
            keyboard_buttons.append([InlineKeyboardButton(f"👍 Готово с '{parent_display_name}'", callback_data=f"reg_category_done:{current_category_id_detailed}")])

    # --- Логика отображения услуг из основной очереди ---
    elif service_processing_queue:
        current_service_to_process = service_processing_queue[0]
        service_id = current_service_to_process.get("service_id")
        display_name = current_service_to_process.get("display_name")
        has_children = current_service_to_process.get("has_children", False)
        is_selectable = current_service_to_process.get("is_selectable_by_master", False)
        if has_children:
            message_text = f"Распознана категория услуг: **{display_name}**. Желаете уточнить услуги в этой категории?"
            keyboard_buttons.append([InlineKeyboardButton(f"🔍 Да, уточнить '{display_name}'", callback_data=f"reg_detail_category:{service_id}")])
            if is_selectable and service_id not in master_selected_services:
                keyboard_buttons.append([InlineKeyboardButton(f"➕ Добавить '{display_name}' (всю категорию)", callback_data=f"reg_add_direct_service:{service_id}")])
            keyboard_buttons.append([InlineKeyboardButton(f"➡️ Пропустить '{display_name}'", callback_data=f"reg_skip_top_service:{service_id}")])
        elif is_selectable:
            message_text = f"Мы распознали у вас услугу: **{display_name}**. Добавить ее в ваш список?"
            keyboard_buttons.append([InlineKeyboardButton(f"✅ Да, добавить '{display_name}'", callback_data=f"reg_add_direct_service:{service_id}")])
            keyboard_buttons.append([InlineKeyboardButton("➡️ Нет, пропустить", callback_data=f"reg_skip_top_service:{service_id}")])
        else:
            logger.warning(f"RegLogic: User {user_id_log}: Service '{display_name}' (ID: {service_id}) is not selectable and has no children. Auto-skipping.")
            if service_processing_queue: service_processing_queue.pop(0) 
            context_updates_to_return["service_processing_queue"] = service_processing_queue

    # --- Логика завершения выбора услуг ---
    else: 
        logger.info(f"RegLogic: User {user_id_log}: Service processing queue IS EMPTY and no category is being detailed. Finalizing service selection.")
        final_message = "Выбор услуг завершен."
        if master_selected_services:
            selected_names = []
            processed_ids_for_names = set()
            for service_id_selected in master_selected_services:
                if service_id_selected in processed_ids_for_names: continue
                service_obj_final_start_time = time.monotonic()
                service_obj = await session.get(Services, service_id_selected)
                logger.debug(f"RegLogic: session.get(Services) for final list item took {time.monotonic() - service_obj_final_start_time:.4f}s")
                if service_obj:
                    display_name_sel = (getattr(service_obj, f"name_{user_lang_code_for_display.lower()}", None) or getattr(service_obj, "name_en", None) or service_obj.name_key)
                    selected_names.append(f"- {display_name_sel}")
                    processed_ids_for_names.add(service_id_selected)
            if selected_names: final_message += " Вы выбрали:\n" + "\n".join(selected_names)
            else: final_message += " Вы пока не выбрали ни одной конкретной услуги."
        else: final_message += " Вы пока не выбрали ни одной конкретной услуги. Вы сможете добавить их позже."

        if chat_id:
            last_msg_id = service_suggestion_message_id 
            if last_msg_id:
                try: 
                    edit_markup_start_time = time.monotonic()
                    await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=last_msg_id, reply_markup=None)
                    logger.debug(f"RegLogic: edit_message_reply_markup (final) took {time.monotonic() - edit_markup_start_time:.4f}s")
                except Exception as e_final_edit: logger.warning(f"RegLogic: Could not remove keyboard from final message {last_msg_id}: {e_final_edit}")
            
            send_final_msg_start_time = time.monotonic()
            await context.bot.send_message(chat_id=chat_id, text=final_message)
            logger.debug(f"RegLogic: send_message (final summary) took {time.monotonic() - send_final_msg_start_time:.4f}s")

        context_updates_to_return["service_processing_queue"] = None 
        context_updates_to_return["current_category_selections"] = {}
        context_updates_to_return["current_category_being_detailed_id"] = None
        context_updates_to_return["service_suggestion_message_id"] = None
        context_updates_to_return["processed_for_auto_detail"] = []
        context_updates_to_return["service_analysis_result"] = None 
        context_updates_to_return["master_selected_services"] = master_selected_services 
        
        logger.info(f"RegLogic: User {user_id_log}: All services processed. Setting state to REG_MASTER_ALL_SERVICES_CONFIRMED.")
        context_updates_to_return["_trigger_state_transition_to"] = "REG_MASTER_ALL_SERVICES_CONFIRMED"
        logger.debug(f"RegLogic: prepare_service_suggestions_message total took {time.monotonic() - func_start_time:.4f}s (finalization path)")
        return context_updates_to_return
    
    logger.debug(f"RegLogic: Keyboard building logic took {time.monotonic() - build_kbd_start_time:.4f}s")

    # --- Отправка/редактирование сообщения с кнопками ---
    reply_markup = InlineKeyboardMarkup(keyboard_buttons) if keyboard_buttons else None
    message_to_send = message_text if message_text else "Пожалуйста, выберите действие."
    message_id_to_edit = service_suggestion_message_id 

    send_edit_logic_start_time = time.monotonic()
    if query and query.message and message_id_to_edit == query.message.message_id:
        try:
            edit_msg_start_time = time.monotonic()
            await query.edit_message_text(text=message_to_send, reply_markup=reply_markup, parse_mode="Markdown")
            logger.debug(f"RegLogic: query.edit_message_text took {time.monotonic() - edit_msg_start_time:.4f}s")
            logger.info(f"RegLogic: Edited message_id {message_id_to_edit} for user {user_id_log} via query.")
            context_updates_to_return["service_suggestion_message_id"] = message_id_to_edit 
        except telegram.error.BadRequest as e_bad_request: 
            if "message is not modified" in str(e_bad_request).lower():
                logger.debug(f"RegLogic: Message {message_id_to_edit} not modified. Callback already answered.")
            else:
                logger.warning(f"RegLogic: BadRequest editing message {message_id_to_edit} via query (user {user_id_log}): {e_bad_request}. Will try to send new.")
                message_id_to_edit = None 
        except Exception as e_edit:
            logger.warning(f"RegLogic: Could not edit message {message_id_to_edit} via query (user {user_id_log}): {e_edit}. Will try to send new.")
            message_id_to_edit = None 
    
    if not message_id_to_edit and chat_id and (reply_markup or message_text): 
        if service_suggestion_message_id: 
            try: 
                edit_markup_start_time = time.monotonic()
                await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=service_suggestion_message_id, reply_markup=None)
                logger.debug(f"RegLogic: edit_message_reply_markup (before new) took {time.monotonic() - edit_markup_start_time:.4f}s")
            except Exception: pass
        
        send_new_msg_start_time = time.monotonic()
        sent_message = await context.bot.send_message(chat_id=chat_id, text=message_to_send, reply_markup=reply_markup, parse_mode="Markdown")
        logger.debug(f"RegLogic: context.bot.send_message (new suggestions) took {time.monotonic() - send_new_msg_start_time:.4f}s")
        context_updates_to_return["service_suggestion_message_id"] = sent_message.message_id
        logger.info(f"RegLogic: Sent NEW service suggestions message (ID: {sent_message.message_id}) to user {user_id_log}.")
    elif chat_id and not reply_markup and message_id_to_edit : 
        try:
            edit_text_start_time = time.monotonic()
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id_to_edit, text=message_to_send, reply_markup=None, parse_mode="Markdown")
            logger.debug(f"RegLogic: edit_message_text (remove kbd) took {time.monotonic() - edit_text_start_time:.4f}s")
            context_updates_to_return["service_suggestion_message_id"] = message_id_to_edit 
            logger.info(f"RegLogic: Edited message {message_id_to_edit} to remove keyboard.")
        except Exception:
            logger.warning(f"RegLogic: Could not edit message {message_id_to_edit} to remove keyboard.")
            context_updates_to_return["service_suggestion_message_id"] = None 
    
    logger.debug(f"RegLogic: Send/edit message logic took {time.monotonic() - send_edit_logic_start_time:.4f}s")
    logger.debug(f"RegLogic: prepare_service_suggestions_message total took {time.monotonic() - func_start_time:.4f}s")
    return context_updates_to_return
# === END BLOCK 8 ===

# === BLOCK 9: handle_detail_category ===
async def handle_detail_category(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any], 
) -> Optional[Dict[str, Any]]: 
    func_start_time = time.monotonic()
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    query = update.callback_query
    context_updates_to_return = {}

    if not query or not query.data or not query.data.startswith("reg_detail_category:"):
        logger.warning(f"RegLogic: User {user_id_log}: handle_detail_category called with invalid data: {query.data if query else 'No query'}")
        if query: 
            with suppress(Exception): await query.answer("Ошибка: нет данных.", show_alert=True) # Answer once
        logger.debug(f"RegLogic: handle_detail_category took {time.monotonic() - func_start_time:.4f}s (invalid data)")
        return None 

    try:
        answer_start_time = time.monotonic()
        await query.answer() 
        logger.debug(f"RegLogic: query.answer() in handle_detail_category took {time.monotonic() - answer_start_time:.4f}s")
    except Exception as e_ans:
        logger.warning(f"RegLogic: handle_detail_category: Could not answer query: {e_ans}")
        
    try:
        parent_service_id_str = query.data.split(":")[1]
        parent_service_id = int(parent_service_id_str)
    except (IndexError, ValueError):
        logger.error(f"RegLogic: User {user_id_log}: Invalid parent_service_id in callback: {query.data}")
        logger.debug(f"RegLogic: handle_detail_category took {time.monotonic() - func_start_time:.4f}s (parse error)")
        return None 

    logger.info(f"RegLogic: User {user_id_log}: Chose to detail category ID {parent_service_id}.")
    context_updates_to_return["current_category_being_detailed_id"] = parent_service_id
    current_selections_copy = state_context.get("current_category_selections", {}).copy()
    if str(parent_service_id) not in current_selections_copy:
        current_selections_copy[str(parent_service_id)] = []
    context_updates_to_return["current_category_selections"] = current_selections_copy
    
    logger.debug(f"RegLogic: handle_detail_category for {parent_service_id} total took {time.monotonic() - func_start_time:.4f}s")
    return context_updates_to_return
# === END BLOCK 9 ===

# === BLOCK 10: handle_toggle_sub_service ===
async def handle_toggle_sub_service(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any], 
) -> Optional[Dict[str, Any]]: 
    func_start_time = time.monotonic()
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    query = update.callback_query

    if (not query or not query.data or not query.data.startswith("reg_toggle_sub_service:")):
        logger.warning(f"RegLogic: User {user_id_log}: handle_toggle_sub_service called with invalid data: {query.data if query else 'No query'}")
        if query: 
            with suppress(Exception): await query.answer("Ошибка обработки выбора.", show_alert=True)
        logger.debug(f"RegLogic: handle_toggle_sub_service took {time.monotonic() - func_start_time:.4f}s (invalid data)")
        return None

    try:
        answer_start_time = time.monotonic()
        await query.answer() 
        logger.debug(f"RegLogic: query.answer() in handle_toggle_sub_service took {time.monotonic() - answer_start_time:.4f}s")
    except Exception as e_ans:
        logger.warning(f"RegLogic: handle_toggle_sub_service: Could not answer query: {e_ans}")
        
    try:
        _, child_id_str, parent_id_str = query.data.split(":")
        child_id = int(child_id_str)
        parent_id = int(parent_id_str)
    except (IndexError, ValueError):
        logger.error(f"RegLogic: User {user_id_log}: Invalid IDs in callback data: {query.data}")
        logger.debug(f"RegLogic: handle_toggle_sub_service took {time.monotonic() - func_start_time:.4f}s (parse error)")
        return None

    logger.info(f"RegLogic: User {user_id_log}: Toggled sub-service ID {child_id} for parent ID {parent_id}.")
    current_category_selections_copy = state_context.get("current_category_selections", {}).copy()
    parent_id_key = str(parent_id)
    if parent_id_key not in current_category_selections_copy:
        current_category_selections_copy[parent_id_key] = []
    if child_id in current_category_selections_copy[parent_id_key]:
        current_category_selections_copy[parent_id_key].remove(child_id)
        logger.debug(f"RegLogic: User {user_id_log}: Sub-service {child_id} REMOVED from selections for category {parent_id_key}. Selections now: {current_category_selections_copy[parent_id_key]}")
    else:
        current_category_selections_copy[parent_id_key].append(child_id)
        logger.debug(f"RegLogic: User {user_id_log}: Sub-service {child_id} ADDED to selections for category {parent_id_key}. Selections now: {current_category_selections_copy[parent_id_key]}")
    
    logger.debug(f"RegLogic: handle_toggle_sub_service for {child_id}:{parent_id} total took {time.monotonic() - func_start_time:.4f}s")
    return {"current_category_selections": current_category_selections_copy}
# === END BLOCK 10 ===

# === BLOCK 11: handle_category_done ===
async def handle_category_done(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any], 
) -> Optional[Dict[str, Any]]: 
    func_start_time = time.monotonic()
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    query = update.callback_query
    context_updates_to_return = {}

    if not query or not query.data or not query.data.startswith("reg_category_done:"):
        logger.warning(f"RegLogic: User {user_id_log}: handle_category_done called with invalid data: {query.data if query else 'No query'}")
        if query: 
            with suppress(Exception): await query.answer("Ошибка обработки.", show_alert=True)
        logger.debug(f"RegLogic: handle_category_done took {time.monotonic() - func_start_time:.4f}s (invalid data)")
        return None 

    try:
        answer_start_time = time.monotonic()
        await query.answer("Выбор в категории сохранен.") 
        logger.debug(f"RegLogic: query.answer() in handle_category_done took {time.monotonic() - answer_start_time:.4f}s")
    except Exception as e_ans:
        logger.warning(f"RegLogic: handle_category_done: Could not answer query: {e_ans}")

    try:
        parent_id_done_str = query.data.split(":")[1]
        parent_id_done = int(parent_id_done_str)
    except (IndexError, ValueError):
        logger.error(f"RegLogic: User {user_id_log}: Invalid parent_id in callback for category_done: {query.data}")
        logger.debug(f"RegLogic: handle_category_done took {time.monotonic() - func_start_time:.4f}s (parse error)")
        return None

    logger.info(f"RegLogic: User {user_id_log}: Finished with category ID {parent_id_done}.")
    current_category_selections_from_context = state_context.get("current_category_selections", {}).copy()
    master_selected_services_copy = state_context.get("master_selected_services", []).copy()
    service_processing_queue_copy = state_context.get("service_processing_queue", []).copy()
    selections_for_this_done_category = current_category_selections_from_context.get(str(parent_id_done), [])

    for sub_service_id in selections_for_this_done_category:
        if sub_service_id not in master_selected_services_copy:
            master_selected_services_copy.append(sub_service_id)

    if not selections_for_this_done_category: 
        get_parent_obj_start_time = time.monotonic()
        parent_service_obj = await session.get(Services, parent_id_done)
        logger.debug(f"RegLogic: session.get(Services) in category_done took {time.monotonic() - get_parent_obj_start_time:.4f}s")
        if (parent_service_obj and parent_service_obj.is_selectable_by_master and parent_service_obj.service_id not in master_selected_services_copy):
            master_selected_services_copy.append(parent_service_obj.service_id)
            logger.info(f"RegLogic: User {user_id_log}: No sub-services selected for '{getattr(parent_service_obj, 'name_ru', parent_service_obj.name_key)}', adding parent category itself (ID: {parent_id_done}) as it's selectable.")

    context_updates_to_return["master_selected_services"] = master_selected_services_copy
    logger.info(f"RegLogic: User {user_id_log}: Current master_selected_services after category {parent_id_done}: {master_selected_services_copy}")
    context_updates_to_return["current_category_being_detailed_id"] = None 
    if str(parent_id_done) in current_category_selections_from_context:
        current_category_selections_from_context.pop(str(parent_id_done))
    context_updates_to_return["current_category_selections"] = current_category_selections_from_context
    
    if (service_processing_queue_copy and service_processing_queue_copy[0].get("service_id") == parent_id_done):
        processed_service = service_processing_queue_copy.pop(0)
        logger.debug(f"RegLogic: User {user_id_log}: Removed '{processed_service.get('display_name')}' from processing queue after detailing.")
    context_updates_to_return["service_processing_queue"] = service_processing_queue_copy
    context_updates_to_return["processed_for_auto_detail"] = state_context.get("processed_for_auto_detail", []).copy()
    
    logger.debug(f"RegLogic: handle_category_done for {parent_id_done} total took {time.monotonic() - func_start_time:.4f}s")
    return context_updates_to_return
# === END BLOCK 11 ===

# === BLOCK 12: handle_skip_top_service ===
async def handle_skip_top_service(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    func_start_time = time.monotonic()
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    query = update.callback_query
    context_updates_to_return = {}

    if (not query or not query.data or not query.data.startswith("reg_skip_top_service:")):
        logger.warning(f"RegLogic: User {user_id_log}: handle_skip_top_service called with invalid data: {query.data if query else 'No query'}")
        if query: 
            with suppress(Exception): await query.answer("Ошибка обработки.", show_alert=True)
        logger.debug(f"RegLogic: handle_skip_top_service took {time.monotonic() - func_start_time:.4f}s (invalid data)")
        return None

    try:
        answer_start_time = time.monotonic()
        await query.answer("Услуга/категория пропущена.") 
        logger.debug(f"RegLogic: query.answer() in handle_skip_top_service took {time.monotonic() - answer_start_time:.4f}s")
    except Exception as e_ans:
        logger.warning(f"RegLogic: handle_skip_top_service: Could not answer query: {e_ans}")

    try:
        service_id_to_skip_str = query.data.split(":")[1]
        service_id_to_skip = int(service_id_to_skip_str)
    except (IndexError, ValueError):
        logger.error(f"RegLogic: User {user_id_log}: Invalid service_id in callback for skip_top_service: {query.data}")
        logger.debug(f"RegLogic: handle_skip_top_service took {time.monotonic() - func_start_time:.4f}s (parse error)")
        return None

    logger.info(f"RegLogic: User {user_id_log}: Skipped top service/category ID {service_id_to_skip}.")
    service_processing_queue_copy = state_context.get("service_processing_queue", []).copy()
    if (service_processing_queue_copy and service_processing_queue_copy[0].get("service_id") == service_id_to_skip):
        skipped_service = service_processing_queue_copy.pop(0)
        logger.debug(f"RegLogic: User {user_id_log}: Removed '{skipped_service.get('display_name')}' from processing queue (skipped).")
    context_updates_to_return["service_processing_queue"] = service_processing_queue_copy

    if state_context.get("current_category_being_detailed_id") == service_id_to_skip:
        context_updates_to_return["current_category_being_detailed_id"] = None
        current_category_selections_copy = state_context.get("current_category_selections", {}).copy()
        current_category_selections_copy.pop(str(service_id_to_skip), None)
        context_updates_to_return["current_category_selections"] = current_category_selections_copy
    
    processed_for_auto_detail_copy = state_context.get("processed_for_auto_detail", []).copy()
    if service_id_to_skip not in processed_for_auto_detail_copy: 
        processed_for_auto_detail_copy.append(service_id_to_skip)
    context_updates_to_return["processed_for_auto_detail"] = processed_for_auto_detail_copy
    
    logger.debug(f"RegLogic: handle_skip_top_service for {service_id_to_skip} total took {time.monotonic() - func_start_time:.4f}s")
    return context_updates_to_return
# === END BLOCK 12 ===

# === BLOCK 13: handle_add_direct_service ===
async def handle_add_direct_service(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    func_start_time = time.monotonic()
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    query = update.callback_query
    context_updates_to_return = {}

    if (not query or not query.data or not query.data.startswith("reg_add_direct_service:")):
        logger.warning(f"RegLogic: User {user_id_log}: handle_add_direct_service called with invalid data: {query.data if query else 'No query'}")
        if query: 
            with suppress(Exception): await query.answer("Ошибка обработки.", show_alert=True)
        logger.debug(f"RegLogic: handle_add_direct_service took {time.monotonic() - func_start_time:.4f}s (invalid data)")
        return None
    
    try:
        service_id_to_add_str = query.data.split(":")[1]
        service_id_to_add = int(service_id_to_add_str)
    except (IndexError, ValueError):
        logger.error(f"RegLogic: User {user_id_log}: Invalid service_id in callback for add_direct_service: {query.data}")
        if query: 
            with suppress(Exception): await query.answer("Ошибка: неверный ID услуги.", show_alert=True)
        logger.debug(f"RegLogic: handle_add_direct_service took {time.monotonic() - func_start_time:.4f}s (parse error)")
        return None

    logger.info(f"RegLogic: User {user_id_log}: Directly adding service ID {service_id_to_add}.")
    master_selected_services_copy = state_context.get("master_selected_services", []).copy()
    service_display_name_for_answer = f"Услуга ID {service_id_to_add}" 
    answer_text = ""

    if service_id_to_add not in master_selected_services_copy:
        master_selected_services_copy.append(service_id_to_add)
        context_updates_to_return["master_selected_services"] = master_selected_services_copy
        
        get_service_obj_start_time = time.monotonic()
        service_obj = await session.get(Services, service_id_to_add)
        logger.debug(f"RegLogic: session.get(Services) in add_direct_service took {time.monotonic() - get_service_obj_start_time:.4f}s")

        if service_obj:
            db_user_for_lang_start_time = time.monotonic()
            db_user_for_lang = await session.get(UserData, user.id)
            logger.debug(f"RegLogic: session.get(UserData) for lang in add_direct_service took {time.monotonic() - db_user_for_lang_start_time:.4f}s")
            user_lang_code_add = "ru"
            if db_user_for_lang and db_user_for_lang.language_code:
                if db_user_for_lang.language_code.startswith("uk"): user_lang_code_add = "uk"
                elif db_user_for_lang.language_code.startswith("en"): user_lang_code_add = "en"
            service_display_name_for_answer = (getattr(service_obj, f"name_{user_lang_code_add.lower()}", None) or getattr(service_obj, "name_en", None) or service_obj.name_key)
        logger.info(f"RegLogic: User {user_id_log}: Added service '{service_display_name_for_answer}' (ID: {service_id_to_add}) to selections.")
        answer_text = f"Услуга '{service_display_name_for_answer}' добавлена."
    else:
        logger.info(f"RegLogic: User {user_id_log}: Service ID {service_id_to_add} was already selected.")
        answer_text = "Эта услуга уже была добавлена."

    if query:
        try:
            answer_start_time = time.monotonic()
            await query.answer(answer_text)
            logger.debug(f"RegLogic: query.answer() in handle_add_direct_service took {time.monotonic() - answer_start_time:.4f}s")
        except Exception as e_ans:
            logger.warning(f"RegLogic: handle_add_direct_service: Could not answer query: {e_ans}")

    service_processing_queue_copy = state_context.get("service_processing_queue", []).copy()
    if (service_processing_queue_copy and service_processing_queue_copy[0].get("service_id") == service_id_to_add):
        processed_service = service_processing_queue_copy.pop(0)
        logger.debug(f"RegLogic: User {user_id_log}: Removed '{processed_service.get('display_name')}' from processing queue (added directly).")
    context_updates_to_return["service_processing_queue"] = service_processing_queue_copy

    if state_context.get("current_category_being_detailed_id") == service_id_to_add: 
        context_updates_to_return["current_category_being_detailed_id"] = None
        current_category_selections_copy = state_context.get("current_category_selections", {}).copy()
        current_category_selections_copy.pop(str(service_id_to_add), None)
        context_updates_to_return["current_category_selections"] = current_category_selections_copy
    
    context_updates_to_return["processed_for_auto_detail"] = state_context.get("processed_for_auto_detail", []).copy()
    
    logger.debug(f"RegLogic: handle_add_direct_service for {service_id_to_add} total took {time.monotonic() - func_start_time:.4f}s")
    return context_updates_to_return
# === END BLOCK 13 ===

# === END BLOCK: handlers/registration_logic.py (Конец файла) ===