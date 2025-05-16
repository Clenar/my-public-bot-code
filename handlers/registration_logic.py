# === BLOCK: handlers/registration_logic.py (Начало файла) ===
# handlers/registration_logic.py

# === BLOCK 1: Imports ===
import json
import logging
from contextlib import suppress  # <--- ДОБАВЛЕНО НА СЛУЧАЙ SIM105
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

# Импорты из вашего проекта
try:
    from ai.interaction import _get_instruction_text, generate_text_response
except ImportError:
    logging.getLogger(__name__).error(
        "Failed to import from ai.interaction for registration_logic"
    )

    async def generate_text_response(*args, **kwargs) -> Optional[str]:
        logging.getLogger(__name__).error(
            "Using MOCK generate_text_response due to import error."
        )
        if kwargs.get("instruction_key") == "classify_master_services_prompt":
            user_input = kwargs.get("user_reply_for_format", "")
            if "брови" in user_input and "ресницы" in user_input:
                return json.dumps(
                    {
                        "matched_services": [
                            {
                                "name_key": "beauty_services.eyebrows",
                                "user_provided_text": "брови",
                            },
                            {
                                "name_key": "beauty_services.eyelashes",
                                "user_provided_text": "ресницы",
                            },
                        ],
                        "unmatched_phrases": [],
                        "needs_clarification": False,
                    }
                )
            elif "маникюр" in user_input:
                return json.dumps(
                    {
                        "matched_services": [
                            {
                                "name_key": "beauty_services.nail_service.manicure",
                                "user_provided_text": "маникюр",
                            }
                        ],
                        "unmatched_phrases": [],
                        "needs_clarification": False,
                    }
                )
            return json.dumps(
                {
                    "matched_services": [],
                    "unmatched_phrases": [user_input],
                    "needs_clarification": True,
                }
            )
        return None

    async def _get_instruction_text(*args, **kwargs) -> Optional[str]:
        logging.getLogger(__name__).error(
            "Using MOCK _get_instruction_text due to import error."
        )
        return (
            "Mocked instruction text: {user_reply}"
            if kwargs.get("instruction_key") == "classify_master_services_prompt"
            else "Mocked text"
        )


try:
    from BehaviorEngine.state_manager import reset_user_state, update_user_state
    from database.models import Services, UserData, UserStates
except ImportError:
    logging.getLogger(__name__).error(
        "Failed to import DB models or state_manager for registration_logic"
    )

    class Services:
        pass

    class UserData:
        pass

    class UserStates:
        pass

    async def update_user_state(*args, **kwargs):
        pass

    async def reset_user_state(*args, **kwargs):
        pass


CALLBACK_CONFIRM_CITY_PREFIX = "confirm_city_reg:"
# === END BLOCK 1 ===


# === BLOCK 2: Вспомогательная функция для получения дочерних услуг ===
async def get_service_children(
    session: AsyncSession, parent_service_id: Optional[int], lang_code: str
) -> List[Dict[str, Any]]:
    children_services = []
    if not parent_service_id:
        logger.warning("get_service_children: parent_service_id не предоставлен.")
        return children_services

    try:
        stmt = (
            select(Services)
            .where(
                Services.parent_id == parent_service_id,
                Services.is_selectable_by_master,  # ИСПРАВЛЕНО E712
            )
            .order_by(Services.service_id)
        )

        result = await session.execute(stmt)

        for row in result.scalars().all():
            display_name = (
                getattr(row, f"name_{lang_code.lower()}", None)
                or getattr(row, "name_en", None)
                or row.name_key
            )

            stmt_grand_children = (
                select(Services.service_id)
                .where(
                    Services.parent_id == row.service_id,
                    Services.is_selectable_by_master,  # ИСПРАВЛЕНО E712
                )
                .limit(1)
            )
            result_grand_children = await session.execute(stmt_grand_children)
            has_grand_children = result_grand_children.scalar_one_or_none() is not None

            children_services.append(
                {
                    "service_id": row.service_id,
                    "name_key": row.name_key,
                    "display_name": display_name,
                    "has_children": has_grand_children,
                }
            )
        logger.debug(
            f"Fetched {len(children_services)} selectable children for parent_id {parent_service_id}"
        )
    except Exception as e:
        logger.error(
            f"Error fetching children for parent_id {parent_service_id}: {e}",
            exc_info=True,
        )
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
    user = update.effective_user
    if not user or not update.effective_chat:
        logger.warning("[prepare_city_confirmation] User or chat_id not found.")
        return {"error": "User or chat_id not found, cannot proceed."}

    user_id_log = user.id
    chat_id = update.effective_chat.id
    logger.info(
        f"[prepare_city_confirmation] Called for user {user_id_log}. State_context: {state_context}"
    )

    ai_response_text = state_context.get("city_ai_response")

    # Улучшенная проверка ответа AI на город
    parsed_city_name: Optional[str] = None
    parsed_country_name: str = "N/A"
    parsed_region_name: str = "N/A"
    city_found_marker = "CITY_FOUND:"

    # Ищем маркер в строке, а не только в начале
    if (
        ai_response_text
        and isinstance(ai_response_text, str)
        and city_found_marker in ai_response_text
    ):
        try:
            # Извлекаем часть строки ПОСЛЕ маркера
            parts_str = ai_response_text.split(city_found_marker, 1)[1].strip()
            first_line_of_city_data = parts_str.split("\n")[
                0
            ]  # Берем только первую строку данных
            parts = [p.strip() for p in first_line_of_city_data.split("|")]

            city_name_from_ai = parts[0]
            country_name_from_ai = parts[1] if len(parts) > 1 else "N/A"
            region_name_from_ai = parts[2] if len(parts) > 2 else "N/A"

            if not city_name_from_ai:  # Город должен быть не пустым
                raise ValueError("AI returned CITY_FOUND, but the city name is empty.")

            parsed_city_name = city_name_from_ai
            parsed_country_name = country_name_from_ai
            parsed_region_name = region_name_from_ai

            logger.info(
                f"User {user_id_log}: AI response parsed. City: '{parsed_city_name}', "
                f"Country: '{parsed_country_name}', Region: '{parsed_region_name}'."
            )
        except Exception as parse_error:
            logger.error(
                f"User {user_id_log}: Error parsing '{city_found_marker}' AI response '{ai_response_text}': {parse_error}"
            )
            parsed_city_name = None  # Сбрасываем, если парсинг не удался
            # Отправляем сообщение об ошибке парсинга и просим ввести город заново
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Вибачте, не вдалося точно розпізнати місто. Спробуйте, будь ласка, ввести його ще раз.",
                )
            except Exception as e_msg:
                logger.error(
                    f"Failed to send city parsing error message to user {user_id_log}: {e_msg}"
                )

            await update_user_state(
                user.id,
                state_context.get("scenario_key", "master_registration_v1"),
                "REG_MASTER_ASK_CITY",
                {"city_ai_response": None},
                session,
            )
            return {
                "handler_initiated_scenario_switch": True,
                "error_message": "AI response (CITY_FOUND) parsing failed",
            }

    # Если город был успешно распарсен, показываем кнопки подтверждения
    if parsed_city_name:
        confirmation_text = (
            f"Здається, ви вказали місто: **{parsed_city_name}**"
            f"{f' ({parsed_country_name})' if parsed_country_name and parsed_country_name != 'N/A' else ''}.\n"
            f"Це вірно?"
        )

        safe_city_name_for_callback = parsed_city_name.replace(":", "_").replace(
            "|", "_"
        )
        keyboard = [
            [
                InlineKeyboardButton(
                    f"✅ Так, це {parsed_city_name}",
                    callback_data=f"{CALLBACK_CONFIRM_CITY_PREFIX}{safe_city_name_for_callback}",
                ),
                InlineKeyboardButton("🔄 Інше місто", callback_data="change_city_reg"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=confirmation_text,
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            logger.info(
                f"User {user_id_log}: Sent city confirmation for '{parsed_city_name}'."
            )
            return {
                "proposed_city_for_confirmation": parsed_city_name,
                "proposed_country": parsed_country_name,
                "proposed_region": parsed_region_name,
                "message_with_buttons_sent": True,
            }
        except Exception as e:  # Ошибка отправки сообщения с кнопками
            logger.error(
                f"User {user_id_log}: Failed to send city confirmation message with keyboard: {e}"
            )
            # Пробуем отправить простое сообщение об ошибке, если кнопки не отправились
            with suppress(
                Exception
            ):  # Здесь SIM105 может быть уместен, если мы просто хотим подавить ошибку отправки второго сообщения
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Вибачте, сталася помилка. Спробуйте ввести місто ще раз.",
                )
            await update_user_state(
                user.id,
                state_context.get("scenario_key", "master_registration_v1"),
                "REG_MASTER_ASK_CITY",
                {"city_ai_response": None},
                session,
            )
            return {
                "handler_initiated_scenario_switch": True,
                "error": "Failed to send city confirmation message.",
            }
    else:
        # Если CITY_FOUND не найдено или ai_response_text пустой/невалидный
        clarification_message = (
            ai_response_text
            if (
                ai_response_text
                and isinstance(ai_response_text, str)
                and len(ai_response_text) < 200
            )
            else "Будь ласка, уточніть назву міста або введіть її ще раз."
        )
        if not ai_response_text or not isinstance(ai_response_text, str):
            logger.warning(
                f"User {user_id_log}: No valid 'city_ai_response' in state_context for clarification. Using default message."
            )
        else:
            logger.info(
                f"User {user_id_log}: AI did not return 'CITY_FOUND:'. AI response used as clarification: '{ai_response_text}'"
            )

        try:
            await context.bot.send_message(chat_id=chat_id, text=clarification_message)
        except Exception as e:
            logger.error(
                f"Failed to send AI's clarification/response to user {user_id_log}: {e}"
            )

        await update_user_state(
            user.id,
            state_context.get("scenario_key", "master_registration_v1"),
            "REG_MASTER_ASK_CITY",
            {
                "city_ai_response": None,
                "last_ai_clarification": ai_response_text
                if ai_response_text
                else "N/A",
            },
            session,
        )
        return {
            "handler_initiated_scenario_switch": True,
            "ai_clarification_sent": True,
        }


# === END BLOCK 4 ===


# === BLOCK 5: handle_city_confirmation_callback ===
# ... (код без изменений, как вы присылали) ...
async def handle_city_confirmation_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    query = update.callback_query
    if not query or not query.data:
        logger.warning("[handle_city_confirmation_callback] No callback query or data.")
        return None

    await query.answer()

    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    callback_data = query.data

    logger.info(
        f"[handle_city_confirmation_callback] User {user_id_log} pressed callback: '{callback_data}'"
    )

    if callback_data.startswith(CALLBACK_CONFIRM_CITY_PREFIX):
        confirmed_city = callback_data[len(CALLBACK_CONFIRM_CITY_PREFIX) :]

        logger.info(f"User {user_id_log}: Confirmed city '{confirmed_city}'.")
        try:
            await query.edit_message_text(
                text=f"Місто {confirmed_city} підтверджено. Чудово!"
            )
        except Exception as e:
            logger.error(
                f"Error editing message after city confirmation for user {user_id_log}: {e}"
            )

        return {
            "master_reg_confirmed_city": confirmed_city,
            "city_confirmation_status": "confirmed",
            "next_state_for_yaml": "REG_MASTER_ASK_SERVICES_INITIAL",
        }
    elif callback_data == "change_city_reg":
        logger.info(f"User {user_id_log}: Chose to change city.")
        try:
            await query.edit_message_text(
                text="Добре, давайте спробуємо ввести місто ще раз."
            )
        except Exception as e:
            logger.error(
                f"Error editing message for city change request by user {user_id_log}: {e}"
            )

        return {
            "city_ai_response": None,
            "proposed_city_for_confirmation": None,
            "city_confirmation_status": "change_requested",
            "next_state_for_yaml": "REG_MASTER_ASK_CITY",
        }
    else:
        logger.warning(
            f"User {user_id_log}: Received unknown callback_data in city confirmation: '{callback_data}'"
        )
        try:
            await query.edit_message_text(
                text="Вибачте, ця дія зараз недоступна. Спробуйте /start."
            )
        except Exception:
            pass
        return None


# === END BLOCK 5 ===


# === BLOCK 6: reset_user_state_handler (для REG_MASTER_END_STUB) ===
# ... (код без изменений, как вы присылали) ...
async def reset_user_state_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    user = update.effective_user
    if not user:
        logger.warning("[reset_user_state_handler] User not found.")
        return {"error": "User not found, cannot reset state."}

    user_id = user.id
    logger.info(
        f"[reset_user_state_handler] Attempting to reset state for user {user_id}."
    )

    try:
        reset_success = await reset_user_state(user_id, session)
        if reset_success:
            logger.info(
                f"User {user_id} state has been reset successfully via handler."
            )
            return {"state_reset_status": "success"}
        else:
            logger.warning(
                f"Failed to reset state for user {user_id} via handler (reset_user_state returned False)."
            )
            return {"state_reset_status": "failed"}
    except Exception as e:
        logger.error(
            f"Error in reset_user_state_handler for user {user_id}: {e}", exc_info=True
        )
        return {"state_reset_status": "error", "error_message": str(e)}


# === END BLOCK 6 ===


# === BLOCK 7: analyze_and_match_services_initial ===
# ... (код с обогащением данных, как я присылал ранее, с ИСПРАВЛЕННЫМИ E712) ...
async def analyze_and_match_services_initial(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        logger.warning(
            "[analyze_and_match_services_initial] User or message text not found."
        )
        return {
            "next_step_recommendation": "REG_MASTER_ASK_SERVICES_AGAIN",
            "error_message": "No message text from user",
        }

    user_id_log = user.id
    master_services_text_input = update.message.text
    logger.info(
        f"[analyze_and_match_services_initial] User {user_id_log} entered services: '{master_services_text_input}'"
    )

    instruction_key_to_test = "classify_master_services_prompt"

    db_user = await session.get(UserData, user.id)
    user_lang_code_for_display = "ru"
    if db_user and db_user.language_code:
        if db_user.language_code.startswith("uk"):
            user_lang_code_for_display = "uk"
        elif db_user.language_code.startswith("en"):
            user_lang_code_for_display = "en"
    logger.debug(
        f"User {user_id_log} language for service display: {user_lang_code_for_display}"
    )

    ai_response_json_str: Optional[str] = None
    try:
        logger.info(
            f"Calling AI with instruction_key='{instruction_key_to_test}' and user_reply_for_format='{master_services_text_input}' for lang='ru'"
        )
        ai_response_json_str = await generate_text_response(
            messages=[],
            instruction_key=instruction_key_to_test,
            user_reply_for_format=master_services_text_input,
            session=session,
            user_lang_code="ru",
        )
        logger.info(
            f"Raw AI response string for services (user {user_id_log}): \n---\n{ai_response_json_str}\n---"
        )
    except Exception as e:
        logger.error(
            f"Error calling AI for service classification (user {user_id_log}): {e}",
            exc_info=True,
        )
        return {
            "services_text_input": master_services_text_input,
            "ai_raw_response": None,
            "needs_clarification": True,
            "next_step_recommendation": "REG_MASTER_ASK_SERVICES_AGAIN",
            "error_message": f"AI call failed: {str(e)}",
        }

    if not ai_response_json_str:
        logger.warning(
            f"AI returned no response string for service classification (user {user_id_log})."
        )
        return {
            "services_text_input": master_services_text_input,
            "ai_raw_response": None,
            "needs_clarification": True,
            "next_step_recommendation": "REG_MASTER_ASK_SERVICES_AGAIN",
            "error_message": "AI did not respond",
        }

    ai_parsed_data: Optional[Dict[str, Any]] = None
    try:
        ai_parsed_data = json.loads(ai_response_json_str)
        if (
            not isinstance(ai_parsed_data, dict)
            or not isinstance(ai_parsed_data.get("matched_services"), list)
            or not isinstance(ai_parsed_data.get("unmatched_phrases"), list)
            or not isinstance(ai_parsed_data.get("needs_clarification"), bool)
        ):
            raise ValueError("AI response JSON structure is invalid.")
        for item in ai_parsed_data.get("matched_services", []):
            if not (
                isinstance(item, dict)
                and "name_key" in item
                and "user_provided_text" in item
            ):
                raise ValueError("Invalid item structure in 'matched_services'.")
        logger.info(
            f"AI response for services (user {user_id_log}) successfully parsed: {ai_parsed_data}"
        )
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(
            f"Error parsing AI JSON response for services (user {user_id_log}): '{ai_response_json_str}'. Error: {e}"
        )
        return {
            "services_text_input": master_services_text_input,
            "ai_raw_response": ai_response_json_str,
            "ai_parsed_data": None,
            "needs_clarification": True,
            "next_step_recommendation": "REG_MASTER_ASK_SERVICES_AGAIN",
            "error_message": f"Invalid JSON from AI: {str(e)}",
        }

    enriched_matched_services = []
    if ai_parsed_data:
        matched_services_from_ai = ai_parsed_data.get("matched_services", [])
        for ai_service in matched_services_from_ai:
            if isinstance(ai_service, dict) and "name_key" in ai_service:
                name_key = ai_service["name_key"]
                user_provided_text = ai_service.get("user_provided_text", "")

                service_id_db: Optional[int] = None
                display_name_db: str = f"Услуга ({name_key})"
                parent_id_db: Optional[int] = None
                has_children_db: bool = False
                is_selectable_by_master_db: bool = False

                try:
                    stmt_service = select(Services).where(Services.name_key == name_key)
                    result_service = await session.execute(stmt_service)
                    db_service_obj = result_service.scalar_one_or_none()

                    if db_service_obj:
                        service_id_db = db_service_obj.service_id
                        display_name_db = (
                            getattr(
                                db_service_obj,
                                f"name_{user_lang_code_for_display.lower()}",
                                None,
                            )
                            or db_service_obj.name_en
                            or name_key
                        )
                        parent_id_db = db_service_obj.parent_id
                        is_selectable_by_master_db = (
                            db_service_obj.is_selectable_by_master
                        )

                        stmt_children = (
                            select(Services.service_id)
                            .where(
                                Services.parent_id == service_id_db,
                                Services.is_selectable_by_master,  # ИСПРАВЛЕНО E712
                            )
                            .limit(1)
                        )
                        result_children = await session.execute(stmt_children)
                        if result_children.scalar_one_or_none() is not None:
                            has_children_db = True

                        logger.info(
                            f"Enriched service '{name_key}': ID={service_id_db}, Name='{display_name_db}', HasChildren={has_children_db}, Selectable={is_selectable_by_master_db}, ParentID={parent_id_db}"
                        )
                    else:
                        logger.warning(
                            f"Service with name_key '{name_key}' not found in DB for enrichment."
                        )
                except Exception as db_exc:
                    logger.error(
                        f"DB error enriching service '{name_key}': {db_exc}",
                        exc_info=True,
                    )

                enriched_matched_services.append(
                    {
                        "name_key": name_key,
                        "service_id": service_id_db,
                        "display_name": display_name_db,
                        "has_children": has_children_db,
                        "parent_id": parent_id_db,
                        "user_provided_text": user_provided_text,
                        "is_selectable_by_master": is_selectable_by_master_db,
                    }
                )

    next_step = "REG_MASTER_ASK_SERVICES_AGAIN"
    if ai_parsed_data:
        if (
            ai_parsed_data.get("needs_clarification") or not enriched_matched_services
        ):  # ИСПРАВЛЕНО E712 (было is True)
            next_step = "REG_MASTER_ASK_SERVICES_AGAIN"
        elif enriched_matched_services:
            next_step = "REG_MASTER_SHOW_SERVICE_SUGGESTIONS"

    analysis_result = {
        "services_text_input": master_services_text_input,
        "ai_raw_response": ai_response_json_str,
        "ai_parsed_data": ai_parsed_data,
        "matched_services_info": enriched_matched_services,
        "unmatched_phrases": ai_parsed_data.get("unmatched_phrases", [])
        if ai_parsed_data
        else [master_services_text_input],
        "needs_clarification": ai_parsed_data.get("needs_clarification", True)
        if ai_parsed_data
        else True,
        "next_step_recommendation": next_step,
    }
    return analysis_result


# === END BLOCK 7 ===


# === BLOCK 8: prepare_service_suggestions_message (Улучшенная версия с немедленной авто-детализацией) ===
# ... (код как в моем предыдущем ответе, с исправлениями E712 внутри него, если они там были нужны) ...
async def prepare_service_suggestions_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    chat_id = update.effective_chat.id if update.effective_chat else None
    query = update.callback_query

    logger.info(f"[prepare_service_suggestions_message] Called for user {user_id_log}.")

    if (
        "service_processing_queue" not in state_context
        and "service_analysis_result" in state_context
    ):
        service_analysis_result = state_context.get("service_analysis_result", {})
        initial_matched_services = service_analysis_result.get(
            "matched_services_info", []
        )
        state_context["service_processing_queue"] = [
            s for s in initial_matched_services if s.get("service_id")
        ]
        state_context["master_selected_services"] = state_context.get(
            "master_selected_services", []
        )
        state_context["current_category_selections"] = state_context.get(
            "current_category_selections", {}
        )
        state_context["current_category_being_detailed_id"] = None
        state_context["service_suggestion_message_id"] = None
        state_context["processed_for_auto_detail"] = []
        logger.info(
            f"User {user_id_log}: Initialized/reset service processing. Queue: {len(state_context.get('service_processing_queue',[]))} services."
        )
    elif (
        "service_analysis_result" in state_context
        and not state_context.get("service_processing_queue")
        and not state_context.get("current_category_being_detailed_id")
    ):  # Добавил проверку на current_category_being_detailed_id
        service_analysis_result = state_context.get("service_analysis_result", {})
        initial_matched_services = service_analysis_result.get(
            "matched_services_info", []
        )
        state_context["service_processing_queue"] = [
            s for s in initial_matched_services if s.get("service_id")
        ]
        logger.info(
            f"User {user_id_log}: Re-initialized service processing queue for a new set of services as queue was empty and no category was being detailed."
        )

    service_processing_queue: List[Dict[str, Any]] = state_context.get(
        "service_processing_queue", []
    )
    master_selected_services: List[int] = state_context.get(
        "master_selected_services", []
    )

    db_user = await session.get(UserData, user.id)
    user_lang_code_for_display = "ru"
    if db_user and db_user.language_code:
        if db_user.language_code.startswith("uk"):
            user_lang_code_for_display = "uk"
        elif db_user.language_code.startswith("en"):
            user_lang_code_for_display = "en"

    message_text = ""
    keyboard_buttons = []

    current_category_id_detailed = state_context.get(
        "current_category_being_detailed_id"
    )
    processed_for_auto_detail = state_context.get("processed_for_auto_detail", [])

    if not current_category_id_detailed and service_processing_queue:
        first_service_in_queue = service_processing_queue[0]
        first_service_id = first_service_in_queue.get("service_id")

        if (
            first_service_id not in processed_for_auto_detail
            and first_service_in_queue.get("has_children")
            and not first_service_in_queue.get("is_selectable_by_master")
        ):
            current_category_id_detailed = first_service_id
            state_context["current_category_being_detailed_id"] = (
                current_category_id_detailed
            )
            state_context.get("current_category_selections", {}).pop(
                str(current_category_id_detailed), None
            )
            processed_for_auto_detail.append(first_service_id)
            state_context["processed_for_auto_detail"] = processed_for_auto_detail
            logger.info(
                f"User {user_id_log}: Auto-detailing first category: '{first_service_in_queue.get('display_name')}' (ID: {current_category_id_detailed})."
            )

    if current_category_id_detailed:
        parent_service_obj = await session.get(Services, current_category_id_detailed)
        if not parent_service_obj:
            logger.error(
                f"User {user_id_log}: Parent service ID {current_category_id_detailed} for detailing not found. Clearing detail state."
            )
            state_context.pop("current_category_being_detailed_id", None)
            state_context.pop("processed_for_auto_detail", None)
            if query:
                await query.answer("Ошибка: категория не найдена.", show_alert=True)
            return {"next_state_for_yaml": "REG_MASTER_SHOW_SERVICE_SUGGESTIONS"}

        parent_display_name = (
            getattr(
                parent_service_obj, f"name_{user_lang_code_for_display.lower()}", None
            )
            or getattr(parent_service_obj, "name_en", None)
            or parent_service_obj.name_key
        )
        children_services = await get_service_children(
            session, current_category_id_detailed, user_lang_code_for_display
        )

        if not children_services:
            logger.info(
                f"User {user_id_log}: Category '{parent_display_name}' (ID: {current_category_id_detailed}) has no selectable children. Adding parent itself if selectable and not already added."
            )
            if (
                parent_service_obj.is_selectable_by_master
                and parent_service_obj.service_id not in master_selected_services
            ):  # ИСПРАВЛЕНО E712
                master_selected_services.append(parent_service_obj.service_id)
                state_context["master_selected_services"] = master_selected_services
                logger.info(
                    f"User {user_id_log}: Added parent service '{parent_display_name}' (ID: {parent_service_obj.service_id}) as it has no selectable children for detailing."
                )

            state_context.pop("current_category_being_detailed_id", None)
            state_context.get("current_category_selections", {}).pop(
                str(current_category_id_detailed), None
            )
            if (
                service_processing_queue
                and service_processing_queue[0].get("service_id")
                == current_category_id_detailed
            ):
                service_processing_queue.pop(0)
                state_context["service_processing_queue"] = service_processing_queue

            if query:
                await query.answer(
                    f"Для '{parent_display_name}' нет подуслуг. Переходим к следующей."
                )
            return {"next_state_for_yaml": "REG_MASTER_SHOW_SERVICE_SUGGESTIONS"}

        message_text = f"Категория: **{parent_display_name}**.\nВыберите уточняющие услуги (можно несколько, повторное нажатие меняет выбор):"
        current_selections_for_this_category = state_context.get(
            "current_category_selections", {}
        ).get(str(current_category_id_detailed), [])

        for child in children_services:
            is_selected = child["service_id"] in current_selections_for_this_category
            button_text = f"{'✅ ' if is_selected else '☑️ '} {child['display_name']}"
            keyboard_buttons.append(
                [
                    InlineKeyboardButton(
                        button_text,
                        callback_data=f"reg_toggle_sub_service:{child['service_id']}:{current_category_id_detailed}",
                    )
                ]
            )

        keyboard_buttons.append(
            [
                InlineKeyboardButton(
                    f"👍 Готово с '{parent_display_name}'",
                    callback_data=f"reg_category_done:{current_category_id_detailed}",
                )
            ]
        )

    elif service_processing_queue:
        current_service_to_process = service_processing_queue[0]
        service_id = current_service_to_process.get("service_id")
        display_name = current_service_to_process.get("display_name")
        has_children = current_service_to_process.get("has_children", False)
        is_selectable = current_service_to_process.get("is_selectable_by_master", False)

        if has_children:
            logger.info(
                f"User {user_id_log}: Offering to detail category '{display_name}' (ID: {service_id}) (manual choice)."
            )
            message_text = f"Распознана категория услуг: **{display_name}**. Желаете уточнить услуги в этой категории?"
            keyboard_buttons.append(
                [
                    InlineKeyboardButton(
                        f"🔍 Да, уточнить '{display_name}'",
                        callback_data=f"reg_detail_category:{service_id}",
                    )
                ]
            )
            if is_selectable and service_id not in master_selected_services:
                keyboard_buttons.append(
                    [
                        InlineKeyboardButton(
                            f"➕ Добавить '{display_name}' (всю категорию)",
                            callback_data=f"reg_add_direct_service:{service_id}",
                        )
                    ]
                )
            keyboard_buttons.append(
                [
                    InlineKeyboardButton(
                        f"➡️ Пропустить '{display_name}'",
                        callback_data=f"reg_skip_top_service:{service_id}",
                    )
                ]
            )
        elif is_selectable:
            logger.info(
                f"User {user_id_log}: Offering direct service '{display_name}' (ID: {service_id})."
            )
            message_text = f"Мы распознали у вас услугу: **{display_name}**. Добавить ее в ваш список?"
            keyboard_buttons.append(
                [
                    InlineKeyboardButton(
                        f"✅ Да, добавить '{display_name}'",
                        callback_data=f"reg_add_direct_service:{service_id}",
                    )
                ]
            )
            keyboard_buttons.append(
                [
                    InlineKeyboardButton(
                        "➡️ Нет, пропустить",
                        callback_data=f"reg_skip_top_service:{service_id}",
                    )
                ]
            )
        else:
            logger.warning(
                f"User {user_id_log}: Service '{display_name}' (ID: {service_id}) is not selectable and has no children for detailing. Auto-skipping."
            )
            state_context["service_processing_queue"].pop(0)
            if query:
                await query.answer("Услуга пропущена.")
            return {"next_state_for_yaml": "REG_MASTER_SHOW_SERVICE_SUGGESTIONS"}

    else:
        logger.info(
            f"User {user_id_log}: Service processing queue is empty. Finalizing service selection."
        )
        final_message = "Выбор услуг завершен."
        if master_selected_services:
            selected_names = []
            processed_ids_for_names = set()
            for service_id_selected in master_selected_services:
                if service_id_selected in processed_ids_for_names:
                    continue
                service_obj = await session.get(Services, service_id_selected)
                if service_obj:
                    display_name_sel = (
                        getattr(
                            service_obj,
                            f"name_{user_lang_code_for_display.lower()}",
                            None,
                        )
                        or getattr(service_obj, "name_en", None)
                        or service_obj.name_key
                    )
                    selected_names.append(f"- {display_name_sel}")
                    processed_ids_for_names.add(service_id_selected)
            if selected_names:
                final_message += " Вы выбрали:\n" + "\n".join(selected_names)
            else:
                final_message += " Вы пока не выбрали ни одной конкретной услуги."
        else:
            final_message += " Вы пока не выбрали ни одной конкретной услуги. Вы сможете добавить их позже из своего профиля."

        if chat_id:
            if query:
                await query.answer()
            last_suggestion_message_id = state_context.get(
                "service_suggestion_message_id"
            )
            if last_suggestion_message_id:
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=last_suggestion_message_id,
                        reply_markup=None,
                    )
                except Exception as e_final_edit:
                    logger.warning(
                        f"Could not remove keyboard from final message {last_suggestion_message_id}: {e_final_edit}"
                    )

            await context.bot.send_message(chat_id=chat_id, text=final_message)

        state_context.pop("service_processing_queue", None)
        state_context.pop("current_category_selections", None)
        state_context.pop("current_category_being_detailed_id", None)
        state_context.pop("service_suggestion_message_id", None)
        state_context.pop("processed_for_auto_detail", None)
        return {"next_state_for_yaml": "REG_MASTER_ALL_SERVICES_CONFIRMED"}

    reply_markup = InlineKeyboardMarkup(keyboard_buttons)
    message_to_send = message_text if message_text else "Пожалуйста, выберите действие."
    edit_message_id = state_context.get("service_suggestion_message_id")

    if (
        query
        and query.message
        and edit_message_id
        and query.message.message_id == edit_message_id
    ):
        try:
            await query.edit_message_text(
                text=message_to_send, reply_markup=reply_markup, parse_mode="Markdown"
            )
            logger.info(
                f"Edited message_id {edit_message_id} for service suggestions for user {user_id_log}."
            )
        except Exception as e:
            logger.warning(
                f"Could not edit message {edit_message_id} (user {user_id_log}): {e}. Answering callback and sending new message."
            )
            await query.answer()
            if chat_id:
                sent_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=message_to_send,
                    reply_markup=reply_markup,
                    parse_mode="Markdown",
                )
                state_context["service_suggestion_message_id"] = sent_message.message_id
    elif chat_id:
        if edit_message_id and query:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=edit_message_id, reply_markup=None
                )
                logger.info(
                    f"Removed keyboard from previous message {edit_message_id} before sending new one."
                )
            except Exception as e_edit_kb:
                logger.warning(
                    f"Could not remove keyboard from previous message {edit_message_id}: {e_edit_kb}"
                )

        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=message_to_send,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
        state_context["service_suggestion_message_id"] = sent_message.message_id
        logger.info(
            f"Sent new service suggestions message (ID: {sent_message.message_id}) to user {user_id_log}."
        )
        if query:
            await query.answer()
    else:
        logger.error(
            f"Cannot send service suggestions message to user {user_id_log}: chat_id is missing."
        )
        if query:
            await query.answer("Ошибка: chat_id отсутствует.")
        return {"error_message": "Missing chat_id."}

    await update_user_state(
        user_id=user.id,
        scenario_key=state_context.get("scenario_key", "master_registration_v1"),
        state_key="REG_MASTER_SHOW_SERVICE_SUGGESTIONS",
        context_data=state_context,
        session=session,
    )
    return None


# === END BLOCK 8 ===


# === BLOCK 9: handle_detail_category ===
# ... (код без изменений, как я присылал) ...
async def handle_detail_category(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    query = update.callback_query

    if not query or not query.data:
        logger.warning(
            f"User {user_id_log}: handle_detail_category_callback called without query data."
        )
        if query:
            await query.answer("Ошибка: нет данных.", show_alert=True)
        return None

    parent_service_id_str = query.data.split(":")[1]
    try:
        parent_service_id = int(parent_service_id_str)
    except ValueError:
        logger.error(
            f"User {user_id_log}: Invalid parent_service_id in callback: {parent_service_id_str}"
        )
        await query.answer("Ошибка: неверный ID категории.", show_alert=True)
        return None

    logger.info(f"User {user_id_log}: Chose to detail category ID {parent_service_id}.")

    state_context["current_category_being_detailed_id"] = parent_service_id
    if str(parent_service_id) not in state_context.get(
        "current_category_selections", {}
    ):
        state_context.setdefault("current_category_selections", {})[
            str(parent_service_id)
        ] = []

    return {"handler_initiated_payload_for_next_on_entry": True}


# === END BLOCK 9 ===


# === BLOCK 10: handle_toggle_sub_service ===
# ... (код без изменений, как я присылал) ...
async def handle_toggle_sub_service(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    query = update.callback_query

    if (
        not query
        or not query.data
        or not query.data.startswith("reg_toggle_sub_service:")
    ):
        logger.warning(
            f"User {user_id_log}: handle_toggle_sub_service called with invalid data: {query.data if query else 'No query'}"
        )
        if query:
            await query.answer("Ошибка обработки выбора.", show_alert=True)
        return None

    try:
        _, child_id_str, parent_id_str = query.data.split(":")
        child_id = int(child_id_str)
        parent_id = int(parent_id_str)
    except ValueError:
        logger.error(f"User {user_id_log}: Invalid IDs in callback data: {query.data}")
        await query.answer("Ошибка: неверные ID услуг.", show_alert=True)
        return None

    logger.info(
        f"User {user_id_log}: Toggled sub-service ID {child_id} for parent ID {parent_id}."
    )

    current_selections = state_context.get("current_category_selections", {})
    # Убедимся, что ключ parent_id существует как строка
    parent_id_key = str(parent_id)
    if parent_id_key not in current_selections:
        current_selections[parent_id_key] = []

    if child_id in current_selections[parent_id_key]:
        current_selections[parent_id_key].remove(child_id)
        logger.debug(
            f"User {user_id_log}: Sub-service {child_id} REMOVED from selections for category {parent_id_key}"
        )
    else:
        current_selections[parent_id_key].append(child_id)
        logger.debug(
            f"User {user_id_log}: Sub-service {child_id} ADDED to selections for category {parent_id_key}"
        )

    state_context["current_category_selections"] = current_selections
    return {"handler_initiated_payload_for_next_on_entry": True}


# === END BLOCK 10 ===


# === BLOCK 11: handle_category_done ===
# ... (код без изменений, как я присылал) ...
async def handle_category_done(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    query = update.callback_query

    if not query or not query.data or not query.data.startswith("reg_category_done:"):
        logger.warning(
            f"User {user_id_log}: handle_category_done called with invalid data: {query.data if query else 'No query'}"
        )
        if query:
            await query.answer("Ошибка обработки.", show_alert=True)
        return None

    try:
        parent_id_done_str = query.data.split(":")[1]
        parent_id_done = int(parent_id_done_str)
    except ValueError:
        logger.error(
            f"User {user_id_log}: Invalid parent_id in callback for category_done: {parent_id_done_str}"
        )
        await query.answer("Ошибка: неверный ID категории.", show_alert=True)
        return None

    logger.info(f"User {user_id_log}: Finished with category ID {parent_id_done}.")

    current_selections_for_category = state_context.get(
        "current_category_selections", {}
    ).get(str(parent_id_done), [])
    master_selected_services: List[int] = state_context.get(
        "master_selected_services", []
    )

    for sub_service_id in current_selections_for_category:
        if sub_service_id not in master_selected_services:
            master_selected_services.append(sub_service_id)

    # Если в категории ничего не выбрано, а сама категория (parent_id_done) выбираема и еще не добавлена,
    # то можно ее добавить. Но это если такая логика нужна.
    # Пока просто добавляем то, что было отмечено в current_category_selections.
    if not current_selections_for_category:
        parent_service_obj = await session.get(Services, parent_id_done)
        if (
            parent_service_obj
            and parent_service_obj.is_selectable_by_master
            and parent_service_obj.service_id not in master_selected_services
        ):
            master_selected_services.append(parent_service_obj.service_id)
            logger.info(
                f"User {user_id_log}: No sub-services selected for '{parent_service_obj.name_ru}', adding parent category itself (ID: {parent_id_done}) as it's selectable."
            )

    state_context["master_selected_services"] = master_selected_services
    logger.info(
        f"User {user_id_log}: Final selected services after category {parent_id_done}: {master_selected_services}"
    )

    state_context.pop("current_category_being_detailed_id", None)
    state_context.get("current_category_selections", {}).pop(str(parent_id_done), None)

    service_processing_queue: List[Dict[str, Any]] = state_context.get(
        "service_processing_queue", []
    )
    if (
        service_processing_queue
        and service_processing_queue[0].get("service_id") == parent_id_done
    ):
        processed_service = service_processing_queue.pop(0)
        logger.debug(
            f"User {user_id_log}: Removed '{processed_service.get('display_name')}' from processing queue after detailing."
        )
    state_context["service_processing_queue"] = service_processing_queue
    state_context.pop(
        "processed_for_auto_detail", None
    )  # Сбрасываем, т.к. категория обработана

    if query:
        await query.answer("Выбор в категории сохранен.")
    return {"next_state_for_yaml": "REG_MASTER_SHOW_SERVICE_SUGGESTIONS"}


# === END BLOCK 11 ===


# === BLOCK 12: handle_skip_top_service ===
# ... (код без изменений, как я присылал) ...
async def handle_skip_top_service(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    query = update.callback_query

    if (
        not query
        or not query.data
        or not query.data.startswith("reg_skip_top_service:")
    ):
        logger.warning(
            f"User {user_id_log}: handle_skip_top_service called with invalid data: {query.data if query else 'No query'}"
        )
        if query:
            await query.answer("Ошибка обработки.", show_alert=True)
        return None

    try:
        service_id_to_skip_str = query.data.split(":")[1]
        service_id_to_skip = int(service_id_to_skip_str)
    except ValueError:
        logger.error(
            f"User {user_id_log}: Invalid service_id in callback for skip_top_service: {service_id_to_skip_str}"
        )
        await query.answer("Ошибка: неверный ID услуги.", show_alert=True)
        return None

    logger.info(
        f"User {user_id_log}: Skipped top service/category ID {service_id_to_skip}."
    )

    service_processing_queue: List[Dict[str, Any]] = state_context.get(
        "service_processing_queue", []
    )
    if (
        service_processing_queue
        and service_processing_queue[0].get("service_id") == service_id_to_skip
    ):
        skipped_service = service_processing_queue.pop(0)
        logger.debug(
            f"User {user_id_log}: Removed '{skipped_service.get('display_name')}' from processing queue (skipped)."
        )
    state_context["service_processing_queue"] = service_processing_queue

    state_context.pop("current_category_being_detailed_id", None)
    state_context.pop("current_category_selections", None)
    state_context.pop("processed_for_auto_detail", None)  # Сбрасываем флаг

    if query:
        await query.answer("Услуга/категория пропущена.")
    return {"next_state_for_yaml": "REG_MASTER_SHOW_SERVICE_SUGGESTIONS"}


# === END BLOCK 12 ===


# === BLOCK 13: handle_add_direct_service ===
# ... (код без изменений, как я присылал) ...
async def handle_add_direct_service(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    user = update.effective_user
    user_id_log = user.id if user else "UnknownUser"
    query = update.callback_query

    if (
        not query
        or not query.data
        or not query.data.startswith("reg_add_direct_service:")
    ):
        logger.warning(
            f"User {user_id_log}: handle_add_direct_service called with invalid data: {query.data if query else 'No query'}"
        )
        if query:
            await query.answer("Ошибка обработки.", show_alert=True)
        return None

    try:
        service_id_to_add_str = query.data.split(":")[1]
        service_id_to_add = int(service_id_to_add_str)
    except ValueError:
        logger.error(
            f"User {user_id_log}: Invalid service_id in callback for add_direct_service: {service_id_to_add_str}"
        )
        await query.answer("Ошибка: неверный ID услуги.", show_alert=True)
        return None

    logger.info(f"User {user_id_log}: Directly adding service ID {service_id_to_add}.")

    master_selected_services: List[int] = state_context.get(
        "master_selected_services", []
    )
    if service_id_to_add not in master_selected_services:
        master_selected_services.append(service_id_to_add)
        state_context["master_selected_services"] = master_selected_services
        service_obj = await session.get(Services, service_id_to_add)
        display_name_add = "Неизвестная услуга"
        if service_obj:
            db_user_for_lang = await session.get(
                UserData, user.id
            )  # Получаем язык пользователя
            user_lang_code_add = "ru"
            if db_user_for_lang and db_user_for_lang.language_code:
                if db_user_for_lang.language_code.startswith("uk"):
                    user_lang_code_add = "uk"
                elif db_user_for_lang.language_code.startswith("en"):
                    user_lang_code_add = "en"
            display_name_add = (
                getattr(service_obj, f"name_{user_lang_code_add.lower()}", None)
                or getattr(service_obj, "name_en", None)
                or service_obj.name_key
            )
        else:
            display_name_add = f"Услуга ID {service_id_to_add}"

        logger.info(
            f"User {user_id_log}: Added service '{display_name_add}' (ID: {service_id_to_add}) to selections."
        )
        if query:
            await query.answer(f"Услуга '{display_name_add}' добавлена.")
    else:
        logger.info(
            f"User {user_id_log}: Service ID {service_id_to_add} was already selected."
        )
        if query:
            await query.answer("Эта услуга уже была добавлена.")

    service_processing_queue: List[Dict[str, Any]] = state_context.get(
        "service_processing_queue", []
    )
    if (
        service_processing_queue
        and service_processing_queue[0].get("service_id") == service_id_to_add
    ):
        processed_service = service_processing_queue.pop(0)
        logger.debug(
            f"User {user_id_log}: Removed '{processed_service.get('display_name')}' from processing queue (added directly)."
        )
    state_context["service_processing_queue"] = service_processing_queue

    state_context.pop("current_category_being_detailed_id", None)
    state_context.pop("current_category_selections", None)
    state_context.pop("processed_for_auto_detail", None)  # Сбрасываем флаг

    return {"next_state_for_yaml": "REG_MASTER_SHOW_SERVICE_SUGGESTIONS"}


# === END BLOCK 13 ===

# === END BLOCK: handlers/registration_logic.py (Конец файла) ===
