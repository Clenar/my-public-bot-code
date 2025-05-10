# Sprofy/database/models.py (Версия с добавленной моделью UserStates)

# === BLOCK 1: Imports ===
import asyncio
import datetime
import logging
from typing import Any, Optional  # Добавлены Any, Optional, Union для type hints

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)

# Импорт JSONB для PostgreSQL
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
)

# === END BLOCK 1 ===


# === BLOCK 2: Logger Definition ===
logger = logging.getLogger(__name__)
# === END BLOCK 2 ===


# === BLOCK 3: Database Connection Setup ===
# --- Импорт данных для подключения ---
try:
    # Убедитесь, что config.py существует и содержит эти переменные
    from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

    if (
        not all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD])
        or "YOUR_" in DB_HOST
        or "ВАШ_" in DB_PASSWORD
    ):
        raise ValueError(
            "Данные для подключения к БД не заданы или не изменены в config.py"
        )
    DB_PORT = int(DB_PORT)  # Преобразуем порт в число
    # Формируем URL для SQLAlchemy asyncpg
    DATABASE_URL = (
        f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    # URL для логов, чтобы не светить пароль
    log_url = f"postgresql+asyncpg://{DB_USER}:***@{DB_HOST}:{DB_PORT}/{DB_NAME}"

except (ImportError, KeyError, ValueError, TypeError) as e:
    logger.critical(
        f"!!! ОШИБКА КОНФИГУРАЦИИ БД: {e} !!! Не удалось создать DATABASE_URL."
    )
    DATABASE_URL = None  # Явно указываем None, если URL не создан
# === END BLOCK 3 ===


# === BLOCK 4: SQLAlchemy Async Engine Setup ===
# --- Настройка SQLAlchemy Async ---
async_engine = None  # Глобальная переменная для движка
AsyncSessionLocal: Optional[async_sessionmaker[AsyncSession]] = (
    None  # Глобальная фабрика сессий
)
_get_or_create_lock = (
    asyncio.Lock()
)  # Мьютекс для предотвращения гонок при создании юзера
# === END BLOCK 4 ===


# === BLOCK 5: Base Model Definition ===
# --- Определение Базовой Модели ---
class Base(DeclarativeBase):
    # Настройка типа данных для datetime с таймзоной
    type_annotation_map = {
        datetime.datetime: DateTime(timezone=True),
    }

    # Автоматическое добавление поля created_at
    @declared_attr.directive
    def created_at(cls) -> Mapped[datetime.datetime]:
        return mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )

    # Автоматическое добавление/обновление поля updated_at
    @declared_attr.directive
    def updated_at(cls) -> Mapped[datetime.datetime]:
        return mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )


# === END BLOCK 5 ===


# === BLOCK 6: UserData Model ===
# --- Модель Пользователя ---
class UserData(Base):
    __tablename__ = "user_data"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(
        String(100), index=True, nullable=True
    )
    first_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    last_search_city: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    last_search_city_updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        nullable=True
    )
    last_seen: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    is_banned: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    # Связи
    master_profile: Mapped[Optional["Masters"]] = relationship(back_populates="user")
    registration_code_used: Mapped[Optional["RegistrationCodes"]] = relationship(
        back_populates="user_who_used"
    )
    # --- НОВАЯ СВЯЗЬ для UserStates ---
    current_state: Mapped[Optional["UserStates"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",  # Удаляем состояние, если удаляется юзер
    )
    # ----------------------------------

    def __repr__(self):
        admin_status = "[ADMIN]" if self.is_admin else ""
        banned_status = "[BANNED]" if self.is_banned else ""
        # Строка f-string разбита для E501
        return (
            f"<UserData(id={self.user_id}, u='{self.username}'"
            f"{admin_status}{banned_status})>"
        )


# === END BLOCK 6 ===


# === BLOCK 7: Masters Model ===
# --- Модель Профиля Мастера ---
class Masters(Base):
    __tablename__ = "masters"
    master_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ИЗМЕНЕНИЕ: ForeignKey теперь ссылается на user_id типа BigInteger
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_data.user_id"), unique=True, nullable=False, index=True
    )
    city: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    district: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    workplace_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # Например: 'salon', 'home', 'both'
    travels_to_client: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    experience_years: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_username: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    share_telegram_contact: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )  # Мастер может временно отключить профиль
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )  # Верификация админом

    # Связи
    user: Mapped["UserData"] = relationship(back_populates="master_profile")
    services: Mapped[list["Services"]] = relationship(
        secondary="master_services",
        back_populates="masters",
        lazy="selectin",  # Загружать связанные услуги сразу
    )
    photos: Mapped[list["MasterPhotos"]] = relationship(
        back_populates="master",
        cascade="all, delete-orphan",  # Удалять фото при удалении мастера
        lazy="selectin",
    )
    # Комментарий перенесен для E501
    # Указываем SQLAlchemy, что эта связь пересекается с 'services'
    service_associations: Mapped[list["MasterServices"]] = relationship(
        back_populates="master",
        cascade="all, delete-orphan",
        overlaps="services",
    )

    def __repr__(self):
        status = ("ACTIVE" if self.is_active else "PAUSED") + (
            " VERIFIED" if self.is_verified else " UNVERIFIED"
        )
        # Строка f-string разбита для E501
        return (
            f"<Master(id={self.master_id}, user_id={self.user_id}, "
            f"city='{self.city}', status='{status}')>"
        )


# === END BLOCK 7 ===


# === BLOCK 8: Services Model ===
# --- Модель Услуг ---
class Services(Base):
    __tablename__ = "services"
    service_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("services.service_id"), nullable=True, index=True
    )
    # Уникальный ключ для идентификации (например, 'nails_manicure_classic')
    name_key: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )

    # --- Колонки для названий на разных языках ---
    name_en: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # Английский обязателен
    name_es: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name_fr: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name_de: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name_uk: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name_pl: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name_ru: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name_ro: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name_ar: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Text для языков с другим письмом
    name_tr: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name_fa: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    name_pt: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name_hi: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    name_uz: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # -------------------------------------------

    # Дополнительные поля для управления логикой
    category_group: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # Группа (nails, hair, etc.)
    is_selectable_by_master: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )  # Может ли мастер выбрать эту услугу
    is_selectable_by_customer: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )  # Может ли клиент искать по этой услуге
    requires_travel_question: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Нужно ли спрашивать про выезд
    requires_workplace_question: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Нужно ли спрашивать про место работы
    admin_managed: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )  # Управляется админом или может добавляться пользователями?

    # Связи для иерархии
    parent: Mapped[Optional["Services"]] = relationship(
        back_populates="children", remote_side=[service_id]
    )
    children: Mapped[list["Services"]] = relationship(
        back_populates="parent", lazy="selectin", cascade="all, delete-orphan"
    )

    # Связи с мастерами
    masters: Mapped[list["Masters"]] = relationship(
        secondary="master_services",
        back_populates="services",
        lazy="selectin",
        overlaps="service_associations",
    )
    master_associations: Mapped[list["MasterServices"]] = relationship(
        back_populates="service", overlaps="masters,services"
    )

    def __repr__(self):
        # Строка f-string разбита для E501
        return (
            f"<Service(id={self.service_id}, key='{self.name_key}', "
            f"name_en='{self.name_en}')>"
        )


# === END BLOCK 8 ===


# === BLOCK 9: MasterServices Model (Association Table) ===
# --- Таблица Связи Мастер <-> Услуга ---
class MasterServices(Base):
    __tablename__ = "master_services"
    # created_at/updated_at наследуются от Base

    master_service_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(
        ForeignKey("masters.master_id"), nullable=False, index=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.service_id"), nullable=False, index=True
    )
    # Дополнительные поля для связи
    price: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )  # Цена конкретной услуги у мастера
    custom_description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Описание услуги от мастера

    # Ограничение: одна и та же услуга у одного мастера может быть только раз
    __table_args__ = (
        UniqueConstraint("master_id", "service_id", name="uq_master_service"),
    )

    # Связи с основными таблицами
    master: Mapped["Masters"] = relationship(
        back_populates="service_associations", overlaps="masters,services"
    )
    service: Mapped["Services"] = relationship(
        back_populates="master_associations",
        lazy="joined",  # Загружать данные услуги сразу при запросе связи
        overlaps="masters,services",
    )

    def __repr__(self):
        # Строка f-string разбита для E501
        return (
            f"<MasterService(msid={self.master_service_id}, "
            f"mid={self.master_id}, sid={self.service_id})>"
        )


# === END BLOCK 9 ===


# === BLOCK 10: MasterPhotos Model ===
# --- Модель Фото Работ Мастера ---
class MasterPhotos(Base):
    __tablename__ = "master_photos"
    photo_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(
        ForeignKey("masters.master_id"), nullable=False, index=True
    )
    # Храним ID файла в Telegram для повторной отправки
    telegram_file_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    caption: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True
    )  # Подпись к фото

    # Связь
    master: Mapped["Masters"] = relationship(back_populates="photos")

    def __repr__(self):
        # Строка f-string разбита для E501
        return (
            f"<MasterPhoto(id={self.photo_id}, master_id={self.master_id}, "
            f"file_id='{self.telegram_file_id[:10]}...')>"
        )


# === END BLOCK 10 ===


# === BLOCK 11: RegistrationCodes Model ===
# --- Модель Кодов Регистрации Мастеров ---
class RegistrationCodes(Base):
    __tablename__ = "registration_codes"
    code: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )  # Сам код - первичный ключ
    is_used: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    used_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_data.user_id"), nullable=True
    )  # Кто использовал
    used_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        nullable=True
    )  # Когда использовал

    # Связь для получения пользователя, который использовал код
    user_who_used: Mapped[Optional["UserData"]] = relationship(
        back_populates="registration_code_used"
    )

    def __repr__(self):
        status = "USED" if self.is_used else "AVAILABLE"
        user_id_info = (
            f" by user {self.used_by_user_id}" if self.used_by_user_id else ""
        )
        return f"<RegCode(code='{self.code}', status={status}{user_id_info})>"


# === END BLOCK 11 ===


# === BLOCK 12: Instructions Model ===
# --- Модель Инструкций/Настроек для AI/Бота ---
class Instructions(Base):
    __tablename__ = "instructions"
    instruction_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Уникальный ключ для поиска инструкции (например, 'master_registration_welcome')
    key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )

    # --- Колонки для текста на разных языках ---
    text_en: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_es: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_fr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_de: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_uk: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_pl: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_ru: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_ro: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_ar: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_tr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_fa: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_pt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_hi: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_uz: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # -------------------------------------------

    # Описание назначения инструкции (для администратора)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self):
        return f"<Instruction(id={self.instruction_id}, key='{self.key}')>"


# === END BLOCK 12 ===


# === BLOCK 13: ConversationScenario Model ===
class ConversationScenario(Base):
    __tablename__ = "conversation_scenarios"

    scenario_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Ключ сценария, используемый для его идентификации в коде/движке
    scenario_key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    # Человекочитаемое имя сценария
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Описание назначения сценария
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Содержимое сценария в формате YAML (или JSON) как строка
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    # Флаг активности сценария
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    # Версия сценария для отслеживания изменений
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # created_at и updated_at наследуются от Base

    __table_args__ = (
        UniqueConstraint("scenario_key", name="uq_scenario_key"),  # Уникальный ключ
    )

    def __repr__(self):
        status = "active" if self.is_active else "inactive"
        # Строка f-string разбита для E501
        return (
            f"<Scenario(id={self.scenario_id}, key='{self.scenario_key}', "
            f"name='{self.name}', v={self.version}, status='{status}')>"
        )


# === END BLOCK 13 ===


# === BLOCK 14: UserStates Model (НОВАЯ МОДЕЛЬ) ===
class UserStates(Base):
    """Хранит текущее состояние пользователя в рамках активного сценария."""

    __tablename__ = "user_states"

    user_state_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Ссылка на пользователя. Используем BigInteger, как в UserData.user_id
    # Добавляем nullable=False, т.к. состояние без пользователя бессмысленно.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_data.user_id"), nullable=False, index=True
    )
    # Ключ активного сценария из таблицы conversation_scenarios
    scenario_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # Ключ текущего состояния (шага) внутри сценария
    current_state_key: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    # Контекст состояния в формате JSON (для хранения временных данных сценария)
    # Используем JSONB для эффективности в PostgreSQL. Указываем тип Python dict[str, Any]
    state_context: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    # created_at и updated_at наследуются от Base

    # Связь для доступа к объекту UserData из состояния
    user: Mapped["UserData"] = relationship(back_populates="current_state")

    # Ограничение: У одного пользователя может быть только одно активное состояние?
    # Если да, можно добавить UniqueConstraint("user_id", name="uq_user_state")
    # Пока не добавляем для гибкости, но стоит подумать.
    # __table_args__ = (UniqueConstraint("user_id", name="uq_user_state"),)

    def __repr__(self):
        # Строка f-string разбита для E501
        return (
            f"<UserState(id={self.user_state_id}, user={self.user_id}, "
            f"scenario='{self.scenario_key}', state='{self.current_state_key}')>"
        )


# === END BLOCK 14 ===


# === BLOCK 15: Database Helper Functions === (Перенумерован)
# --- Функции для инициализации и работы с БД ---
# (Включая исправления E501 и SIM117)


async def initialize_database() -> Optional[async_sessionmaker[AsyncSession]]:
    """
    Инициализирует асинхронный движок SQLAlchemy, создает/обновляет все таблицы
    (определенные через Base) и возвращает async_sessionmaker.
    """
    global async_engine, AsyncSessionLocal
    local_session_maker: Optional[async_sessionmaker[AsyncSession]] = None
    if not DATABASE_URL:
        logger.critical("DATABASE_URL не определен в config.py или произошла ошибка.")
        return None

    try:
        logger.info(f"Инициализация SQLAlchemy async engine для: {log_url}")
        # Если движок уже существует, корректно закроем его перед созданием нового
        if async_engine:
            # Строка разбита для E501
            logger.warning(
                "Попытка повторной инициализации БД без закрытия. "
                "Закрываем старый движок..."
            )
            await close_database()

        # Создаем асинхронный движок
        async_engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
        # Создаем фабрику асинхронных сессий
        local_session_maker = async_sessionmaker(
            async_engine, expire_on_commit=False, class_=AsyncSession
        )
        # Сохраняем фабрику глобально для использования в get_or_create_user и др.
        AsyncSessionLocal = local_session_maker

        logger.info(
            "Проверка/создание/обновление таблиц через Base.metadata.create_all..."
        )
        # Комментарий разбит для E501
        # Используем begin() для автоматического управления транзакцией
        # при создании таблиц
        async with async_engine.begin() as conn:
            # Комментарий разбит для E501
            # Эта команда создаст/обновит ВСЕ таблицы, унаследованные от Base,
            # включая новую UserStates
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Таблицы проверены/созданы/обновлены.")
        logger.info("SQLAlchemy async engine и sessionmaker инициализированы.")
        return local_session_maker  # Возвращаем фабрику для передачи в bot_data

    except Exception as e:
        logger.critical(
            f"!!! КРИТИЧЕСКАЯ ОШИБКА при инициализации SQLAlchemy: {e}", exc_info=True
        )
        # Пытаемся закрыть движок, если он был частично создан
        if async_engine:
            try:
                await async_engine.dispose()
            except Exception as dispose_e:
                logger.error(
                    "Ошибка при закрытии движка после сбоя инициализации: "
                    f"{dispose_e}"
                )
        async_engine = None
        AsyncSessionLocal = None
        return None


async def close_database():
    """Корректно закрывает (утилизирует) асинхронный движок SQLAlchemy."""
    global async_engine, AsyncSessionLocal
    if async_engine:
        try:
            logger.info("Закрытие SQLAlchemy async engine...")
            await async_engine.dispose()  # Освобождаем пул соединений
            logger.info("SQLAlchemy async engine закрыт.")
        except Exception as e:
            logger.error(f"Ошибка при закрытии SQLAlchemy: {e}", exc_info=True)
    # Сбрасываем глобальные переменные
    async_engine = None
    AsyncSessionLocal = None


async def get_or_create_user(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    language_code: Optional[str] = None,
) -> tuple[Optional[UserData], bool]:
    """
    Получает пользователя по ID или создает нового, используя
    глобальную AsyncSessionLocal. (Строка docstring разбита для E501)
    Обновляет username, first_name, language_code, last_seen при каждом вызове.
    Возвращает (объект UserData или None, флаг created=True/False).
    """
    if not AsyncSessionLocal:
        # Строка разбита для E501
        logger.error(
            "get_or_create_user: AsyncSessionLocal не инициализирована! "
            "Вызовите initialize_database() сначала."
        )
        return None, False

    created = False
    user: UserData | None = None
    current_time = datetime.datetime.now(datetime.timezone.utc)  # Используем UTC

    # Комментарий разбит для E501
    # Используем мьютекс для предотвращения гонки
    # при одновременном создании одного юзера
    # Исправлено SIM117: объединены lock, session и transaction begin в один with
    async with _get_or_create_lock, AsyncSessionLocal() as session, session.begin():
        try:
            # Пытаемся получить пользователя
            stmt_get = select(UserData).where(UserData.user_id == user_id)
            result = await session.execute(stmt_get)
            user = result.scalar_one_or_none()

            if user:
                # Пользователь найден, обновляем данные
                needs_update = False
                if user.username != username:
                    user.username = username
                    needs_update = True
                if user.first_name != first_name:
                    user.first_name = first_name
                    needs_update = True
                # Обновляем язык только если он передан и отличается
                if language_code and user.language_code != language_code:
                    user.language_code = language_code
                    needs_update = True
                # Всегда обновляем last_seen
                user.last_seen = current_time
                needs_update = True  # Эта строка была здесь, сохраняем

                if needs_update:
                    logger.debug(f"Обновление данных для UserData {user_id}...")
                # Комментарий разбит для E501
                # session.add(user) не нужен здесь, т.к. объект уже в сессии
                # и будет сохранен при commit
                created = False
            else:
                # Пользователь не найден, создаем нового
                # Строка f-string разбита для E501
                logger.info(
                    f"[get_or_create_user] Пользователь {user_id} "
                    "не найден, создаем..."
                )
                user = UserData(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    language_code=language_code,
                    # Комментарий перенесен для E501
                    last_seen=current_time,  # last_seen устанавливается при создании
                )
                session.add(user)  # Добавляем нового пользователя в сессию
                # Не нужно вызывать flush или refresh здесь, т.к. мы в begin()
                logger.info(f"Новый UserData {user_id} ({username}) добавлен в сессию.")
                created = True

        except SQLAlchemyIntegrityError as e:
            # Комментарий разбит для E501
            # Эта ошибка может возникнуть, если два процесса одновременно
            # пытаются создать одного юзера
            # Строка f-string разбита для E501
            logger.warning(
                f"[get_or_create_user] IntegrityError для user_id={user_id}. "
                f"Вероятно, создан параллельно. Ошибка: {e}"
            )
            # Комментарий разбит для E501
            # Транзакция будет автоматически отменена (rollback)
            # из-за session.begin()
            # Комментарий разбит для E501
            # Пытаемся получить пользователя еще раз ВНУТРИ ЭТОЙ ЖЕ СЕССИИ
            # (но уже после rollback)
            # Комментарий разбит для E501
            # Это может не сработать как ожидается без новой транзакции,
            # но попробуем
            # Комментарий разбит для E501
            # ЛУЧШЕ: Выйти из lock и сделать повторный вызов
            # get_or_create_user, но пока так.
            try:
                stmt_get_retry = select(UserData).where(UserData.user_id == user_id)
                result_retry = await session.execute(stmt_get_retry)
                user = result_retry.scalar_one_or_none()
                if user:
                    # Комментарий разбит для E501
                    # Если нашли, обновляем last_seen и считаем,
                    # что не создавали
                    user.last_seen = current_time
                    session.add(user)  # Добавляем в сессию для обновления last_seen
                    # Строка f-string разбита для E501
                    logger.info(
                        f"UserData {user_id} успешно получен " "после IntegrityError."
                    )
                    created = False
                else:
                    # Строка f-string разбита для E501
                    logger.error(
                        f"!!! UserData {user_id} НЕ найден после "
                        "IntegrityError и повторной попытки!"
                    )
                    return None, False  # Критическая ситуация
            except Exception as e_retry:
                # Строка f-string разбита для E501
                logger.error(
                    "Критическая ошибка при повторном получении "
                    f"user_id={user_id} после IntegrityError: {e_retry}",
                    exc_info=True,
                )
                return None, False

        except Exception as e:
            # Строка f-string разбита для E501
            logger.error(
                "[get_or_create_user] Неперехваченная ошибка для "
                f"user_id={user_id}: {e}",
                exc_info=True,
            )
            # Транзакция будет автоматически отменена
            return None, False  # Возвращаем ошибку

        # Комментарий разбит для E501
        # Если вышли из session.begin() без исключений,
        # коммит произойдет автоматически
        # Если было исключение, произойдет rollback

    # Возвращаем пользователя (может быть None при ошибке) и флаг создания
    return user, created


# === END BLOCK 15 ===
