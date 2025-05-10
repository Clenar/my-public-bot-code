# BehaviorEngine/parser.py

# === BLOCK 1: Imports ===
import logging
from typing import Any, Dict, Optional

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yaml import YAMLError  # Импортируем специфичную ошибку парсинга YAML

# Импортируем модель сценария из БД
try:
    from database.models import ConversationScenario
except ImportError as e:
    # Логгируем критическую ошибку и прерываем выполнение, если модель не найдена
    logging.critical(
        f"CRITICAL: Failed to import DB models in parser: {e}", exc_info=True
    )
    raise
# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
# === END BLOCK 2 ===


# === BLOCK 3: In-Memory Cache ===
# Простой кэш для хранения распарсенных сценариев (dict[scenario_key, parsed_yaml_dict])
# Внимание: Этот кэш будет сброшен при перезапуске бота.
# Для более надежного кэширования в будущем можно использовать Redis (Phase 5).
_scenario_cache: Dict[str, Dict[str, Any]] = {}
# === END BLOCK 3 ===


# === BLOCK 4: Load and Parse Scenario Function ===
async def load_and_parse_scenario(
    scenario_key: str,
    session: AsyncSession,
    force_reload: bool = False,  # Флаг для принудительной перезагрузки из БД
) -> Optional[Dict[str, Any]]:
    """
    Загружает активный сценарий по ключу из БД, парсит YAML и кэширует результат.

    Args:
        scenario_key: Уникальный ключ сценария для загрузки.
        session: Активная сессия SQLAlchemy.
        force_reload: Если True, принудительно загружает из БД, игнорируя кэш.

    Returns:
        Словарь с распарсенным сценарием или None, если сценарий не найден,
        неактивен, содержит невалидный YAML или произошла ошибка БД.
    """
    if not scenario_key:
        logger.warning("Попытка загрузить сценарий с пустым scenario_key")
        return None

    # 1. Проверка кэша (если не требуется принудительная перезагрузка)
    if not force_reload and scenario_key in _scenario_cache:
        logger.debug(f"Сценарий '{scenario_key}' найден в кэше.")
        # Возвращаем копию из кэша, чтобы избежать случайного изменения оригинала
        return _scenario_cache[scenario_key].copy()

    logger.debug(
        f"Загрузка сценария '{scenario_key}' из БД (force_reload={force_reload})..."
    )
    try:
        # 2. Запрос к БД: ищем активный сценарий по ключу, выбираем только поле definition
        stmt = (
            select(ConversationScenario.definition)
            .where(ConversationScenario.scenario_key == scenario_key)
            .where(ConversationScenario.is_active)
            .limit(1)
        )  # Отступ этой строки важен
        result = await session.execute(stmt)
        yaml_definition_str = result.scalar_one_or_none()  # Получаем строку или None

        # Если сценарий не найден или неактивен
        if not yaml_definition_str:
            logger.warning(
                f"Активный сценарий с ключом '{scenario_key}' не найден в БД или не активен."
            )
            # Если ключ был в кэше (например, сценарий деактивировали), удаляем его
            if scenario_key in _scenario_cache:
                del _scenario_cache[scenario_key]
            return None

        # 3. Парсинг YAML-строки
        try:
            parsed_scenario = yaml.safe_load(yaml_definition_str)
            # Дополнительная проверка: убедимся, что результат парсинга - это словарь
            if not isinstance(parsed_scenario, dict):
                logger.error(
                    f"Ошибка парсинга YAML для '{scenario_key}': результат не является словарем (dict). Тип: {type(parsed_scenario)}"
                )
                # Очищаем кэш для этого ключа, если там была некорректная запись
                if scenario_key in _scenario_cache:
                    del _scenario_cache[scenario_key]
                return None

            logger.info(
                f"Сценарий '{scenario_key}' успешно загружен из БД и распарсен."
            )
            # 4. Кэширование успешно распарсенного результата
            _scenario_cache[scenario_key] = parsed_scenario
            # Возвращаем копию словаря
            return parsed_scenario.copy()

        except YAMLError as e:
            # Обработка ошибок парсинга YAML
            logger.error(
                f"Ошибка парсинга YAML для сценария '{scenario_key}': {e}",
                exc_info=True,
            )
            # Очищаем кэш для этого ключа
            if scenario_key in _scenario_cache:
                del _scenario_cache[scenario_key]
            return None

    except Exception as e:
        # 5. Обработка ошибок БД или других неожиданных ошибок при загрузке
        logger.error(
            f"Ошибка БД или другая ошибка при загрузке сценария '{scenario_key}': {e}",
            exc_info=True,
        )
        # Очищаем кэш для этого ключа
        if scenario_key in _scenario_cache:
            del _scenario_cache[scenario_key]
        return None


# === END BLOCK 4 ===


# === BLOCK 5: Clear Cache Function ===
def clear_scenario_cache(scenario_key: Optional[str] = None) -> None:
    """
    Очищает кэш сценариев (либо весь, либо по ключу).
    Полезно вызывать, например, после команды /upload_scenario.

    Args:
        scenario_key: Если указан, очищает кэш только для этого ключа.
                      Если None, очищает весь кэш.
    """
    global _scenario_cache
    if scenario_key:
        # Используем pop для удаления и избежания KeyError, если ключа нет
        if _scenario_cache.pop(scenario_key, None) is not None:
            logger.info(f"Кэш для сценария '{scenario_key}' очищен.")
        else:
            logger.debug(
                f"Попытка очистить кэш для ключа '{scenario_key}', который не был закэширован."
            )
    else:
        _scenario_cache = {}
        logger.info("Кэш всех сценариев очищен.")


# === END BLOCK 5 ===
