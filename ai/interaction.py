# ai/interaction.py (Исправленная версия после Ruff check)

# === BLOCK 1: Imports ===
import asyncio
import logging
import typing

from openai import APIError, AsyncOpenAI, RateLimitError  # Импорт OpenAI
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

# Импорт конфигурации и моделей БД
import config
from database.models import (
    AsyncSessionLocal,
    Instructions,
)

# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
# === END BLOCK 2 ===


# === BLOCK 3: AI Client Initialization ===
# --- Инициализация AI клиентов ---
openai_client: typing.Optional[AsyncOpenAI] = None
if config.OPENAI_API_KEY and config.OPENAI_API_KEY not in [
    "ВАШ_OPENAI_КЛЮЧ_СЮДА",
    "sk-...",
    "ЗАМЕНЕННЫЙ КЛЮЧ OPEN AI",
]:  # Добавил ваш плейсхолдер
    try:
        # Используем AsyncOpenAI для асинхронной работы
        openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        logger.info("Асинхронный клиент OpenAI инициализирован.")
    except Exception as e:
        logger.error(f"Ошибка инициализации клиента OpenAI: {e}")
else:
    # Строка лога разбита для E501
    logger.warning(
        "OPENAI_API_KEY не найден, не изменен или содержит плейсхолдер. "
        "Функциональность OpenAI недоступна."
    )

# TODO: Добавить инициализацию клиентов Gemini / Vertex AI по аналогии,
# когда понадобятся (Комментарий разбит для E501)
gemini_client = None  # Пример заглушки
vertex_client = None  # Пример заглушки
# === END BLOCK 3 ===


# === BLOCK 4: _get_instruction_text Helper Function ===
# --- Вспомогательная функция для получения инструкции из БД ---
async def _get_instruction_text(
    session: AsyncSession,
    instruction_key: str,
    user_lang_code: typing.Optional[str] = None,
) -> typing.Optional[str]:
    """
    Извлекает текст инструкции из БД по ключу с учетом fallback логики.
    Fallback порядок: user_lang_code -> 'en' -> 'uk' -> 'ru'.
    """
    # Определяем порядок языков для поиска
    # Можно вынести ['en', 'uk', 'ru'] в config.py как DEFAULT_FALLBACK_LANGS
    fallback_order = (
        config.DEFAULT_FALLBACK_LANGS
        if hasattr(config, "DEFAULT_FALLBACK_LANGS")
        else ["en", "uk", "ru"]
    )
    codes_to_try = []
    if (
        user_lang_code and user_lang_code.lower() in fallback_order
    ):  # Проверяем, поддерживается ли язык
        codes_to_try.append(user_lang_code.lower())
    # Добавляем остальные языки из fallback_order, если их еще нет
    for code in fallback_order:
        if code not in codes_to_try:
            codes_to_try.append(code)

    logger.debug(
        f"Поиск инструкции '{instruction_key}' в порядке языков: {codes_to_try}"
    )

    try:
        for lang_code in codes_to_try:
            column_name = f"text_{lang_code}"
            # Проверяем, есть ли такая колонка в модели Instructions
            if hasattr(Instructions, column_name):
                column_to_select = getattr(Instructions, column_name)
                # Выбираем только нужную колонку по ключу
                stmt = (
                    select(column_to_select)
                    .where(Instructions.key == instruction_key)
                    .limit(1)
                )
                result = await session.execute(stmt)
                instruction_text = result.scalar_one_or_none()

                # Если текст найден и он не пустой после удаления пробелов
                if instruction_text and instruction_text.strip():
                    # Строка f-string разбита для E501
                    logger.debug(
                        f"Найдена инструкция '{instruction_key}' "
                        f"на языке '{lang_code}'."
                    )
                    return instruction_text.strip()
            else:
                # Логируем только если это язык пользователя,
                # иначе это ожидаемо для fallback (Комментарий разбит для E501)
                if user_lang_code and lang_code == user_lang_code.lower():
                    # Строка f-string разбита для E501
                    logger.warning(
                        f"Колонка {column_name} не найдена в модели "
                        f"Instructions, пропуск '{lang_code}'."
                    )

        # Если прошли по всем языкам и ничего не нашли
        # Строка f-string разбита для E501
        logger.warning(
            f"Инструкция '{instruction_key}' не найдена ни на одном "
            f"из языков: {codes_to_try}"
        )
        return None
    except SQLAlchemyError as e:
        logger.error(
            f"Ошибка SQLAlchemy при получении инструкции '{instruction_key}': {e}",
            exc_info=True,
        )
        return None
    except Exception as e:
        logger.error(
            f"Неожиданная ошибка при получении инструкции '{instruction_key}': {e}",
            exc_info=True,
        )
        return None


# === END BLOCK 4 ===


# === BLOCK 5: generate_text_response Function (Обновленная) ===
# --- Основная функция взаимодействия с AI (обновленная) ---
async def generate_text_response(
    # Аннотации типов исправлены для UP006
    messages: list[dict[str, str]],
    instruction_key: typing.Optional[str] = None,
    user_lang_code: typing.Optional[str] = None,
    model: typing.Optional[str] = None,
    fallback_system_message: typing.Optional[str] = None,
    session: typing.Optional[AsyncSession] = None,
    system_prompt_override: typing.Optional[str] = None,  # Для прямой передачи промпта
    user_reply_for_format: typing.Optional[
        str
    ] = None,  # Для подстановки в промпт из БД
) -> typing.Optional[str]:
    """
    Генерирует текстовый ответ от AI.
    Приоритет системного промпта:
    1. system_prompt_override (если передан)
    2. Форматированная инструкция из БД (если переданы instruction_key
       и user_reply_for_format)
    3. Обычная инструкция из БД (если передан instruction_key)
    4. fallback_system_message
    """
    provider = config.ACTIVE_AI_PROVIDER
    final_system_prompt: typing.Optional[str] = None
    session_provided_or_global_exists = (
        session is not None or AsyncSessionLocal is not None
    )

    # --- Определение системного промпта ---
    if system_prompt_override:
        # 1. Используем промпт, переданный напрямую
        final_system_prompt = system_prompt_override
        logger.debug("Использован system_prompt_override.")
    elif instruction_key and session_provided_or_global_exists:
        # 2 & 3. Пытаемся получить промпт из БД по ключу
        logger.debug(
            f"Попытка получить/форматировать инструкцию '{instruction_key}'..."
        )
        fetched_instruction_text: typing.Optional[str] = None
        try:
            current_session: typing.Optional[AsyncSession] = session
            if not current_session and AsyncSessionLocal:
                async with AsyncSessionLocal() as new_session:  # Создаем сессию
                    fetched_instruction_text = await _get_instruction_text(
                        new_session, instruction_key, user_lang_code
                    )
            elif current_session:  # Используем переданную сессию
                fetched_instruction_text = await _get_instruction_text(
                    current_session, instruction_key, user_lang_code
                )
            else:
                logger.error(
                    "Логическая ошибка: Сессия недоступна для получения инструкции."
                )

            # Обрабатываем полученный текст
            if fetched_instruction_text:
                if user_reply_for_format:  # 2. Если нужно форматировать
                    # Расширенное логирование для отладки форматирования
                    logger.info(
                        f"AI_INTERACTION_DEBUG: About to format. Type of fetched_instruction_text: {type(fetched_instruction_text)}"
                    )
                    logger.info(
                        f"AI_INTERACTION_DEBUG: Fetched instruction text (raw, len {len(fetched_instruction_text)}):\n'''{fetched_instruction_text}'''"
                    )
                    # Используем repr() для выявления скрытых/специальных символов
                    logger.info(
                        f"AI_INTERACTION_DEBUG: Representation of fetched_instruction_text:\n{repr(fetched_instruction_text)}"
                    )
                    logger.info(
                        f"AI_INTERACTION_DEBUG: Type of user_reply_for_format: {type(user_reply_for_format)}"
                    )
                    logger.info(
                        f"AI_INTERACTION_DEBUG: Value for user_reply_for_format: '{user_reply_for_format}'"
                    )
                    logger.info(
                        f"AI_INTERACTION_DEBUG: Representation of user_reply_for_format:\n{repr(user_reply_for_format)}"
                    )

                    placeholder_name_to_check = (
                        "user_reply"  # Имя ключа, которое мы ожидаем
                    )
                    is_placeholder_present_immediately_before_format = (
                        f"{{{placeholder_name_to_check}}}" in fetched_instruction_text
                    )
                    logger.info(
                        f"AI_INTERACTION_DEBUG: Is '{{{placeholder_name_to_check}}}' present in fetched_instruction_text immediately before .format()? {is_placeholder_present_immediately_before_format}"
                    )

                    try:
                        # Попытка форматирования с явным указанием ключа как в словаре
                        final_system_prompt = fetched_instruction_text.format(
                            **{placeholder_name_to_check: user_reply_for_format}
                        )
                        logger.info(
                            "Использована ФОРМАТИРОВАННАЯ инструкция "
                            f"'{instruction_key}'."
                        )
                        logger.info(
                            f"AI_INTERACTION_DEBUG: Successfully formatted prompt:\n'''{final_system_prompt}'''"
                        )
                    except KeyError as e_key:
                        logger.error(
                            f"Ошибка форматирования инструкции '{instruction_key}': "
                            f"плейсхолдер {{user_reply}} не найден? (KeyError: {e_key}) "
                            "Использую неформатированный текст."
                        )
                        logger.error(
                            f"AI_INTERACTION_DEBUG: KeyError during format: {e_key}. Available keys in fetched_instruction_text might be different or placeholder name is subtly wrong.",
                            exc_info=True,
                        )
                        final_system_prompt = fetched_instruction_text
                    except Exception as fmt_e:
                        logger.error(
                            "Неизвестная ошибка форматирования инструкции "
                            f"'{instruction_key}': {fmt_e}"
                        )
                        logger.error(
                            f"AI_INTERACTION_DEBUG: Other error during format: {fmt_e}",
                            exc_info=True,
                        )
                        final_system_prompt = fetched_instruction_text
                else:  # 3. Используем текст инструкции напрямую (user_reply_for_format не передан)
                    final_system_prompt = fetched_instruction_text
                    logger.info(
                        f"Использована инструкция '{instruction_key}' из БД (без форматирования user_reply)."
                    )  # Уточнено сообщение
            else:
                # Инструкция не найдена в БД
                logger.warning(
                    f"Инструкция '{instruction_key}' не найдена в БД. "
                    "Используем fallback."
                )
                final_system_prompt = fallback_system_message
        except Exception as e:
            logger.error(
                "Ошибка при получении/форматировании инструкции "
                f"'{instruction_key}': {e}",
                exc_info=True,
            )
            final_system_prompt = fallback_system_message
    else:
        # Если ключ не передан или сессия недоступна
        if instruction_key and not session_provided_or_global_exists:
            logger.error(
                f"instruction_key '{instruction_key}' передан, "
                "но нет сессии для его загрузки."
            )
        final_system_prompt = fallback_system_message
        if final_system_prompt:
            logger.debug("Использован fallback_system_message.")
        else:
            logger.debug("Системный промпт не используется.")
    # --- Конец определения системного промпта ---

    # --- Формирование финального списка сообщений для AI ---
    final_messages = []
    if final_system_prompt:
        final_messages.append({"role": "system", "content": final_system_prompt})
    final_messages.extend(messages)
    # --- Конец формирования списка ---

    # --- Предпросмотр для лога ---
    system_preview = (
        f"System: {str(final_system_prompt)[:70]}... "
        if final_system_prompt
        else "System: None "
    )
    try:
        history_preview_list = [
            f"{m.get('role', 'unk')[:1]}:{m.get('content', '')[:30]}..."
            for m in messages[-min(len(messages), 2) :]
        ]
        history_preview_str = (
            ", ".join(history_preview_list) if history_preview_list else "empty"
        )
    except Exception:
        history_preview_str = "[ошибка предпросмотра истории]"
    logger.debug(
        f"Запрос к AI ({provider}): {system_preview}History: [{history_preview_str}]"
    )
    # --- Конец предпросмотра ---

    # --- Вызов AI провайдера ---
    if provider == "openai":
        if not openai_client:
            logger.error("OpenAI клиент не инициализирован.")
            return None
        try:
            model_to_use = model if model else config.DEFAULT_OPENAI_MODEL
            logger.debug(f"Вызов OpenAI model='{model_to_use}'...")
            response = await openai_client.chat.completions.create(
                model=model_to_use, messages=final_messages
            )
            if (
                response.choices
                and response.choices[0].message
                and response.choices[0].message.content
            ):
                ai_response = response.choices[0].message.content.strip()
                logger.debug(f"Ответ OpenAI: '{ai_response[:100]}...'")
                return ai_response
            else:
                logger.error("Ответ OpenAI не содержит ожидаемых данных.")
                return None
        except RateLimitError:
            logger.error("Ошибка OpenAI: Превышен лимит запросов.")
            return "Извините, сервис перегружен. Попробуйте позже."
        except APIError as e:
            logger.error(
                f"Ошибка API OpenAI: status_code={e.status_code}, message={e.message}"
            )
            return "Произошла ошибка при обращении к AI."
        except Exception as e:
            logger.error(f"Неожиданная ошибка при вызове OpenAI: {e}", exc_info=True)
            return "Произошла внутренняя ошибка AI."

    # --- Заглушки для других провайдеров ---
    elif provider == "gemini":
        logger.warning("Вызов Gemini API еще не реализован.")
        await asyncio.sleep(0.1)
        last_user_msg = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "Нет сообщения",
        )
        return (
            f"[ЗАГЛУШКА GEMINI] Промпт: {str(final_system_prompt)[:50]}..., "
            f"Посл. польз.: {last_user_msg}"
        )
    elif provider == "vertexai":
        logger.warning("Вызов Vertex AI еще не реализован.")
        await asyncio.sleep(0.1)
        last_user_msg = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "Нет сообщения",
        )
        return (
            f"[ЗАГЛУШКА VERTEXAI] Промпт: {str(final_system_prompt)[:50]}..., "
            f"Посл. польз.: {last_user_msg}"
        )
    else:
        logger.error(f"Неизвестный AI провайдер: {provider}")
        return None


# === END BLOCK 5 ===
