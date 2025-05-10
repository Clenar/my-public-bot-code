# load_services_to_db.py (Исправленная версия)
import asyncio
import csv
import logging
import os
import sys

# Исправлено UP035: typing.Dict/List -> dict/list
from typing import Any, Optional

# Убедитесь, что модели и сессии доступны
try:
    # Импорт text удален (F401)
    from sqlalchemy import func, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    # Убедитесь, что config импортируется для DATABASE_URL
    # и база данных может быть инициализирована
    from database.models import Services, close_database, initialize_database
except ImportError as e:
    # Строка разбита для E501
    print(
        f"Ошибка импорта: {e}. Убедитесь, что скрипт находится в "
        "правильном месте или настройте PYTHONPATH."
    )
    sys.exit(1)

# --- Параметры ---
CSV_FILENAME = "services_data.csv"
CSV_DELIMITER = ";"
# --- Конец Параметров ---

# Настройка логирования
log_formatter_file = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
)
log_formatter_console = logging.Formatter("%(levelname)s: %(message)s")

file_handler = logging.FileHandler("load_services.log", encoding="utf-8")
file_handler.setFormatter(log_formatter_file)
file_handler.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter_console)
console_handler.setLevel(logging.INFO)

logger = logging.getLogger()
# Комментарий разбит для E501
# Очищаем существующие обработчики, чтобы избежать дублирования
# при повторном запуске в некоторых средах
if logger.hasHandlers():
    logger.handlers.clear()
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Ожидаемые колонки
EXPECTED_HEADERS = [
    "name_key",
    "parent_name_key",
    "name_en",
    "name_es",
    "name_fr",
    "name_de",
    "name_uk",
    "name_pl",
    "name_ru",
    "name_ro",
    "name_ar",
    "name_tr",
    "name_fa",
    "name_pt",
    "name_hi",
    "name_uz",
    "category_group",
    "is_selectable_by_master",
    "is_selectable_by_customer",
    "requires_travel_question",
    "requires_workplace_question",
    "admin_managed",
]
LANG_COLUMNS = {
    lang_code: f"name_{lang_code}"
    for lang_code in [
        "en",
        "es",
        "fr",
        "de",
        "uk",
        "pl",
        "ru",
        "ro",
        "ar",
        "tr",
        "fa",
        "pt",
        "hi",
        "uz",
    ]
}


def str_to_bool(val: Optional[str]) -> bool:
    """Преобразует строковое представление boolean в bool."""
    if val is None:
        return False
    return val.strip().lower() in ["true", "1", "yes", "on"]


async def load_data(session_maker: async_sessionmaker[AsyncSession]):
    """Читает CSV и загружает данные в таблицу Services последовательно."""
    # Исправлены UP006: Dict/List -> dict/list
    all_rows_data: dict[str, dict[str, Any]] = {}
    child_map: dict[str, list[str]] = {}
    root_keys: list[str] = []
    col_indices: dict[str, int] = {}

    logging.info(f"Чтение данных из {CSV_FILENAME}...")
    try:
        # Используем 'utf-8-sig' для корректной обработки BOM, если он есть
        with open(CSV_FILENAME, encoding="utf-8-sig", newline="") as infile:
            reader = csv.reader(infile, delimiter=CSV_DELIMITER)
            try:
                header = next(reader)
            except StopIteration:
                logging.error(f"Ошибка: CSV файл '{CSV_FILENAME}' пуст.")
                return False

            header = [h.strip() for h in header]
            missing_cols = []
            actual_indices = {}
            for expected_col in EXPECTED_HEADERS:
                try:
                    actual_indices[expected_col] = header.index(expected_col)
                except ValueError:
                    missing_cols.append(expected_col)
            if missing_cols:
                # Строка f-string разбита для E501
                logging.error(
                    "Критическая ошибка: Отсутствуют колонки: "
                    f"{', '.join(missing_cols)}"
                )
                return False
            col_indices = actual_indices
            logging.info("Заголовки CSV проверены.")

            for i, row in enumerate(reader):
                row_num = i + 2
                if len(row) != len(header):
                    # Строка f-string разбита для E501
                    logging.warning(
                        f"Строка {row_num}: Несоответствие колонок "
                        f"({len(row)}/{len(header)}). Пропуск."
                    )
                    continue
                try:
                    name_key = row[col_indices["name_key"]].strip()
                    parent_name_key = (
                        row[col_indices["parent_name_key"]].strip() or None
                    )
                    if not name_key:
                        logging.warning(f"Строка {row_num}: Пустой name_key. Пропуск.")
                        continue
                    if name_key in all_rows_data:
                        # Строка f-string разбита для E501
                        logging.warning(
                            f"Строка {row_num}: Дубликат name_key '{name_key}'. "
                            "Перезапись."
                        )

                    row_data = {"name_key": name_key}
                    # Исправлено B007: code -> _code
                    for _code, col_name in LANG_COLUMNS.items():
                        row_data[col_name] = row[col_indices[col_name]].strip() or None
                    row_data.update(
                        {
                            "parent_name_key": parent_name_key,
                            "category_group": row[
                                col_indices["category_group"]
                            ].strip(),
                            "is_selectable_by_master": str_to_bool(
                                row[col_indices["is_selectable_by_master"]]
                            ),
                            "is_selectable_by_customer": str_to_bool(
                                row[col_indices["is_selectable_by_customer"]]
                            ),
                            "requires_travel_question": str_to_bool(
                                row[col_indices["requires_travel_question"]]
                            ),
                            "requires_workplace_question": str_to_bool(
                                row[col_indices["requires_workplace_question"]]
                            ),
                            "admin_managed": str_to_bool(
                                row[col_indices["admin_managed"]]
                            ),
                            "parent_id": None,  # Будет заполнено позже
                        }
                    )
                except IndexError:
                    logging.error(
                        f"Строка {row_num}: Ошибка индекса. Строка: {row}. Пропуск."
                    )
                    continue
                except Exception as e:
                    # Строка f-string разбита для E501
                    logging.error(
                        f"Строка {row_num}: Ошибка обработки: {e}. "
                        f"Строка: {row}. Пропуск.",
                        exc_info=True,
                    )
                    continue

                all_rows_data[name_key] = row_data
                parent_key_for_map = parent_name_key if parent_name_key else "__ROOT__"
                if parent_key_for_map not in child_map:
                    child_map[parent_key_for_map] = []
                child_map[parent_key_for_map].append(name_key)
                if not parent_name_key:
                    root_keys.append(name_key)

    except FileNotFoundError:
        logging.error(f"Ошибка: Файл '{CSV_FILENAME}' не найден.")
        return False
    except Exception as e:
        logging.error(f"Ошибка чтения CSV '{CSV_FILENAME}': {e}", exc_info=True)
        return False

    logging.info(f"Прочитано {len(all_rows_data)} строк данных из CSV.")
    if not all_rows_data:
        logging.warning("Нет данных для загрузки.")
        return False

    # --- Загрузка данных в БД ---
    # Исправлено UP006: Dict -> dict
    inserted_keys_to_id: dict[str, int] = {}
    processed_in_session: set[str] = set()
    total_records = len(all_rows_data)
    processed_count = 0
    error_keys: list[str] = []

    async def insert_recursive_wrapper(session: AsyncSession, key: str):
        """Рекурсивно вставляет/обновляет записи, начиная с ключа."""
        nonlocal processed_count
        if key in processed_in_session:
            if key not in inserted_keys_to_id:  # Ensure ID exists if processed
                select_stmt = select(Services.service_id).where(
                    Services.name_key == key
                )
                result = await session.execute(select_stmt)
                existing_id = result.scalar_one_or_none()
                if existing_id:
                    inserted_keys_to_id[key] = existing_id
                else:
                    logging.error(
                        f"Критическая ошибка: Ключ '{key}' обработан, но ID не найден!"
                    )
            return

        if key not in all_rows_data:
            logging.error(f"Ошибка целостности: Ключ '{key}' отсутствует в данных CSV.")
            return

        data_to_insert = all_rows_data[key].copy()
        parent_name_key = data_to_insert.pop("parent_name_key", None)
        parent_id: Optional[int] = None
        if parent_name_key:
            if parent_name_key in inserted_keys_to_id:
                parent_id = inserted_keys_to_id[parent_name_key]
            else:  # Search DB if parent not yet processed in this run
                logging.debug(
                    f"Поиск parent_id для '{parent_name_key}' (для '{key}')..."
                )
                select_stmt = select(Services.service_id).where(
                    Services.name_key == parent_name_key
                )
                result = await session.execute(select_stmt)
                parent_id = result.scalar_one_or_none()
                if parent_id:
                    inserted_keys_to_id[parent_name_key] = parent_id
                    logging.debug(f"Найден ID={parent_id} для '{parent_name_key}'.")
                else:
                    # Строка f-string разбита для E501
                    logging.error(
                        f"Ошибка связи: parent_id не найден для '{parent_name_key}' "
                        f"(при обработке '{key}')."
                    )
        data_to_insert["parent_id"] = parent_id

        try:
            stmt = pg_insert(Services).values(data_to_insert)
            # Обновляем все колонки кроме первичного ключа и ключа конфликта
            update_dict = {
                col.name: getattr(stmt.excluded, col.name)
                for col in Services.__table__.columns
                if col.name in data_to_insert
                and not col.primary_key
                and col.name != Services.name_key.name
            }
            update_dict[Services.updated_at.name] = func.now()  # Обновляем дату
            stmt = stmt.on_conflict_do_update(
                index_elements=[Services.name_key], set_=update_dict
            ).returning(Services.service_id)

            result = await session.execute(stmt)
            inserted_id = result.scalar_one()
            inserted_keys_to_id[key] = inserted_id
            logging.debug(
                f"Успешно обработан: {key} (ID: {inserted_id}) ParentID: {parent_id}"
            )
        except Exception as db_err:
            logging.error(
                f"Ошибка БД при вставке/обновлении '{key}': {db_err}", exc_info=False
            )
            error_keys.append(key)
            processed_in_session.add(key)  # Считаем обработанным с ошибкой
            processed_count += 1
            if processed_count % 50 == 0 or processed_count == total_records:
                # Строка f-string разбита для E501
                logging.info(
                    f"Обработано {processed_count}/{total_records} записей "
                    "(с ошибками)..."
                )
            return  # Пропускаем обработку детей

        processed_in_session.add(key)
        processed_count += 1
        if processed_count % 50 == 0 or processed_count == total_records:
            logging.info(f"Обработано {processed_count}/{total_records} записей...")

        # Рекурсивно обрабатываем детей ПОСЛЕДОВАТЕЛЬНО
        children_keys = child_map.get(key, [])
        if children_keys:
            logging.debug(f"Обработка {len(children_keys)} дочерних для '{key}'...")
            for child_key in children_keys:
                await insert_recursive_wrapper(session, child_key)

    logging.info("Начинаем загрузку данных в базу данных...")
    final_success = False
    async with session_maker() as session:
        try:
            logging.info(
                f"Обработка {len(root_keys)} корневых узлов ПОСЛЕДОВАТЕЛЬНО..."
            )
            for root_key in root_keys:
                await insert_recursive_wrapper(
                    session, root_key
                )  # Запускаем последовательно

            processed_successfully = len(processed_in_session) - len(error_keys)
            if error_keys:
                # Строка f-string разбита для E501
                logging.warning(
                    f"Во время загрузки возникли ошибки БД для {len(error_keys)} "
                    f"ключей. Первые {min(len(error_keys), 10)}: {error_keys[:10]}"
                )
            if len(processed_in_session) != total_records:
                missed_keys = set(all_rows_data.keys()) - processed_in_session
                # Строка f-string разбита для E501
                missed_keys_str = (
                    str(list(missed_keys)[:20]) + "..."
                    if len(missed_keys) > 20
                    else str(missed_keys)
                )
                logging.warning(
                    "Не все записи были запущены на обработку! "
                    f"Запущено: {len(processed_in_session)}, "
                    f"Всего: {total_records}. Пропущенные ключи: {missed_keys_str}"
                )

            await session.commit()
            # Строка f-string разбита для E501
            logging.info(
                "Транзакция завершена (commit). "
                f"Успешно вставлено/обновлено: {processed_successfully}, "
                f"Ошибок БД: {len(error_keys)}."
            )
            final_success = not error_keys  # Успешно, если не было ошибок БД

        except Exception as e:
            logging.error(f"Критическая ошибка транзакции: {e}", exc_info=True)
            try:
                await session.rollback()
                logging.info("Транзакция отменена (rollback).")
            except Exception as rb_err:
                logging.error(f"Ошибка отката транзакции: {rb_err}", exc_info=True)
            final_success = False

    return final_success


async def main():
    """Основная функция скрипта."""
    session_maker = await initialize_database()
    if not session_maker:
        logging.error("Инициализация БД не удалась. Загрузка отменена.")
        return
    load_successful = False
    try:
        load_successful = await load_data(session_maker)
    except Exception as e:
        logging.error(f"Неперехваченная ошибка в load_data: {e}", exc_info=True)
    finally:
        logging.info("Закрытие соединения с БД...")
        await close_database()
        # Строка f-string разбита для E501
        logging.info(
            "Загрузка данных завершена "
            f"{'УСПЕШНО' if load_successful else 'С ОШИБКАМИ'}."
        )


if __name__ == "__main__":
    try:
        # Проверяем доступность файла перед запуском asyncio
        with open(CSV_FILENAME, encoding="utf-8-sig") as f:
            pass
        logging.info(f"Найден файл {CSV_FILENAME}. Начинаем процесс загрузки...")
        asyncio.run(main())
    except FileNotFoundError:
        logging.error(f"Критическая ошибка: Файл '{CSV_FILENAME}' не найден.")
    except Exception as e:
        logging.error(f"Ошибка на этапе подготовки: {e}", exc_info=True)
    logging.info(f"Скрипт {os.path.basename(__file__)} завершил работу.")
