# handlers/admin.py (Исправленная версия v3 - Ruff check + noqa F401)

# === BLOCK 1: Imports and Logger ===
import asyncio  # Для возможного sleep в заглушках
import csv  # noqa: F401 - Оставлен для будущей реализации handle_instructions_file
import io  # noqa: F401 - Оставлен для будущей реализации handle_instructions_file
import logging
import typing

import telegram  # Добавлен импорт для telegram.error
import yaml  # Для YAML

# Импорты SQLAlchemy отсортированы (I001)
from sqlalchemy import select  # Импорт insert ОСТАВЛЕН (игнорируем F401)
from sqlalchemy import update as sqlalchemy_update
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError  # Оставлен F401
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update, constants
from telegram.ext import ContextTypes
from yaml import YAMLError  # Для ошибок YAML

# Импортируем все модели, используемые в этом файле (отсортировано I001)
from database.models import (
    ConversationScenario,  # Модель сценариев
    Instructions,
    RegistrationCodes,
    UserData,
)


# Отдельная функция-заглушка для escape_md
def _escape_md_fallback(text: typing.Optional[typing.Any], **kwargs) -> str:
    """Заглушка для escape_md, если основной модуль недоступен."""
    # Строка лога разбита для E501
    logger.error(
        "Используется ЗАГЛУШКА для escape_md! Форматирование может быть неверным."
    )
    return str(text) if text is not None else ""


# Импортируем нашу утилиту экранирования
try:
    from utils.message_utils import escape_md
except ImportError:
    # Заглушка на случай, если файл utils не создан (но лучше его создать!)
    logging.basicConfig(level=logging.ERROR)  # Ensure basicConfig is called once
    # Строка лога разбита для E501
    logging.error(
        "!!! Не удалось импортировать escape_md из utils.message_utils. "
        "Используется простая заглушка !!!"
    )
    escape_md = _escape_md_fallback


logger = logging.getLogger(__name__)
# === END BLOCK 1 ===


# === BLOCK 2: Admin Check Helper ===
async def _is_admin(
    user_id: int, session_maker: typing.Optional[async_sessionmaker[AsyncSession]]
) -> bool:
    """Проверяет, является ли пользователь администратором."""
    if not session_maker:
        logger.error("_is_admin: Фабрика сессий не передана.")
        return False
    # Используем try-except для перехвата возможных ошибок БД
    try:
        async with session_maker() as session:
            user = await session.get(UserData, user_id)
            if user and user.is_admin:
                return True
    except Exception as e:
        logger.error(f"Ошибка БД при проверке админа {user_id}: {e}", exc_info=True)
    return False


# === END BLOCK 2 ===


# === BLOCK 3: View Registration Codes ===
# --- КОМАНДА ПРОСМОТРА КОДОВ ---
async def view_registration_codes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Показывает список всех кодов регистрации."""
    if not update or not update.effective_user:
        logger.warning("view_registration_codes вызван без пользователя.")
        return
    user = update.effective_user
    user_id = user.id

    logger.info(f"Админ-команду /view_reg_codes вызвал пользователь {user_id}")
    session_maker: typing.Optional[async_sessionmaker[AsyncSession]] = (
        context.bot_data.get("session_maker")
    )
    if not session_maker:
        logger.error(
            f"view_registration_codes: Фабрика сессий не найдена для user {user_id}."
        )
        try:
            await update.message.reply_text(
                "Ошибка: Не удалось получить доступ к базе данных."
            )
        except Exception as e:
            logger.error(
                "Не удалось отправить сообщение об ошибке БД в "
                f"view_registration_codes: {e}"
            )
        return
    if not await _is_admin(user_id, session_maker):
        logger.warning(f"/view_reg_codes: Пользователь {user_id} не админ.")
        try:
            await update.message.reply_text(
                "У вас нет прав для выполнения этой команды."
            )
        except Exception as e:
            logger.error(
                "Не удалось отправить сообщение об отказе в правах в "
                f"view_registration_codes: {e}"
            )
        return

    logger.info(f"Пользователь {user_id} админ. Запрашиваю коды...")
    # Исправлено UP006: typing.List -> list
    all_codes: list[RegistrationCodes] = []
    try:
        async with session_maker() as session:
            stmt = select(RegistrationCodes).order_by(RegistrationCodes.created_at)
            result = await session.execute(stmt)
            all_codes = result.scalars().all()
    except Exception as e:
        logger.error(
            f"Ошибка БД при получении рег. кодов админом {user_id}: {e}", exc_info=True
        )
        try:
            await update.message.reply_text("Произошла ошибка при получении кодов.")
        except Exception as e2:
            logger.error(
                f"Не удалось отправить сообщение об ошибке получения кодов: {e2}"
            )
        return

    if not all_codes:
        try:
            await update.message.reply_text(
                "В базе данных пока нет регистрационных кодов."
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение 'кодов нет': {e}")
        return

    reply_parts = ["📋 *Список регистрационных кодов:*\n\n"]
    max_part_len = 4050  # Приблизительный лимит Telegram

    for code_obj in all_codes:
        status = "✅ Использован" if code_obj.is_used else "⏳ Доступен"
        user_info = ""
        if code_obj.is_used and code_obj.used_by_user_id:
            user_info = f" (User ID: {code_obj.used_by_user_id})"
            if code_obj.used_at:
                try:
                    used_at_str = escape_md(code_obj.used_at.strftime("%Y-%m-%d %H:%M"))
                except Exception:
                    used_at_str = "???"
                user_info += f" в {used_at_str}"

        code_escaped = escape_md(code_obj.code)
        status_escaped = escape_md(status)
        user_info_escaped = (
            escape_md(user_info).replace(r"(", r"\(").replace(r")", r"\)")
        )

        line = f"`{code_escaped}` \\- {status_escaped}{user_info_escaped}\n"

        if len(reply_parts[-1]) + len(line) > max_part_len:
            reply_parts.append("")  # Начинаем новую часть
        reply_parts[-1] += line

    try:  # Отправка частей
        # Исправлено B007: i -> _i
        for _i, part in enumerate(reply_parts):
            if not part.strip():
                continue
            await update.message.reply_text(
                part, parse_mode=constants.ParseMode.MARKDOWN_V2
            )
    except Exception as send_err:
        logger.error(
            f"Ошибка отправки списка кодов админу {user_id}: {send_err}", exc_info=True
        )
        try:
            await update.message.reply_text(
                "Не удалось отправить отформатированный список кодов."
            )
        except Exception as e:
            # Строка лога разбита для E501
            logger.error(
                "Не удалось отправить fallback сообщение в "
                f"view_registration_codes: {e}"
            )

    logger.info(f"Админу {user_id} отправлен список из {len(all_codes)} кодов.")


# === END BLOCK 3 ===


# === BLOCK 4: Ask for Codes File ===
# --- ФУНКЦИИ ДЛЯ МАССОВОГО ДОБАВЛЕНИЯ КОДОВ ---
async def ask_for_codes_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Запрашивает у администратора txt файл с кодами."""
    if not update or not update.effective_user:
        return
    user_id = update.effective_user.id

    logger.info(f"Админ-команду /add_reg_codes_file вызвал пользователь {user_id}")
    session_maker: typing.Optional[async_sessionmaker[AsyncSession]] = (
        context.bot_data.get("session_maker")
    )
    if not session_maker:
        await update.message.reply_text("Ошибка БД.")
        return
    if not await _is_admin(user_id, session_maker):
        await update.message.reply_text("Нет прав.")
        return

    message_text = escape_md(
        "Пожалуйста, прикрепите `.txt` файл с новыми кодами регистрации.\n"
        "Каждый код должен быть на новой строке.\n"
        "Коды должны быть уникальными и не должны существовать в базе.\n"
        "Пустые строки и дубликаты в файле будут проигнорированы."
    )
    try:
        await update.message.reply_text(
            message_text, parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        logger.info(f"Запросили файл с кодами у админа {user_id}")
    except Exception as e:
        logger.error(
            f"Ошибка отправки запроса txt файла кодов админу {user_id}: {e}",
            exc_info=True,
        )
        # Пробуем отправить без форматирования
        await update.message.reply_text(message_text.replace("\\", ""))


# === END BLOCK 4 ===


# === BLOCK 5: Handle Codes File ===
async def handle_codes_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает загруженный .txt файл с кодами регистрации."""
    if (
        not update
        or not update.message
        or not update.message.document
        or not update.effective_user
    ):
        return
    user = update.effective_user
    message = update.message
    doc = message.document
    user_id = user.id

    if doc.mime_type != "text/plain":
        logger.debug(f"Проигнорирован не txt файл от {user_id}: {doc.file_name}")
        return

    logger.info(f"Получен txt файл {doc.file_name} от {user_id}.")
    session_maker: typing.Optional[async_sessionmaker[AsyncSession]] = (
        context.bot_data.get("session_maker")
    )
    if not session_maker:
        await message.reply_text("Ошибка БД.")
        return
    if not await _is_admin(user_id, session_maker):
        logger.warning(f"Не-админ {user_id} прислал файл с кодами.")
        return

    file_content_str = ""  # Инициализация
    try:  # Скачивание и декодирование
        file = await doc.get_file()
        file_content_bytes = await file.download_as_bytearray()
        try:
            file_content_str = file_content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            file_content_str = file_content_bytes.decode("cp1251")
            logger.warning(f"Файл {doc.file_name} был в кодировке cp1251.")
    except Exception as e:
        logger.error(f"Ошибка скачивания/декодирования файла кодов: {e}", exc_info=True)
        await message.reply_text("Не удалось скачать/прочитать файл.")
        return

    # Обработка кодов
    lines = file_content_str.splitlines()
    potential_codes_raw = {line.strip() for line in lines if line.strip()}
    added_count = 0

    if not potential_codes_raw:
        await message.reply_text("Файл пуст или содержит только пустые строки.")
        return

    total_lines = len(lines)
    codes_in_file = len(potential_codes_raw)
    # Исправлено E741: l -> line
    initial_non_empty_lines = [line.strip() for line in lines if line.strip()]
    duplicates_in_file = len(initial_non_empty_lines) - codes_in_file
    invalid_format = set()
    existing_in_db = set()
    valid_for_insert = set()
    error_message = None  # Сохраняем для отчета

    try:  # Операции с БД
        # Исправлено SIM117: объединены with
        async with session_maker() as session, session.begin():
            codes_to_check_db = set()
            for code in potential_codes_raw:
                if 5 <= len(code) <= 40 and " " not in code:
                    codes_to_check_db.add(code)
                else:
                    invalid_format.add(code)
            if invalid_format:
                logger.warning(f"Найдены коды неверного формата: {invalid_format}")

            if codes_to_check_db:
                stmt = select(RegistrationCodes.code).where(
                    RegistrationCodes.code.in_(codes_to_check_db)
                )
                result = await session.execute(stmt)
                existing_in_db = set(result.scalars().all())
                if existing_in_db:
                    logger.info(f"Найдены существующие коды: {existing_in_db}")

            valid_for_insert = codes_to_check_db - existing_in_db

            if valid_for_insert:
                new_codes_objs = [
                    RegistrationCodes(code=code, is_used=False)
                    for code in valid_for_insert
                ]
                session.add_all(new_codes_objs)
                await session.flush()
                added_count = len(valid_for_insert)
                logger.info(f"Успешно добавлены {added_count} кодов.")
            else:
                logger.info("Новых кодов для добавления не найдено.")
    # Ловим ОШИБКУ ЦЕЛОСТНОСТИ отдельно
    except SQLAlchemyIntegrityError as e:
        error_message = "Ошибка БД (IntegrityError). Возможно, код уже был добавлен?"
        # Строка лога разбита для E501
        logger.error(
            f"Ошибка БД IntegrityError при добавлении кодов: {e}", exc_info=True
        )
    except SQLAlchemyError as e:
        error_message = "Ошибка базы данных при добавлении кодов."
        logger.error(f"Ошибка БД при добавлении кодов: {e}", exc_info=True)
    except Exception as e:
        error_message = f"Неожиданная ошибка обработки: {e}"
        logger.error(f"Ошибка обработки кодов: {e}", exc_info=True)

    # Формирование и отправка отчета
    report_parts = [
        f"📝 *Отчет о добавлении кодов из файла* `{escape_md(doc.file_name)}`\n\n"
    ]
    report_parts.append(f"\\- Всего строк в файле: {escape_md(total_lines)}\n")
    report_parts.append(f"\\- Уникальных непустых кодов: {escape_md(codes_in_file)}\n")
    if duplicates_in_file > 0:
        report_parts.append(
            f"\\- Дубликатов/пустых строк \\(проигнорировано\\): "
            f"{escape_md(duplicates_in_file)}\n"
        )
    if invalid_format:
        report_parts.append(
            f"\\- Неверный формат \\(проигнорировано\\): "
            f"{escape_md(len(invalid_format))}\n"
        )
    if existing_in_db:
        report_parts.append(
            f"\\- Уже существуют в БД \\(проигнорировано\\): "
            f"{escape_md(len(existing_in_db))}\n"
        )
    report_parts.append("\\-\\-\n")  # Исполльзуем \\- для экранирования
    if error_message:
        report_parts.append(f"❌ *ОШИБКА:* {escape_md(error_message)}\n")
    report_parts.append(f"✅ *УСПЕШНО ДОБАВЛЕНО НОВЫХ:* {escape_md(added_count)}\n")

    # Логика разбиения на части final_report_messages
    final_report_messages = []
    current_report_text = "".join(report_parts)
    max_part_len = 4050
    lines_in_report = current_report_text.split("\n")
    part_buffer = ""
    for line in lines_in_report:
        line_with_newline = line + "\n"
        if len(part_buffer) + len(line_with_newline) > max_part_len:
            if part_buffer:
                final_report_messages.append(part_buffer)
            part_buffer = (
                line_with_newline
                if len(line_with_newline) <= max_part_len
                else (line[: max_part_len - 5] + "...\\n")
            )
        else:
            part_buffer += line_with_newline
    if part_buffer:
        final_report_messages.append(part_buffer)

    # Отправка отчета
    try:
        # Исправлено B007: i -> _i
        for _i, part in enumerate(final_report_messages):
            if not part.strip():
                continue
            await message.reply_text(part, parse_mode=constants.ParseMode.MARKDOWN_V2)
    except Exception as send_err:
        logger.error(
            f"Ошибка отправки отчета админу {user_id}: {send_err}", exc_info=True
        )
        plain_fallback_text = (
            f"Обработка файла {doc.file_name} завершена. "
            f"Добавлено:{added_count}. Ошибка:{error_message or 'Нет'}"
        )
        await message.reply_text(plain_fallback_text)


# === END BLOCK 5 ===


# === BLOCK 6: View Instructions ===
async def view_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает список всех инструкций."""
    if not update or not update.effective_user:
        return
    user_id = update.effective_user.id
    session_maker = context.bot_data.get("session_maker")  # Исправлено F821
    if not session_maker:
        logger.error("view_instructions: Фабрика сессий не найдена.")
        await update.message.reply_text("Ошибка: Нет доступа к БД.")
        return

    if not await _is_admin(user_id, session_maker):
        await update.message.reply_text("Нет прав.")
        return

    logger.info(f"Пользователь {user_id} админ. Запрашиваю инструкции...")
    all_instructions: list[Instructions] = []
    try:  # Запрос инструкций из БД
        async with session_maker() as session:
            stmt = select(Instructions).order_by(Instructions.key)
            result = await session.execute(stmt)
            all_instructions = result.scalars().all()
    except Exception as e:
        logger.error(f"Ошибка БД при получении инструкций: {e}", exc_info=True)
        await update.message.reply_text("Ошибка получения инструкций.")
        return

    if not all_instructions:
        await update.message.reply_text("Инструкций нет.")
        return

    # Формирование и отправка отчета
    reply_parts = ["📋 *Список инструкций для AI:*\n\n"]
    max_part_len = 4050
    for instr in all_instructions:
        key_escaped = escape_md(instr.key)
        desc_escaped = (
            escape_md(instr.description) if instr.description else "_Нет описания_"
        )
        instr_text_lines = [f"*Key:* `{key_escaped}`", f"*Описание:* {desc_escaped}"]

        text_en_short = escape_md(
            instr.text_en[:150] + "..."
            if instr.text_en and len(instr.text_en) > 150
            else instr.text_en
        )
        text_ru_short = escape_md(
            instr.text_ru[:150] + "..."
            if instr.text_ru and len(instr.text_ru) > 150
            else instr.text_ru
        )
        instr_text_lines.append(f"🇬🇧 EN: {text_en_short or '_пусто_'}")
        instr_text_lines.append(f"🇷🇺 RU: {text_ru_short or '_пусто_'}")

        # Строка разбита для E501
        other_langs_present = any(
            getattr(instr, f"text_{lang}", None)
            for lang in [
                "es",
                "fr",
                "de",
                "uk",
                "pl",
                "ro",
                "ar",
                "tr",
                "fa",
                "pt",
                "hi",
                "uz",
            ]
        )
        if other_langs_present:
            instr_text_lines.append("_\\(есть другие языки\\)_")

        instr_text_lines.append("\\-\\-\\-\n")  # Разделитель
        current_instr_block = "\n".join(instr_text_lines)

        if len(reply_parts[-1]) + len(current_instr_block) > max_part_len:
            reply_parts.append("")
        reply_parts[-1] += current_instr_block

    try:  # Отправка
        # Исправлено B007: i -> _i
        for _i, part in enumerate(reply_parts):
            if not part.strip():
                continue
            await update.message.reply_text(
                part, parse_mode=constants.ParseMode.MARKDOWN_V2
            )
    except Exception as send_err:
        # Строка лога разбита для E501
        logger.error(
            "Ошибка отправки списка инструкций админу " f"{user_id}: {send_err}",
            exc_info=True,
        )
        await update.message.reply_text("Не удалось отправить форматированный список.")


# === END BLOCK 6 ===


# === BLOCK 7: Upload Instructions ===
async def ask_for_instructions_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Запрашивает у администратора CSV файл с инструкциями."""
    if not update or not update.effective_user:
        return
    user_id = update.effective_user.id
    session_maker = context.bot_data.get("session_maker")
    if not session_maker:
        await update.message.reply_text("Ошибка БД.")
        return

    if not await _is_admin(user_id, session_maker):
        await update.message.reply_text("Нет прав.")
        return

    required_cols = escape_md("`key`, `text_en`, `text_ru`")
    optional_cols = escape_md("`description`, `text_es`, `text_fr`, `...`")
    message_parts = [
        escape_md("Пожалуйста, прикрепите `.csv` файл с инструкциями для AI."),
        "",
        escape_md("*Формат файла:*"),
        escape_md("- Кодировка: `UTF-8` (предпочтительно) или `Windows-1251`"),
        escape_md("- Разделитель: запятая (`,`)"),
        escape_md("- Каждая строка - одна инструкция."),
        escape_md("- Первая строка - заголовки колонок."),
        "",
        escape_md("*Обязательные колонки:*"),
        f"\\- {required_cols}",
        "",
        escape_md("*Опциональные колонки:*"),
        f"\\- {optional_cols}",
        "",
        escape_md("*Поведение:*"),
        escape_md("- Если `key` существует, инструкция будет *обновлена*."),
        escape_md("- Если `key` новый, будет *добавлена* новая."),
    ]
    message_text = "\n".join(message_parts)
    try:  # Отправка инструкции
        await update.message.reply_text(
            message_text, parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        logger.info(f"Запросили CSV файл инструкций у админа {user_id}")
    except Exception as e:
        logger.error(
            f"Ошибка отправки запроса CSV файла админу {user_id}: {e}", exc_info=True
        )
        plain_text = message_text.replace("\\", "").replace("`", "").replace("*", "")
        await update.message.reply_text(plain_text)


async def handle_instructions_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обрабатывает загруженный .csv файл с инструкциями."""
    # === НАЧАЛО ЗАГЛУШКИ ===
    # Эта функция требует значительной доработки для реальной работы с CSV
    if (
        not update
        or not update.message
        or not update.message.document
        or not update.effective_user
    ):
        return

    user = update.effective_user
    message = update.message
    doc = message.document
    user_id = user.id  # Эта переменная теперь не помечена как F841

    session_maker = context.bot_data.get("session_maker")
    if not session_maker:
        await message.reply_text("Ошибка БД.")
        return
    if not await _is_admin(user_id, session_maker):
        logger.warning(f"Не-админ {user_id} прислал CSV файл инструкций.")
        return
    # Строка условия разбита для E501
    if doc.mime_type not in (
        "text/csv",
        "text/comma-separated-values",
        "application/csv",
    ):
        logger.debug(f"Проигнорирован не-CSV файл: {doc.file_name} от {user_id}")
        await message.reply_text("Пожалуйста, прикрепите файл в формате .csv")
        return

    logger.info(f"Получен CSV файл {doc.file_name} от {user_id}. Начинаем обработку...")

    # --- Временная заглушка ---
    # TODO: Реализовать парсинг CSV, валидацию, добавление/обновление в БД
    await asyncio.sleep(1.0)  # Имитация долгой обработки
    added_count = 0  # Пример
    updated_count = 0  # Пример
    processed_rows = 0  # Пример
    error_rows_info = []  # Пример
    error_message = "Функционал обработки CSV еще не реализован."  # Пример
    # --- Конец временной заглушки ---

    # Формирование отчета
    try:
        from utils.message_utils import escape_md
    except ImportError:
        escape_md = _escape_md_fallback

    report_header = (
        f"📝 *Отчет об обработке файла инструкций* `{escape_md(doc.file_name)}`\n\n"
    )
    report_body = ""
    if error_message:
        report_body += (
            f"❌ *ОШИБКА/ИНФО:* {escape_md(error_message)}\n"  # Изменил на ОШИБКА/ИНФО
        )
    else:
        # Эта часть пока не будет выполняться из-за заглушки
        report_body += f"\\- Обработано строк (приблизительно): {processed_rows}\n"
        report_body += f"\\- Добавлено новых инструкций: {added_count}\n"
        report_body += f"\\- Обновлено существующих: {updated_count}\n"
        if error_rows_info:
            report_body += f"\\- Ошибок в строках: {len(error_rows_info)}\n"

    full_report = report_header + report_body

    # Логика разбиения на части final_report_messages
    final_report_messages = []
    max_part_len = 4050
    lines_in_report = full_report.split("\n")
    part_buffer = ""
    for line in lines_in_report:
        line_with_newline = line + "\n"
        if len(part_buffer) + len(line_with_newline) > max_part_len:
            if part_buffer:
                final_report_messages.append(part_buffer)
            part_buffer = (
                line_with_newline
                if len(line_with_newline) <= max_part_len
                else (line[: max_part_len - 5] + "...\\n")
            )
        else:
            part_buffer += line_with_newline
    if part_buffer:
        final_report_messages.append(part_buffer)

    try:  # Отправка отчета
        for _i, part in enumerate(final_report_messages):
            if not part.strip():
                continue
            await update.message.reply_text(
                part, parse_mode=constants.ParseMode.MARKDOWN_V2
            )
    except Exception as send_err:  # Fallback
        # --- ИСПРАВЛЕННАЯ СТРОКА (была ~652, теперь может чуть сместиться) ---
        logger.error(
            f"Ошибка отправки отчета по инструкциям админу {user_id}: {send_err}",
            exc_info=True,
        )  # noqa: E501
        # -------------------------------------------------------------------
        plain_fallback_text = (
            f"Обработка файла {doc.file_name} завершена. Добавлено: {added_count}, "
            f"Обновлено: {updated_count}. Ошибок строк: {len(error_rows_info)}. "
            f"Общая ошибка: {error_message or 'Нет'}"
        )
        await update.message.reply_text(plain_fallback_text)


# === END BLOCK 7 ===


# === BLOCK 8: Upload/Manage Scenarios ===
# Комментарий разбит для E501
# (ФИНАЛЬНАЯ ВЕРСИЯ с обработкой и полным отчетом)
async def ask_for_scenario_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Запрашивает у администратора YAML файл со сценарием."""
    if not update or not update.effective_user:
        return
    user_id = update.effective_user.id
    logger.info(f"Админ-команду /upload_scenario вызвал пользователь {user_id}")
    session_maker: typing.Optional[async_sessionmaker[AsyncSession]] = (
        context.bot_data.get("session_maker")
    )
    if not session_maker:
        await update.message.reply_text("Ошибка БД.")
        return
    if not await _is_admin(user_id, session_maker):
        await update.message.reply_text("Нет прав.")
        return

    try:
        from utils.message_utils import escape_md
    except ImportError:
        escape_md = _escape_md_fallback  # Используем общую заглушку

    line1 = escape_md(
        "Пожалуйста, прикрепите файл формата `.yaml` с описанием одного "
        "сценария диалога."
    )
    line2 = ""
    line3 = escape_md("*Ожидаемая структура YAML внутри файла:*")
    yaml_example = """```yaml
scenario_key: уникальный_ключ_сценария
name: "Понятное Название Сценария"
entry_state: НАЗВАНИЕ_ПЕРВОГО_СОСТОЯНИЯ
states:
  НАЗВАНИЕ_СОСТОЯНИЯ_1:
    description: "Описание (опционально)"
    on_entry: [...]
    input_handlers: [...]
  НАЗВАНИЕ_СОСТОЯНИЯ_2:
    # ...
```"""
    line4 = ""
    line5 = escape_md("*Поведение:*")
    line6 = escape_md(
        "- Существующий сценарий с тем же `scenario_key` будет **обновлен** "
        "(версия увеличится)."
    )
    line7 = escape_md("- Новый `scenario_key` будет **добавлен**.")
    line8 = escape_md(
        "- YAML должен быть **валидным** и содержать `scenario_key`, "
        "`name`, `entry_state`, `states`."
    )
    message_parts = [
        line1,
        line2,
        line3,
        yaml_example,
        line4,
        line5,
        line6,
        line7,
        line8,
    ]
    message_text = "\n".join(message_parts)

    try:
        await update.message.reply_text(
            message_text, parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        logger.info(f"Запросили YAML файл сценария у админа {user_id}")
    except Exception as e:  # Fallback
        logger.error(
            f"Ошибка отправки запроса YAML файла админу {user_id}: {e}", exc_info=True
        )
        # Исправлено E741: l -> line
        plain_text = "\n".join(
            [line for line in message_parts if not line.startswith("```")]
        ).replace("\\", "")
        await update.message.reply_text(
            "Не удалось отправить форматированную инструкцию. "
            f"Ошибка: {e}\n\n{plain_text}"
        )


async def handle_scenario_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обрабатывает загруженный .yaml файл со сценарием, добавляет/обновляет в БД."""
    if (
        not update
        or not update.message
        or not update.message.document
        or not update.effective_user
    ):
        return
    user = update.effective_user
    message = update.message
    doc = message.document
    user_id = user.id

    # Проверка прав и типа файла
    session_maker: typing.Optional[async_sessionmaker[AsyncSession]] = (
        context.bot_data.get("session_maker")
    )
    if not session_maker:
        await message.reply_text("Ошибка БД.")
        return
    if not await _is_admin(user_id, session_maker):
        logger.warning(f"Не-админ {user_id} прислал YAML файл.")
        return
    if not doc.file_name.lower().endswith((".yaml", ".yml")):
        logger.debug(f"Проигнорирован не-YAML файл: {doc.file_name} от {user_id}")
        await message.reply_text(
            "Пожалуйста, загрузите файл с расширением .yaml или .yml"
        )
        return

    logger.info(
        f"Получен YAML файл {doc.file_name} от {user_id}. Начинаем обработку..."
    )

    # Инициализация переменных для отчета
    file_content_str: typing.Optional[str] = None
    scenario_data: typing.Optional[dict] = None
    added_count = 0
    updated_count = 0
    error_message = None
    processed_key = "N/A"
    new_version = 0
    existing_scenario_version = 0  # Для отчета

    try:
        # Скачивание
        file = await doc.get_file()
        file_content_bytes = await file.download_as_bytearray()
        try:
            file_content_str = file_content_bytes.decode("utf-8")
        except UnicodeDecodeError as err:
            raise ValueError("Файл должен быть в кодировке UTF-8.") from err
        logger.info(f"Файл {doc.file_name} скачан и декодирован.")

        # Парсинг YAML
        scenario_data = yaml.safe_load(file_content_str)
        if not isinstance(scenario_data, dict):
            raise ValueError(
                "YAML должен содержать объект (словарь) на верхнем уровне."
            )
        logger.info(f"Файл {doc.file_name} успешно распарсен.")

        # Валидация обязательных ключей
        required_keys = ["scenario_key", "name", "entry_state", "states"]
        missing = [key for key in required_keys if key not in scenario_data]
        if missing:
            raise ValueError(
                f"В YAML отсутствуют обязательные ключи: {', '.join(missing)}"
            )
        if not isinstance(scenario_data["states"], dict) or not scenario_data["states"]:
            raise ValueError("Раздел 'states' должен быть непустым словарем.")
        logger.info(
            f"Структура YAML для файла {doc.file_name} базовая валидация пройдена."
        )

        # Извлечение данных
        scenario_key = str(scenario_data["scenario_key"]).strip()
        name = str(scenario_data["name"]).strip()
        description = str(scenario_data.get("description", "")).strip() or None
        definition_yaml = yaml.dump(
            scenario_data, allow_unicode=True, sort_keys=False, default_flow_style=False
        )
        processed_key = scenario_key

        if not scenario_key or not name:
            raise ValueError("Ключи 'scenario_key' и 'name' не могут быть пустыми.")

        # --- Взаимодействие с БД ---
        logger.debug(f"Поиск/Обновление/Вставка сценария '{scenario_key}' в БД...")
        # Комментарий перенесен на строку выше для исправления E501
        # Автоматический commit/rollback
        async with session_maker() as session, session.begin():
            # Ищем существующий сценарий
            select_stmt = select(ConversationScenario).where(
                ConversationScenario.scenario_key == scenario_key
            )
            result = await session.execute(select_stmt)
            existing_scenario = result.scalar_one_or_none()

            if existing_scenario:  # Сценарий найден - ОБНОВЛЯЕМ
                existing_scenario_version = existing_scenario.version
                new_version = existing_scenario_version + 1
                update_stmt = (
                    sqlalchemy_update(ConversationScenario)
                    .where(
                        ConversationScenario.scenario_id
                        == existing_scenario.scenario_id
                    )
                    .values(
                        name=name,
                        description=description,
                        definition=definition_yaml,
                        version=new_version,
                        # is_active не меняем при обновлении
                    )
                )
                await session.execute(update_stmt)
                updated_count = 1
                logger.info(
                    f"Сценарий '{scenario_key}' обновлен с "
                    f"v{existing_scenario_version} до v{new_version}."
                )
            else:  # Сценарий не найден - ДОБАВЛЯЕМ
                new_version = 1
                new_scenario = ConversationScenario(
                    scenario_key=scenario_key,
                    name=name,
                    description=description,
                    definition=definition_yaml,
                    is_active=True,
                    version=new_version,
                )
                session.add(new_scenario)
                await session.flush()
                added_count = 1
                logger.info(f"Добавлен новый сценарий '{scenario_key}' v{new_version}.")
        logger.info(f"Операция с БД для сценария '{scenario_key}' завершена успешно.")

    # --- Обработка ВСЕХ возможных ошибок ---
    except (YAMLError, ValueError, SQLAlchemyError, UnicodeDecodeError) as e:
        error_message = f"{type(e).__name__}: {e}"
        logger.error(
            f"Ошибка обработки файла {doc.file_name}: {error_message}", exc_info=True
        )
    except Exception as e:
        error_message = f"Неожиданная ошибка обработки: {type(e).__name__}: {e}"
        logger.error(
            f"Неожиданная ошибка обработки файла {doc.file_name}: {error_message}",
            exc_info=True,
        )

    # --- Отправка ПОЛНОГО Отчета ---
    try:
        # Определяем escape_md
        try:
            from utils.message_utils import escape_md
        except ImportError:
            escape_md = _escape_md_fallback
    except Exception as esc_err:
        logger.error(f"Критическая ошибка получения escape_md: {esc_err}")
        # Исправлено E731: Используем _escape_md_fallback вместо lambda
        escape_md = _escape_md_fallback  # Абсолютный fallback

    # Формируем отчет
    escaped_filename = escape_md(doc.file_name)
    escaped_key = escape_md(processed_key)
    report_text = ""

    if error_message:
        escaped_error = escape_md(error_message)
        report_text = (
            f"❌ *Ошибка при обработке файла* `{escaped_filename}`:\n{escaped_error}"
        )
    else:
        report_text = (
            f"✅ *Файл сценария* `{escaped_filename}` " f"*успешно обработан\\.*\n\n"
        )
        if added_count > 0:
            escaped_version = escape_md(new_version)
            report_text += (
                f"\\- Добавлен новый сценарий: `{escaped_key}` "
                f"\\(v{escaped_version}\\)\n"
            )
        if updated_count > 0:
            escaped_version = escape_md(new_version)
            report_text += (
                f"\\- Обновлен сценарий: `{escaped_key}` "
                f"\\(новая версия: v{escaped_version}\\)\n"
            )
        if added_count == 0 and updated_count == 0 and not error_message:
            report_text += "\\_\\(Изменений не внесено\\)_"

    plain_fallback_text = (
        f"Обработка файла {doc.file_name} завершена. "
        f"Добавлено:{added_count}, Обновлено:{updated_count}. "
        f"Ошибка:{error_message or 'Нет'}"
    )

    # Отправка
    try:
        logger.debug(f"Попытка отправить ПОЛНЫЙ отчет: {report_text[:100]}...")
        await message.reply_text(
            report_text, parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        logger.info(f"Полный отчет для {doc.file_name} успешно отправлен.")
    except telegram.error.BadRequest as send_err:
        logger.error(
            f"Ошибка отправки ПОЛНОГО отчета (MarkdownV2): {send_err}", exc_info=True
        )
        await message.reply_text(plain_fallback_text)
    except Exception as send_err:
        logger.error(
            f"Неожиданная ошибка при отправке ПОЛНОГО отчета: {send_err}", exc_info=True
        )
        await message.reply_text(plain_fallback_text)


# === END BLOCK 8 ===
