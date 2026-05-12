from __future__ import annotations

import asyncio
import datetime
import json
import traceback

import aiosqlite
import disnake
from disnake.ext import commands

# Подгружаем настройки
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

# Константы для дизайна
INVISIBLE_COLOR = 0x2B2D31
SKY_BLUE = 0x87CEEB  # «небесно-голубой» акцент Container'а панели заявок
ACCENT_COLOR = disnake.Colour(SKY_BLUE)
SUCCESS_COLOR = disnake.Colour(0x2E8B57)
ERROR_COLOR = disnake.Colour(0xED4245)
ORANGE_COLOR = disnake.Colour(0xE67E22)

# Максимум фото персонажей, которые можно прикрепить к заявке
MAX_APPLICATION_FILES = 10

# === Academy / Young constants ===
# Используются как fallback — любой из ID можно переопределить
# в config["ACADEMY"][...]. Держим дефолты здесь, чтобы не зависеть
# от наличия секции в config.
YOUNG_CATEGORY_ID = 1462480155418034301
ACADEMY_CATEGORY_ID = 1433846608914546818
YOUNG_ROLE_ID = 1480686843640156371
ACADEMY_ROLE_ID = 1183863207576739931
RECRUITMENT_ROLE_ID = 1217923581904687184
# Роль, выдаваемая после прохождения этапа ACADEMY («Повысить» на
# финале). Переопределяется через config["ACADEMY"]["RANK_FINAL"].
FINAL_ROLE_ID = 1183854185586901063
# Discord жёстко ограничивает категорию 50 каналами.
DISCORD_CATEGORY_MAX_CHANNELS = 50
ACADEMY_THREAD_NAMES = ("РП", "Арена", "Общение с рекрутёром")
ACADEMY_REFERENCE_IMAGE = (
    "https://media.discordapp.net/attachments/1416897708949504051/"
    "1503645046736420924/image.png?width=1517&height=856"
)

# Награды модератору в коинах (user_coins.balance).
ACCEPT_COIN_REWARD = 5
REJECT_COIN_REWARD = 0

# Тексты главного эмбеда в личном канале кандидата (правила).
ACADEMY_HEADER_TEXT = (
    "К отчетам принимаются откаты с МП: ФЗ, Остров, Диллеры, Цеха, "
    "Дроп, Поставки\n"
    "Скриншоты с ГГ принимаются только на Ангаре или Подъемнике, "
    "режим бой насмерть, ган спешик/тяга и сайга, с 16 сервера и выше."
)
ACADEMY_YOUNG_RULES = (
    "**1 часть академии, роль \"YOUNG\"**\n"
    "срок - 1 неделя\n"
    "◦ 5 скриншотов с МП с группой (пример ниже) в свою ветку "
    "**(на фоне общего группа)**\n"
    "◦ 2 отката где ты активно файтишься на МПшке и слышно колл на фоне\n"
    "◦ регулярные скрины с ГГ с кд от 1.2\n"
    "откатали МП - сделали скриншот, сразу скинули (не тяните с "
    "временем, сразу все скриншоты за неделю не принимаются)\n"
    "◦ 15 откатов с залазами с карт, которые играют сейчас"
)
ACADEMY_ACADEMY_RULES = (
    "**2 часть академии, роль \"ACADEMY\"**\n"
    "срок - 2 недели (14 дней)\n"
    "◦ 10 скриншотов с МП с группой в свою ветку "
    "**(на фоне общего группа)**\n"
    "◦ 5 откатов где ты активно файтишься на МПшке и слышно колл на "
    "фоне\n"
    "**ОБЯЗАТЕЛЬНЫЙ 1 откат с острова/фз**\n"
    "◦ регулярные скрины с ГГ с кд от 1.4\n"
    "откатали МП - сделали скриншот, сразу скинули (не тяните с "
    "временем, сразу все скриншоты за неделю не принимаются)"
)

# Persistent custom ids
APPLICATION_SELECT_CID = "application_action_select"
APPLICATION_OPTION_CREATE = "create_app"

# Топ рекрутеров: список периодов (key, label, timedelta | None)
TOPREC_PERIODS: list[tuple[str, str, datetime.timedelta | None]] = [
    ("day", "День", datetime.timedelta(days=1)),
    ("week", "Неделя", datetime.timedelta(days=7)),
    ("month", "Месяц", datetime.timedelta(days=30)),
    ("half_year", "Полгода", datetime.timedelta(days=182)),
    ("all", "Всё время", None),
]
TOPREC_DEFAULT_PERIOD = "day"
TOPREC_BUTTON_PREFIX = "toprec:"

# Discord-роль «Рекрутёр» — её участники всегда отображаются в `!toprec`,
# даже если у них пока нет принятых заявок и обзвонов (нули в таблице).
RECRUITER_ROLE_ID = 1416816494184239145

# Голосовые каналы обзвона (используется в on_voice_state_update + статистике
# `!toprec`). Конфигурируется здесь, чтобы канал можно было сменить в одном
# месте. Все ID хранятся как str — соответствует TEXT-колонкам в БД.
CALL_VOICE_CHANNEL_IDS: tuple[str, ...] = (
    "1463605913117134900",
    "1452067291343749180",
)
CALL_VOICE_CHANNEL_IDS_INT: frozenset[int] = frozenset(
    int(c) for c in CALL_VOICE_CHANNEL_IDS
)


def _iso_utc_now() -> str:
    """Текущее UTC-время как ISO-строка с секундной точностью."""
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def _format_seconds_compact(total_seconds: int) -> str:
    """Форматирует количество секунд как `Nч Mм` / `Mм Sс` / `Sс`."""
    total_seconds = max(0, int(total_seconds))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}ч {minutes:02d}м"
    if minutes:
        return f"{minutes}м {seconds:02d}с"
    return f"{seconds}с"


async def _start_call_voice_session(
    user_id: str, channel_id: str
) -> None:
    """Открывает новую сессию входа в канал обзвона.

    Идемпотентно — если у пользователя уже есть открытая сессия в этом
    канале, ничего не делает (защита от двойных событий и рестартов).
    """
    async with aiosqlite.connect("data/database.sqlite") as db:
        async with db.execute(
            "SELECT id FROM call_voice_sessions "
            "WHERE user_id = ? AND channel_id = ? AND left_at IS NULL "
            "LIMIT 1",
            (user_id, channel_id),
        ) as cur:
            existing = await cur.fetchone()
        if existing is not None:
            return
        await db.execute(
            "INSERT INTO call_voice_sessions "
            "(user_id, channel_id, joined_at) VALUES (?, ?, ?)",
            (user_id, channel_id, _iso_utc_now()),
        )
        await db.commit()


async def _close_call_voice_session(
    user_id: str, channel_id: str
) -> None:
    """Закрывает открытую сессию (если есть) — выставляет `left_at`."""
    async with aiosqlite.connect("data/database.sqlite") as db:
        await db.execute(
            "UPDATE call_voice_sessions SET left_at = ? "
            "WHERE user_id = ? AND channel_id = ? AND left_at IS NULL",
            (_iso_utc_now(), user_id, channel_id),
        )
        await db.commit()


async def _record_call_invite(
    message_id: str, recruiter_id: str, candidate_id: str
) -> None:
    """Фиксирует факт перевода заявки на обзвон.

    `message_id` — primary key, поэтому повторные клики на одной и той же
    заявке перезаписывают рекрутёра/время (правило «уникальный кандидат
    по заявкам»). Это нормально: если модератора подменили, актуальным
    считается последний.
    """
    async with aiosqlite.connect("data/database.sqlite") as db:
        await db.execute(
            "INSERT INTO call_invites "
            "(message_id, recruiter_id, candidate_id, called_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(message_id) DO UPDATE SET "
            "  recruiter_id = excluded.recruiter_id, "
            "  candidate_id = excluded.candidate_id, "
            "  called_at = excluded.called_at",
            (message_id, recruiter_id, candidate_id, _iso_utc_now()),
        )
        await db.commit()


# ==========================================
# ПОМОЩНИКИ ДЛЯ ЭМОДЗИ
# ==========================================
def e(key: str) -> str:
    """Для текста: возвращает эмодзи с пробелом или пустоту, если эмодзи нет."""
    val = config.get("EMOJIS", {}).get(key, "")
    return f"{val} " if val else ""


def e_btn(key: str):
    """Для кнопок/меню: возвращает эмодзи или None, если эмодзи нет."""
    val = config.get("EMOJIS", {}).get(key, "")
    return val if val else None


def get_safe_logo() -> str:
    logo = config.get("IMAGES", {}).get("LOGO", "").strip()
    if logo.startswith("Https"):
        logo = logo.replace("Https", "https")
    return logo


def get_safe_banner() -> str:
    banner = config.get("IMAGES", {}).get("APPLICATIONS_BANNER", "").strip()
    if banner.startswith("Https"):
        banner = banner.replace("Https", "https")
    return banner


# ==========================================
# ХЕЛПЕРЫ ДЛЯ COMPONENTS V2
# ==========================================
def simple_container(
    text: str, color: disnake.Colour = ACCENT_COLOR
) -> list[disnake.ui.Container]:
    return [
        disnake.ui.Container(
            disnake.ui.TextDisplay(text), accent_colour=color
        )
    ]


def _to_ui_container(container) -> disnake.ui.Container:
    """Гарантирует, что контейнер — disnake.ui.Container.

    ``inter.message.components[0]`` возвращает ``disnake.components.Container``,
    у которого children — тоже типа ``disnake.components.X``. Чтобы isinstance
    проверки на ``disnake.ui.X`` работали, конвертируем.
    """
    if isinstance(container, disnake.ui.Container):
        return container
    return disnake.ui.Container.from_component(container)


# Discord требует 1–45 символов в лейблах компонентов модалки.
MODAL_LABEL_MAX_LEN = 45


def _clip_label(text: str, max_len: int = MODAL_LABEL_MAX_LEN) -> str:
    """Обрезает лейбл до лимита Discord, добавляя «…», если был обрезок."""
    if not text:
        return text
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    return text[: max_len - 1] + "…"


def _file_upload_label(
    label: str = "Скрины персонажей",
    required: bool = True,
    max_files: int = MAX_APPLICATION_FILES,
) -> disnake.ui.Label:
    """Готовый Label с FileUpload (1–max_files файлов)."""
    return disnake.ui.Label(
        _clip_label(label),
        component=disnake.ui.FileUpload(
            custom_id="files",
            min_values=1 if required else 0,
            max_values=max_files,
            required=required,
        ),
        description=(
            f"Прикрепите до {max_files} скринов персонажей "
            "(скриншоты из игры)."
        ),
    )


def _is_attachment_like(obj) -> bool:
    """Утка-тайпинг для Attachment — на случай разных билдов disnake."""
    return (
        obj is not None
        and hasattr(obj, "id")
        and hasattr(obj, "filename")
        and hasattr(obj, "to_file")
    )


def _collect_modal_attachments(inter: disnake.ModalInteraction) -> list:
    """Собирает все Attachment из модалки максимально устойчиво.

    Главный путь — пройти по ``inter.data.components`` (как структура
    приходит от Discord), найти ``file_upload`` (type=19) внутри ``label``
    (type=18) и взять Attachment из ``inter.data.resolved.attachments`` по
    snowflake. Параллельно есть несколько резервных путей: чистый
    ``resolved_values`` disnake, прямой обход ``data.resolved.attachments``
    и сборка из сырого ``data["resolved"]["attachments"]`` если повезёт.
    """
    found: list = []
    seen_ids: set[int] = set()

    def _push(att) -> None:
        if not _is_attachment_like(att):
            return
        try:
            aid = int(att.id)
        except Exception:
            return
        if aid in seen_ids:
            return
        seen_ids.add(aid)
        found.append(att)

    def _walk(items):
        for c in items or []:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            if t == 1 and "components" in c:  # action_row
                yield from _walk(c["components"])
            elif t == 18 and "component" in c:  # label
                yield from _walk([c["component"]])
            else:
                yield c

    # PRIMARY: components -> file_upload(values) -> resolved.attachments by id.
    try:
        resolved_obj = getattr(inter.data, "resolved", None)
        atts_map = getattr(resolved_obj, "attachments", None) or {}
        for comp in _walk(getattr(inter.data, "components", []) or []):
            if comp.get("type") != 19:  # file_upload
                continue
            for vid in comp.get("values") or []:
                try:
                    att = atts_map.get(int(vid))
                except Exception:
                    att = None
                if att is None:
                    att = atts_map.get(str(vid))
                _push(att)
    except Exception as ex:
        print(f"[applications] primary walk failed: {ex!r}")

    if found:
        return found

    # 2) disnake resolved_values
    try:
        rv = getattr(inter, "resolved_values", None) or {}
        for v in rv.values():
            if isinstance(v, (list, tuple)):
                for item in v:
                    _push(item)
    except Exception as ex:
        print(f"[applications] resolved_values failed: {ex!r}")

    if found:
        return found

    # 3) Просто всё из inter.data.resolved.attachments
    try:
        resolved_obj = getattr(inter.data, "resolved", None)
        atts_map = getattr(resolved_obj, "attachments", None) or {}
        for att in atts_map.values():
            _push(att)
    except Exception as ex:
        print(f"[applications] resolved.attachments failed: {ex!r}")

    if found:
        return found

    # 4) Сырой dict-resolved — конструируем Attachment руками.
    try:
        raw_resolved = (
            inter.data.get("resolved")
            if hasattr(inter.data, "get")
            else None
        ) or {}
        raw_atts = raw_resolved.get("attachments") or {}
        state = getattr(inter, "_state", None)
        if state is not None:
            for raw_att in raw_atts.values():
                try:
                    _push(disnake.Attachment(data=raw_att, state=state))
                except Exception as ex:
                    print(f"[applications] Attachment ctor failed: {ex!r}")
    except Exception as ex:
        print(f"[applications] raw walk failed: {ex!r}")

    return found


async def _resolve_modal_files(
    inter: disnake.ModalInteraction,
) -> tuple[list[disnake.File], list[disnake.ui.Component]]:
    """Достаёт прикреплённые в модалку файлы и готовит их к повторной отправке.

    Возвращает кортеж: (files_to_attach, container_children_for_preview).
    Превью склеивается одной MediaGallery (если есть картинки/видео) и/или
    набором File-компонентов (для прочих файлов) — Discord отрендерит их
    прямо внутри Container, и пользователь сможет открыть/скачать каждый файл.
    """
    attachments = _collect_modal_attachments(inter)
    if not attachments:
        try:
            raw_components = getattr(inter.data, "components", None)
            raw_resolved = (
                inter.data.get("resolved")
                if hasattr(inter.data, "get")
                else None
            )
            print(
                "[applications] no attachments resolved | "
                f"components={raw_components!r} resolved={raw_resolved!r}"
            )
        except Exception:
            pass

    files: list[disnake.File] = []
    gallery_items: list[disnake.MediaGalleryItem] = []
    file_components: list[disnake.ui.Component] = []
    for idx, att in enumerate(attachments[:MAX_APPLICATION_FILES]):
        try:
            base_name = (att.filename or f"file_{idx}").replace(" ", "_")
            unique_name = f"{idx}_{base_name}"
            try:
                f = await att.to_file(filename=unique_name)
            except TypeError:
                f = await att.to_file()
                try:
                    f.filename = unique_name
                except Exception:
                    pass
            files.append(f)
            ct = (att.content_type or "").lower()
            ref = f"attachment://{unique_name}"
            if ct.startswith("image/") or ct.startswith("video/"):
                gallery_items.append(disnake.MediaGalleryItem(ref))
            else:
                file_components.append(
                    disnake.ui.File(disnake.UnfurledMediaItem(ref))
                )
        except Exception as ex:
            print(
                f"[applications] to_file failed for "
                f"{getattr(att, 'filename', '?')}: {ex!r}"
            )
            continue

    preview: list[disnake.ui.Component] = []
    if gallery_items:
        preview.append(disnake.ui.MediaGallery(*gallery_items))
    preview.extend(file_components)
    return files, preview


def _build_review_buttons(target_user_id: int) -> disnake.ui.ActionRow:
    """Кнопки модерации заявки (Принять / Отклонить / Обзвон / Изменить)."""
    return disnake.ui.ActionRow(
        disnake.ui.Button(
            label="Принять",
            emoji=e_btn("SUCCESS"),
            style=disnake.ButtonStyle.success,
            custom_id=f"accept_{target_user_id}",
        ),
        disnake.ui.Button(
            label="Отклонить",
            emoji=e_btn("REJECT"),
            style=disnake.ButtonStyle.danger,
            custom_id=f"reject_{target_user_id}",
        ),
        disnake.ui.Button(
            label="Обзвон",
            emoji=e_btn("CALL"),
            style=disnake.ButtonStyle.secondary,
            custom_id=f"call_{target_user_id}",
        ),
        disnake.ui.Button(
            label="Изменить",
            emoji=e_btn("EDIT") or e_btn("SETTINGS"),
            style=disnake.ButtonStyle.secondary,
            custom_id=f"edit_{target_user_id}",
        ),
    )


def _parse_application_fields(text: str) -> dict[str, str]:
    """Обратный парсер текста анкеты в словарь полей.

    Используется для предзаполнения ``EditApplicationModal``. Поддерживает
    многострочные значения — каждое поле берёт все строки между
    своим маркером и следующим, без технической строки ``-# Прикреплено…``.
    """
    fields: dict[str, str] = {
        "name_static": "",
        "age": "",
        "experience": "",
        "otkat": "",
    }
    if not text:
        return fields

    markers: list[tuple[str, str]] = [
        ("name_static", "**Ник и статик:**"),
        ("age", "**Возраст:**"),
        ("experience", "**Опыт в семьях:**"),
        ("otkat", "**Откат:**"),
    ]

    positions: list[tuple[int, str, str]] = []
    for key, marker in markers:
        idx = text.find(marker)
        if idx >= 0:
            positions.append((idx, key, marker))
    positions.sort(key=lambda x: x[0])

    for i, (idx, key, marker) in enumerate(positions):
        start = idx + len(marker)
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        value = text[start:end].strip()
        # Отрезаем техническую строку «-# Прикреплено скринов: ...»,
        # если она прилепилась к последнему полю.
        if "\n-#" in value:
            value = value.split("\n-#", 1)[0].strip()
        fields[key] = value

    return fields


def _extract_media_urls(msg: disnake.Message) -> list[str]:
    """Возвращает список CDN-URL картинок/файлов из v2-сообщения.

    Сначала пробует `msg.attachments` (если Discord вернул их в обычном
    списке). Если пусто — рекурсивно обходит `msg.components`, забирая
    `media.url` / `media.proxy_url` из всех `MediaGallery` и `File`-чайлдов
    (для v2-сообщений Discord прячет файлы внутри компонентов).
    """
    urls: list[str] = []
    seen: set[str] = set()

    def _push(url: str | None) -> None:
        if not url:
            return
        if url.startswith("attachment://"):
            return
        if url in seen:
            return
        seen.add(url)
        urls.append(url)

    for att in getattr(msg, "attachments", None) or []:
        _push(getattr(att, "url", None) or getattr(att, "proxy_url", None))

    def _walk(node) -> None:
        if node is None:
            return
        media = getattr(node, "media", None)
        if media is not None:
            _push(
                getattr(media, "url", None)
                or getattr(media, "proxy_url", None)
            )
        for items_attr in ("items", "children"):
            items = getattr(node, items_attr, None)
            if not items:
                continue
            for child in items:
                _walk(child)

    for component in getattr(msg, "components", None) or []:
        _walk(component)

    return urls


def _extract_application_text(msg: disnake.Message) -> str:
    """Возвращает текст анкеты из Container'а заявки.

    Сначала пытается достать содержимое первого ``TextDisplay`` из
    ``msg.components[0]``. Если сообщение пришло в старом формате
    (через ``embeds``), берёт ``embeds[0].description``.
    """
    try:
        if getattr(msg, "components", None):
            cont = msg.components[0]
            for child in getattr(cont, "children", []) or []:
                content = getattr(child, "content", None)
                if content:
                    return content
    except Exception:
        pass
    try:
        if getattr(msg, "embeds", None):
            return msg.embeds[0].description or ""
    except Exception:
        pass
    return ""


# ==========================================
# COMPONENTS V2: ПАНЕЛЬ "ЗАЯВКИ В СЕМЬЮ"
# ==========================================
def build_application_panel() -> list[disnake.ui.Container]:
    """Сборка стартовой панели заявок одним Container'ом (Components V2).

    Содержит баннер, описание, разделители, подсказки и встроенный
    StringSelect — рендерится единым блоком, как на новом UI Discord.
    """
    banner_url = get_safe_banner()
    children: list = []

    if banner_url:
        children.append(
            disnake.ui.MediaGallery(disnake.MediaGalleryItem(banner_url))
        )

    children.append(
        disnake.ui.TextDisplay(
            "## <a:qq:1485470088600621219>Оформление заявки в семью.\n"
            "Уведомление о приглашении на обзвон отправляется в личные сообщения.\n"
            "Заявки открыты только на 17 сервер Portland <:Portland:1501581436036186244>"
        )
    )

    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(
        disnake.ui.TextDisplay(
            "> В среднем заявки обрабатываются в течение 12-ти часов"
        )
    )

    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(
        disnake.ui.TextDisplay(
            "Следите за статусом набора.\n"
            "**Если возможности заполнить заявку нет – набор закрыт.**\n"
            "**Каждое открытие набора сопровождается тегами в этом канале.**"
        )
    )

    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(
        disnake.ui.TextDisplay(
            "> В случае отказа можете подать заявку повторно через 7 дней"
        )
    )

    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(disnake.ui.TextDisplay("**Подать заявку:**"))

    select = disnake.ui.StringSelect(
        custom_id=APPLICATION_SELECT_CID,
        placeholder="Подать заявку в семью",
        min_values=1,
        max_values=1,
        options=[
            disnake.SelectOption(
                label="Подать заявку в семью",
                description="Откроет форму для заполнения",
                value=APPLICATION_OPTION_CREATE,
                emoji=e_btn("FORM"),
            )
        ],
    )
    children.append(disnake.ui.ActionRow(select))

    return [
        disnake.ui.Container(
            *children, accent_colour=disnake.Colour(SKY_BLUE)
        )
    ]


# ==========================================
# COMPONENTS V2: ПАНЕЛЬ "ТОП РЕКРУТЕРОВ"
# ==========================================
def _toprec_period_meta(
    period_key: str,
) -> tuple[str, datetime.timedelta | None]:
    for key, label, delta in TOPREC_PERIODS:
        if key == period_key:
            return label, delta
    label, delta = TOPREC_PERIODS[0][1], TOPREC_PERIODS[0][2]
    return label, delta


async def _load_toprec_rows(
    period_key: str,
    include_recruiter_ids: list[str] | None = None,
    limit: int = 50,
) -> list[dict]:
    """Возвращает топ рекрутёров для периода.

    Каждая строка — `dict` с ключами:
    - `recruiter_id` (str)
    - `accepted` (int) — принятых заявок
    - `invites` (int) — кандидатов, переведённых на обзвон (уникально по
      заявке: 1 заявка = 1 вызов даже при повторных кликах)
    - `joins` (int) — уникальные кандидаты, которые были в канале обзвона
      одновременно со своим рекрутёром (т.е. реально дошли)
    - `voice_seconds` (int) — суммарное время кандидатов рекрутёра в любом
      из каналов обзвона за период (учитываются только сессии,
      начавшиеся в периоде)

    Если `include_recruiter_ids` передан — все они присутствуют в выдаче
    даже с нулями (используется, чтобы показать всех держателей роли
    «Рекрутёр», а не только тех, кто что-то делал).
    Сортировка: принято / вызовы / время по убыванию.
    """
    _, delta = _toprec_period_meta(period_key)
    if delta is None:
        since_clause = ""
        params_invites: tuple = ()
        since_sessions = "1970-01-01T00:00:00"
    else:
        since = (datetime.datetime.utcnow() - delta).isoformat(
            timespec="seconds"
        )
        since_clause = "AND accepted_at IS NOT NULL AND accepted_at >= ?"
        params_invites = (since,)
        since_sessions = since

    rows_by_rec: dict[str, dict] = {}

    async with aiosqlite.connect("data/database.sqlite") as db:
        # --- accepted ---
        sql_acc = (
            "SELECT recruiter_id, COUNT(*) AS cnt FROM applications "
            "WHERE status = 'accepted' AND recruiter_id IS NOT NULL "
            f"{since_clause} "
            "GROUP BY recruiter_id"
        )
        async with db.execute(sql_acc, params_invites) as cur:
            async for r in cur:
                rid = str(r[0])
                rows_by_rec.setdefault(rid, _empty_toprec_row(rid))
                rows_by_rec[rid]["accepted"] = int(r[1])

        # --- invites: количество уникальных кандидатов, переведённых на обзвон ---
        if delta is None:
            sql_inv = (
                "SELECT recruiter_id, COUNT(DISTINCT candidate_id) "
                "FROM call_invites GROUP BY recruiter_id"
            )
            params_inv: tuple = ()
        else:
            sql_inv = (
                "SELECT recruiter_id, COUNT(DISTINCT candidate_id) "
                "FROM call_invites WHERE called_at >= ? "
                "GROUP BY recruiter_id"
            )
            params_inv = (since_sessions,)
        async with db.execute(sql_inv, params_inv) as cur:
            async for r in cur:
                rid = str(r[0])
                rows_by_rec.setdefault(rid, _empty_toprec_row(rid))
                rows_by_rec[rid]["invites"] = int(r[1])

        # --- voice_seconds: сумма времени кандидатов в каналах обзвона ---
        # SQLite: sessions без left_at считаем «текущими» и закрываем
        # на момент запроса (datetime('now')).
        sql_sec = (
            "SELECT i.recruiter_id, "
            "       SUM(strftime('%s', COALESCE(s.left_at, datetime('now'))) "
            "            - strftime('%s', s.joined_at)) AS total_seconds "
            "FROM call_invites i "
            "JOIN call_voice_sessions s ON s.user_id = i.candidate_id "
            "WHERE s.joined_at >= ? "
            "GROUP BY i.recruiter_id"
        )
        async with db.execute(sql_sec, (since_sessions,)) as cur:
            async for r in cur:
                rid = str(r[0])
                rows_by_rec.setdefault(rid, _empty_toprec_row(rid))
                rows_by_rec[rid]["voice_seconds"] = int(r[1] or 0)

        # --- joins: уникальные кандидаты, которые были в канале обзвона
        # одновременно с тем рекрутёром, который их вызвал ---
        # Реализуем самосвязью по call_voice_sessions: для каждой пары
        # invite (recruiter, candidate) ищем хотя бы одно пересечение
        # отрезков [joined_at, left_at] в одном и том же канале.
        sql_joins = (
            "SELECT i.recruiter_id, COUNT(DISTINCT i.candidate_id) "
            "FROM call_invites i "
            "WHERE EXISTS ( "
            "  SELECT 1 FROM call_voice_sessions sc "
            "  JOIN call_voice_sessions sr "
            "    ON sr.channel_id = sc.channel_id "
            "   AND sr.user_id = i.recruiter_id "
            "   AND sr.joined_at < COALESCE(sc.left_at, datetime('now')) "
            "   AND COALESCE(sr.left_at, datetime('now')) > sc.joined_at "
            "  WHERE sc.user_id = i.candidate_id "
            "    AND sc.joined_at >= ? "
            ") "
            "GROUP BY i.recruiter_id"
        )
        async with db.execute(sql_joins, (since_sessions,)) as cur:
            async for r in cur:
                rid = str(r[0])
                rows_by_rec.setdefault(rid, _empty_toprec_row(rid))
                rows_by_rec[rid]["joins"] = int(r[1])

    # Если передан список «обязательных» рекрутёров — досыпаем нулевые
    # строки. Это позволяет показать всех держателей роли «Рекрутёр»,
    # включая тех, кто ничего ещё не сделал.
    if include_recruiter_ids:
        for rid in include_recruiter_ids:
            rid = str(rid)
            rows_by_rec.setdefault(rid, _empty_toprec_row(rid))

    # сортировка: сперва принято, потом вызовы, потом время. При равенстве
    # — по recruiter_id (стабильно).
    sorted_rows = sorted(
        rows_by_rec.values(),
        key=lambda x: (
            -x["accepted"],
            -x["invites"],
            -x["voice_seconds"],
            x["recruiter_id"],
        ),
    )
    return sorted_rows[:limit]


def _empty_toprec_row(recruiter_id: str) -> dict:
    return {
        "recruiter_id": recruiter_id,
        "accepted": 0,
        "invites": 0,
        "joins": 0,
        "voice_seconds": 0,
    }


def _get_recruiter_role_members(
    guild: "disnake.Guild | None",
) -> list[tuple[str, str]]:
    """Возвращает [(id, display_name)] для всех участников с ролью рекрутёра.

    Если `guild` или роль не найдены — пустой список. Сортировка по
    display_name без учёта регистра для предсказуемого порядка ничейных
    нулевых строк.
    """
    if guild is None:
        return []
    role = guild.get_role(RECRUITER_ROLE_ID)
    if role is None:
        return []
    members = [(str(m.id), m.display_name) for m in role.members]
    members.sort(key=lambda x: x[1].lower())
    return members


_TOPREC_NAME_WIDTH = 16  # длина колонки «Рекрутёр» (display_name)


def _format_toprec_rows(
    rows: list[dict],
    names_by_id: dict[str, str] | None = None,
) -> str:
    """Рендерит таблицу-сетку (моноширинный код-блок) с box-drawing.

    Колонки: №/Рекрутёр/Принято/Вызовы/Заходы/Время. Внутри код-блока
    Discord не разрешает `<@id>`-упоминания, поэтому используем
    `display_name` из `names_by_id` (fallback — `?<id-первые-4>`).
    """
    if not rows:
        return (
            "```\nНет данных за этот период.\n```"
        )
    names_by_id = names_by_id or {}

    def truncate(name: str, width: int) -> str:
        return name if len(name) <= width else name[: width - 1] + "…"

    # Заранее форматируем все ячейки строк
    body_rows: list[tuple[str, str, str, str, str, str]] = []
    for i, row in enumerate(rows):
        rid = row["recruiter_id"]
        name = names_by_id.get(rid) or f"id:{rid[-6:]}"
        body_rows.append(
            (
                f"{i + 1:>2}",
                truncate(name, _TOPREC_NAME_WIDTH),
                str(row["accepted"]),
                str(row["invites"]),
                str(row["joins"]),
                _format_seconds_compact(row["voice_seconds"]),
            )
        )

    headers = ("№", "Рекрутёр", "Принято", "Вызовы", "Заходы", "Время")
    cols = list(zip(headers, *body_rows)) if body_rows else [(h,) for h in headers]
    # ширина колонки = max len ячейки + 2 (по 1 пробелу с каждой стороны)
    widths = [max(len(c) for c in col) for col in cols]
    # минимальная ширина для «Рекрутёр» = _TOPREC_NAME_WIDTH
    widths[1] = max(widths[1], _TOPREC_NAME_WIDTH)

    def hsep(left: str, mid: str, right: str) -> str:
        return left + mid.join("─" * (w + 2) for w in widths) + right

    def hrow(cells: tuple[str, ...]) -> str:
        # № и Принято/Вызовы/Заходы/Время выравниваем по правому краю.
        aligns = ("right", "left", "right", "right", "right", "right")
        parts = []
        for cell, w, align in zip(cells, widths, aligns):
            if align == "right":
                parts.append(f" {cell:>{w}} ")
            else:
                parts.append(f" {cell:<{w}} ")
        return "│" + "│".join(parts) + "│"

    lines: list[str] = ["```"]
    lines.append(hsep("┌", "┬", "┐"))
    lines.append(hrow(headers))
    lines.append(hsep("├", "┼", "┤"))
    for cells in body_rows:
        lines.append(hrow(cells))
    lines.append(hsep("└", "┴", "┘"))
    lines.append("```")
    return "\n".join(lines)


def _build_toprec_buttons(active_key: str) -> disnake.ui.ActionRow:
    buttons: list[disnake.ui.Button] = []
    for key, label, _ in TOPREC_PERIODS:
        buttons.append(
            disnake.ui.Button(
                label=label,
                style=(
                    disnake.ButtonStyle.primary
                    if key == active_key
                    else disnake.ButtonStyle.secondary
                ),
                custom_id=f"{TOPREC_BUTTON_PREFIX}{key}",
                disabled=(key == active_key),
            )
        )
    return disnake.ui.ActionRow(*buttons)


async def _build_toprec_container(
    period_key: str,
    guild: "disnake.Guild | None" = None,
) -> list[disnake.ui.Container]:
    """Главный билдер контейнера `!toprec`.

    Если `guild` передан — подгружает всех держателей роли рекрутёра и
    показывает их в таблице (даже с нулями). Иначе показывает только тех,
    у кого есть статистика.
    """
    label, _ = _toprec_period_meta(period_key)
    role_members = _get_recruiter_role_members(guild)
    rec_ids = [rid for rid, _ in role_members]
    names_by_id = {rid: name for rid, name in role_members}

    rows = await _load_toprec_rows(
        period_key,
        include_recruiter_ids=rec_ids or None,
    )

    children: list = [
        disnake.ui.TextDisplay(
            f"## {e('LOGS')}Топ рекрутеров\n"
            "За выбранный период:\n"
            "• **Принято** — сколько заявок принял рекрутёр\n"
            "• **Вызовы** — уникальных кандидатов, переведённых на обзвон\n"
            "• **Заходы** — кандидаты, что были в канале обзвона **одновременно** с рекрутёром\n"
            "• **Время** — суммарное время кандидатов рекрутёра в каналах обзвона"
        ),
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        ),
        disnake.ui.TextDisplay(
            f"### {label}\n"
            f"{_format_toprec_rows(rows, names_by_id=names_by_id)}"
        ),
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        ),
        _build_toprec_buttons(period_key),
    ]
    return [
        disnake.ui.Container(
            *children, accent_colour=disnake.Colour(SKY_BLUE)
        )
    ]


# ==========================================
# МОДАЛКИ ЗАЯВКИ / ПРИНЯТИЯ / ОТКЛОНЕНИЯ
# ==========================================
class ApplicationModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label=_clip_label("Ваш ник и статик"),
                placeholder="Например: Андрей 1488",
                custom_id="name_static",
                style=disnake.TextInputStyle.short,
                max_length=50,
            ),
            disnake.ui.TextInput(
                label=_clip_label("Возраст"),
                placeholder="Ваш реальный возраст",
                custom_id="age",
                style=disnake.TextInputStyle.short,
                max_length=10,
            ),
            disnake.ui.TextInput(
                label=_clip_label(
                    "Был ли опыт в семьях? Если был то в каких."
                ),
                placeholder="Да, состоял в...",
                custom_id="experience",
                style=disnake.TextInputStyle.short,
                max_length=200,
            ),
            _file_upload_label(
                f"Скрины персонажей (1–{MAX_APPLICATION_FILES})",
                required=True,
            ),
            disnake.ui.TextInput(
                label=_clip_label("Откат (капт, мцл, гг от 5 минут)"),
                placeholder="Ссылка на видео (YouTube, Drive)",
                custom_id="otkat",
                style=disnake.TextInputStyle.paragraph,
                max_length=300,
            ),
        ]
        super().__init__(title="Подать заявку в семью", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        files, preview = await _resolve_modal_files(inter)
        if not files:
            return await inter.followup.send(
                components=simple_container(
                    f"{e('REJECT')}Нужно прикрепить хотя бы одно "
                    "фото персонажа.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )

        category = inter.guild.get_channel(
            int(config["CHANNELS"]["APPLICATION_REVIEW"])
        )
        ticket_channel = await inter.guild.create_text_channel(
            name=f"заявка-{inter.author.name}",
            category=category,
            topic=str(inter.author.id),
        )

        await ticket_channel.set_permissions(
            inter.guild.default_role, read_messages=False
        )
        await ticket_channel.set_permissions(
            inter.author,
            read_messages=True,
            send_messages=True,
            attach_files=True,
        )

        for r_id in config["ROLES"]["MODERATOR"]:
            mod_role = inter.guild.get_role(int(r_id))
            if mod_role:
                await ticket_channel.set_permissions(
                    mod_role, read_messages=True, send_messages=True
                )

        desc_lines = [
            "**Новая заявка**",
            "",
            f"**От:** {inter.author.mention}",
            f"**Ник и статик:** {inter.text_values['name_static']}",
            f"**Возраст:** {inter.text_values['age']}",
            f"**Опыт в семьях:** {inter.text_values['experience']}",
            f"**Откат:** {inter.text_values['otkat']}",
            f"-# Прикреплено скринов: **{len(files)}**",
        ]

        children: list = [
            disnake.ui.TextDisplay("\n".join(desc_lines)),
            disnake.ui.Separator(
                divider=True, spacing=disnake.SeparatorSpacing.small
            ),
        ]
        children.extend(preview)
        if preview:
            children.append(
                disnake.ui.Separator(
                    divider=True, spacing=disnake.SeparatorSpacing.small
                )
            )
        children.append(_build_review_buttons(inter.author.id))

        cont = [
            disnake.ui.Container(
                *children, accent_colour=ORANGE_COLOR
            )
        ]

        # Строгий пинг одной роли при подаче заявки — по умолчанию
        # «Рекрутер» (1217923581904687184), можно переопределить
        # через config["ROLES"]["APPLICATION_PING"].
        ping_role_id = int(
            config.get("ROLES", {}).get(
                "APPLICATION_PING", 1217923581904687184
            )
        )
        # У v2-сообщений с components нельзя одновременно использовать
        # content/embed, поэтому пинг роли идёт отдельным сообщением.
        try:
            await ticket_channel.send(
                content=(
                    f"<@&{ping_role_id}>\nНовая заявка от "
                    f"{inter.author.mention}"
                ),
                allowed_mentions=disnake.AllowedMentions(
                    roles=[disnake.Object(id=ping_role_id)],
                    users=True,
                    everyone=False,
                ),
            )
        except Exception:
            pass
        msg = await ticket_channel.send(
            components=cont,
            files=files,
        )

        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute(
                "INSERT INTO applications (user_id, message_id, status) VALUES (?, ?, ?)",
                (str(inter.author.id), str(msg.id), "pending"),
            )
            await db.commit()

        await inter.followup.send(
            f"{e('SUCCESS')}Ваша заявка успешно отправлена: {ticket_channel.mention}",
            ephemeral=True,
        )


class EditApplicationModal(disnake.ui.Modal):
    """Модалка «Изменить» для модератора.

    Открывается по клику по кнопке ``edit_<id>`` под уже
    существующей заявкой. Подставляет текущие значения и на сабмите
    пересобирает текстовый блок v2-Container'a, сохраняя скрины
    (URL-ы берутся из текущего эмбеда) и кнопки модерации.
    """

    def __init__(
        self,
        message: disnake.Message,
        target_user_id: int,
        current: dict[str, str],
    ):
        self.message = message
        self.target_user_id = target_user_id

        components = [
            disnake.ui.TextInput(
                label=_clip_label("Ваш ник и статик"),
                placeholder="Например: Андрей 1488",
                custom_id="name_static",
                style=disnake.TextInputStyle.short,
                max_length=50,
                value=(current.get("name_static", "") or "")[:50],
            ),
            disnake.ui.TextInput(
                label=_clip_label("Возраст"),
                placeholder="Ваш реальный возраст",
                custom_id="age",
                style=disnake.TextInputStyle.short,
                max_length=10,
                value=(current.get("age", "") or "")[:10],
            ),
            disnake.ui.TextInput(
                label=_clip_label(
                    "Был ли опыт в семьях? Если был то в каких."
                ),
                placeholder="Да, состоял в...",
                custom_id="experience",
                style=disnake.TextInputStyle.paragraph,
                max_length=200,
                value=(current.get("experience", "") or "")[:200],
            ),
            disnake.ui.TextInput(
                label=_clip_label("Откат (капт, мцл, гг от 5 минут)"),
                placeholder="Ссылка на видео (YouTube, Drive)",
                custom_id="otkat",
                style=disnake.TextInputStyle.paragraph,
                max_length=300,
                value=(current.get("otkat", "") or "")[:300],
            ),
        ]
        super().__init__(
            title="Изменение анкеты", components=components
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        # Старый текст анкеты нужен, чтобы вытащить строку «От:» и
        # бывшее количество скринов; остальные поля берём из inter.
        app_text = ""
        try:
            app_text = _extract_application_text(self.message)
        except Exception:
            app_text = ""

        from_line = f"**От:** <@{self.target_user_id}>"
        for ln in (app_text or "").splitlines():
            stripped = ln.strip()
            if stripped.startswith("**От:**"):
                from_line = stripped
                break

        screenshot_urls: list[str] = _extract_media_urls(self.message)
        attached_count = len(screenshot_urls)
        # Если в старом тексте было явно указано количество —
        # отдаём ему приоритет (на случай, если _extract_media_urls
        # не всё нашёл).
        for ln in (app_text or "").splitlines():
            stripped = ln.strip()
            if stripped.startswith("-# Прикреплено скринов:"):
                import re as _re

                m = _re.search(r"\*\*(\d+)\*\*", stripped)
                if m:
                    attached_count = int(m.group(1))
                break

        desc_lines = [
            "**Новая заявка**",
            "",
            from_line,
            f"**Ник и статик:** {inter.text_values['name_static']}",
            f"**Возраст:** {inter.text_values['age']}",
            f"**Опыт в семьях:** {inter.text_values['experience']}",
            f"**Откат:** {inter.text_values['otkat']}",
            f"-# Прикреплено скринов: **{attached_count}**",
        ]

        children: list = [
            disnake.ui.TextDisplay("\n".join(desc_lines)),
            disnake.ui.Separator(
                divider=True, spacing=disnake.SeparatorSpacing.small
            ),
        ]
        if screenshot_urls:
            children.append(
                disnake.ui.MediaGallery(
                    *[
                        disnake.MediaGalleryItem(u)
                        for u in screenshot_urls
                    ]
                )
            )
            children.append(
                disnake.ui.Separator(
                    divider=True, spacing=disnake.SeparatorSpacing.small
                )
            )
        children.append(_build_review_buttons(self.target_user_id))

        cont = [
            disnake.ui.Container(*children, accent_colour=ORANGE_COLOR)
        ]

        try:
            await self.message.edit(components=cont)
        except Exception as ex:
            return await inter.followup.send(
                components=simple_container(
                    f"{e('ERROR')}Не удалось обновить анкету: {ex!r}",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )

        await inter.followup.send(
            components=simple_container(
                f"{e('SUCCESS')}Анкета обновлена.", SUCCESS_COLOR
            ),
            ephemeral=True,
        )


# ==========================================
# ACADEMY / YOUNG: helpers and persistent UI
# ==========================================

def _normalize_channel_name(name: str) -> str:
    """Нормализует строку под Discord-имя канала.

    Discord сам приводит к нижнему регистру и режет недопустимые символы,
    но мы делаем это руками, чтобы префикс гарантированно остался.
    Кириллицу оставляем — Discord сам её сохранит.
    """
    import re as _re

    cleaned = _re.sub(r"\s+", "-", (name or "").strip().lower())
    cleaned = _re.sub(r"[^\w\-\u0400-\u04FF]", "", cleaned)
    return cleaned[:90] or "user"


def _get_moderator_role_ids() -> list[int]:
    """Возвращает ID-роли модераторов из config (admins + moderators)."""
    out: list[int] = []
    roles_cfg = config.get("ROLES", {}) or {}
    for key in ("ADMIN", "MODERATOR", "MODERATORS", "STAFF"):
        for rid in roles_cfg.get(key, []) or []:
            try:
                out.append(int(rid))
            except Exception:
                continue
    # Роль рекрутёра тоже считаем модерацией для целей academy.
    out.append(RECRUITMENT_ROLE_ID)
    return list({rid for rid in out if rid})


def _author_is_academy_moderator(member: disnake.Member | None) -> bool:
    """Проверяет, что у участника есть хотя бы одна модер-роль."""
    if member is None:
        return False
    if getattr(member, "guild_permissions", None) and (
        member.guild_permissions.administrator
        or member.guild_permissions.manage_channels
    ):
        return True
    allowed = set(_get_moderator_role_ids())
    return any(r.id in allowed for r in member.roles)


def _is_channel_in_category_chain(
    guild: disnake.Guild,
    channel: disnake.TextChannel,
    base_category_id: int,
) -> bool:
    """Принадлежит ли канал «цепочке» категории base_category_id.

    Цепочка = базовая категория + её клоны вида `<name>-2`, `<name>-3`...
    (создаются при переполнении). Используется в `/fix_academy`,
    чтобы понять, нужно ли переносить канал в другую категорию.
    """
    base = guild.get_channel(int(base_category_id))
    if not isinstance(base, disnake.CategoryChannel):
        return False
    if channel.category_id == base.id:
        return True
    if channel.category is None:
        return False
    base_name = base.name.lower()
    cur_name = channel.category.name.lower()
    if cur_name == base_name:
        return True
    if cur_name.startswith(base_name + "-"):
        suffix = cur_name[len(base_name) + 1:]
        if suffix.isdigit():
            return True
    return False


async def _pick_category_with_slots(
    guild: disnake.Guild,
    base_category_id: int,
) -> disnake.CategoryChannel | None:
    """Возвращает категорию для нового канала; при переполнении создаёт «-N»."""
    base = guild.get_channel(int(base_category_id))
    if not isinstance(base, disnake.CategoryChannel):
        return None
    if len(base.channels) < DISCORD_CATEGORY_MAX_CHANNELS:
        return base

    base_name = base.name
    for n in range(2, 100):
        candidate_name = f"{base_name}-{n}"
        candidate = disnake.utils.get(guild.categories, name=candidate_name)
        if candidate is None:
            try:
                return await guild.create_category(
                    name=candidate_name,
                    overwrites=base.overwrites,
                    position=base.position + n - 1,
                    reason="academy: переполнение базовой категории",
                )
            except Exception as ex:
                print(f"[academy] create_category failed: {ex!r}")
                return None
        if len(candidate.channels) < DISCORD_CATEGORY_MAX_CHANNELS:
            return candidate
    return None


def _build_academy_card_container(
    member: disnake.Member,
    accepted_at_ts: int,
    image_url: str | None = ACADEMY_REFERENCE_IMAGE,
    show_buttons: bool = True,
    footer_text: str | None = None,
) -> list[disnake.ui.Container]:
    """Собирает v2-Container для личного канала кандидата.

    Включает правила (header + young + academy), личную карточку
    (ник pong / роли / дата принятия) и кнопки `Повысить`/`Выгнать`.
    """
    rules_text = (
        ACADEMY_HEADER_TEXT
        + "\n\n"
        + ACADEMY_YOUNG_RULES
        + "\n\n"
        + ACADEMY_ACADEMY_RULES
    )

    role_mentions = [
        r.mention
        for r in sorted(
            member.roles, key=lambda x: x.position, reverse=True
        )
        if r != member.guild.default_role
    ]
    if not role_mentions:
        roles_value = "—"
    else:
        # Чтобы не упереться в лимит 4000 на TextDisplay — отдаём максимум
        # 15 ролей, остальное — счётчик «и ещё N».
        head = role_mentions[:15]
        roles_value = ", ".join(head)
        if len(role_mentions) > 15:
            roles_value += f", и ещё {len(role_mentions) - 15}"

    card_text = (
        "**Личная карточка**\n"
        f"**Ник:** {member.mention}\n"
        f"**Роли:** {roles_value}\n"
        f"**Принят:** <t:{accepted_at_ts}:F>"
    )
    if footer_text:
        card_text += f"\n{footer_text}"

    children: list = [disnake.ui.TextDisplay(rules_text)]
    if image_url:
        children.append(
            disnake.ui.Separator(divider=True)
        )
        children.append(
            disnake.ui.MediaGallery(disnake.MediaGalleryItem(image_url))
        )
    children.append(disnake.ui.Separator(divider=True))
    children.append(disnake.ui.TextDisplay(card_text))

    if show_buttons:
        children.append(disnake.ui.Separator(divider=True))
        children.append(
            disnake.ui.ActionRow(
                disnake.ui.Button(
                    label="Повысить",
                    emoji=e_btn("PROMOTE") or e_btn("SUCCESS"),
                    style=disnake.ButtonStyle.success,
                    custom_id=f"academy_promote_{member.id}",
                ),
                disnake.ui.Button(
                    label="Выгнать",
                    emoji=e_btn("REJECT"),
                    style=disnake.ButtonStyle.danger,
                    custom_id=f"academy_expel_{member.id}",
                ),
            )
        )

    return [
        disnake.ui.Container(*children, accent_colour=ORANGE_COLOR)
    ]


def _build_academy_overwrites(
    guild: disnake.Guild, member: disnake.Member
) -> dict:
    """Строгие overwrites для канала академии.

    Доступ разрешён только:
    * кандидату (видит/читает; пишет только в ветках);
    * роли `RECRUITMENT_ROLE_ID` (полный доступ);
    * боту (обслуживание канала и веток).

    Остальные модераторские роли из config больше НЕ добавляются в
    overwrites — по требованию (строгий доступ). Админы всё равно
    видят канал через право `administrator` в Discord.
    """
    overwrites: dict = {
        guild.default_role: disnake.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
        ),
        member: disnake.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=False,  # в корень канала писать нельзя
            send_messages_in_threads=True,
            create_public_threads=False,
            create_private_threads=False,
            add_reactions=True,
            attach_files=True,
            embed_links=True,
        ),
    }
    bot_member = guild.me
    if bot_member is not None:
        overwrites[bot_member] = disnake.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            send_messages_in_threads=True,
            manage_messages=True,
            manage_threads=True,
            manage_channels=True,
            # Без этого права бот не сможет создавать ветки в канале,
            # даже имея `manage_threads` (Discord различает CREATE_*_THREADS
            # и MANAGE_THREADS).
            create_public_threads=True,
            create_private_threads=True,
        )
    recruit_role = guild.get_role(RECRUITMENT_ROLE_ID)
    if recruit_role is not None:
        overwrites[recruit_role] = disnake.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            send_messages_in_threads=True,
            manage_messages=True,
            manage_threads=True,
            create_public_threads=True,
            create_private_threads=True,
        )
    return overwrites


async def _ensure_academy_threads(
    channel: disnake.TextChannel,
) -> tuple[list[str], list[str]]:
    """Создаёт недостающие ветки `ACADEMY_THREAD_NAMES` в канале.

    Возвращает кортеж ``(created, errors)``:
    * ``created`` — имена реально созданных веток;
    * ``errors`` — строки вида ``"имя: текст ошибки"`` для веток, которые
      не удалось создать (показывает причину — Forbidden, лимит и т.п.).

    Активные и архивные ветки учитываются (регистр имени игнорируется).
    Между запросами на создание стоит маленькая пауза, чтобы не словить
    rate-limit от Discord.
    """
    existing_names: set[str] = set()
    for t in getattr(channel, "threads", []):
        existing_names.add(t.name.casefold())
    try:
        async for t in channel.archived_threads(limit=100):
            existing_names.add(t.name.casefold())
    except Exception as ex:
        print(
            f"[academy] archived_threads {channel.name!r} failed: "
            f"{ex!r}"
        )

    created: list[str] = []
    errors: list[str] = []

    # Discord поддерживает 10080 (неделя) для всех серверов c 2022,
    # но на старых boost-тирах могут быть жесты — fallback'ы на случай.
    duration_candidates = (10080, 4320, 1440, 60)

    for idx, name in enumerate(ACADEMY_THREAD_NAMES):
        if name.casefold() in existing_names:
            continue

        last_exc: Exception | None = None
        ok = False
        for duration in duration_candidates:
            try:
                await channel.create_thread(
                    name=name,
                    type=disnake.ChannelType.public_thread,
                    auto_archive_duration=duration,
                    reason="academy: восстановление личной ветки",
                )
                ok = True
                break
            except disnake.HTTPException as ex:
                last_exc = ex
                # 50035 = Invalid Form Body (часто на auto_archive_duration).
                # 50013 = Missing Permissions — менять duration бесполезно.
                if getattr(ex, "code", None) == 50013:
                    break
                continue
            except Exception as ex:
                last_exc = ex
                break

        if ok:
            created.append(name)
        else:
            err_repr = repr(last_exc) if last_exc else "unknown"
            errors.append(f"{name}: {err_repr}")
            print(
                f"[academy] create_thread {name!r} in "
                f"{channel.name!r} failed: {err_repr}\n"
                + (traceback.format_exc() if last_exc else "")
            )

        # Небольшая пауза между запросами, чтобы не словить 429.
        if idx < len(ACADEMY_THREAD_NAMES) - 1:
            await asyncio.sleep(0.4)

    return created, errors


async def _resolve_academy_candidate(
    guild: disnake.Guild,
    channel: disnake.TextChannel,
    bot_id: int,
) -> disnake.Member | None:
    """Определяет владельца академического канала.

    1. Пытается прочитать ID из `channel.topic` (бот кладёт его при
       создании).
    2. Если в topic пусто/мусор — сканирует permission overwrites
       канала: ищет первый `Member` overrride, не являющийся ботом, с
       разрешением `view_channel`.
    """
    topic = (channel.topic or "").strip()
    try:
        target_id = int(topic)
    except Exception:
        target_id = None

    member: disnake.Member | None = None
    if target_id is not None:
        member = guild.get_member(target_id)
        if member is None:
            try:
                member = await guild.fetch_member(target_id)
            except Exception:
                member = None

    if member is not None:
        return member

    for target, overwrite in channel.overwrites.items():
        if not isinstance(target, disnake.Member):
            continue
        if target.id == bot_id:
            continue
        # Только пара allow=view_channel — пропускаем `denied` записи.
        allow, _deny = overwrite.pair()
        if allow.view_channel:
            return target

    return None


async def _refresh_academy_card_message(
    channel: disnake.TextChannel,
    member: disnake.Member,
    bot_id: int,
    footer_text: str | None,
) -> str:
    """Обновляет «карточку» в личном канале кандидата.

    Логика:
    1. Собираем все ботовские сообщения в канале.
    2. Ищем среди них верхнее V2-сообщение (с components) — нашу
       живую карточку. Если нашли и редактирование проходит — это путь
       ``"edited"``. Все остальные ботовские сообщения чистим.
    3. Если подходящего V2-сообщения нет или ``edit`` падает
       (старое сообщение без V2-флага), удаляем ВСЕ ботовские
       сообщения (включая системные ``thread_created``) и шлём новый
       эмбед верхом — это путь ``"recreated"`` (или ``"sent"`` в
       пустом канале).

    ВАЖНО: ветки (`disnake.Thread`) не удаляются. Удаление системного
    сообщения «thread_created» от Discord НЕ удаляет саму ветку — ветки
    это отдельные сущности со своими ID, они выживают чистку.
    """
    def _is_safe_to_delete(m: disnake.Message) -> bool:
        """Безопасно ли удалять сообщение без повреждения веток.

        Discord удаляет ветку вместе с её anchor-сообщением
        (или сообщением, из которого ветка была создана). Чтобы
        ветки НЕ пропадали, никогда не удаляем системные
        thread_created и сообщения с флагом has_thread/атрибутом .thread.
        """
        if m.type != disnake.MessageType.default:
            return False
        try:
            if getattr(m.flags, "has_thread", False):
                return False
        except Exception:
            pass
        if getattr(m, "thread", None) is not None:
            return False
        return True

    bot_msgs: list[disnake.Message] = []
    async for msg in channel.history(limit=100, oldest_first=True):
        if msg.author.id != bot_id:
            continue
        bot_msgs.append(msg)

    # Пытаемся найти живую карточку (бот + default + components).
    target_msg: disnake.Message | None = None
    for m in bot_msgs:
        if m.type != disnake.MessageType.default:
            continue
        if m.components:
            target_msg = m
            break

    accepted_at_ts = (
        int(target_msg.created_at.timestamp())
        if target_msg is not None
        else int(datetime.datetime.utcnow().timestamp())
    )
    new_cont = _build_academy_card_container(
        member=member,
        accepted_at_ts=accepted_at_ts,
        footer_text=footer_text,
    )

    edited_in_place = False
    if target_msg is not None:
        try:
            await target_msg.edit(components=new_cont)
            edited_in_place = True
        except Exception:
            edited_in_place = False

    if edited_in_place:
        # Карточка обновлена на своём месте. Чистим только
        # «безопасные» ботовские текстовые сообщения (без веток),
        # чтобы случайно не удалить thread-anchor.
        for m in bot_msgs:
            if m.id == target_msg.id:
                continue
            if not _is_safe_to_delete(m):
                continue
            try:
                await m.delete()
            except Exception as ex:
                print(
                    f"[academy] cleanup delete {channel.name!r} "
                    f"failed: {ex!r}"
                )
        return "edited"

    # Редактировать не получилось или V2-сообщения не было:
    # чистим ботовские default-сообщения (без anchor-веток) и
    # шлём эмбед «с нуля». Системные thread_created остаются.
    had_msgs = any(_is_safe_to_delete(m) for m in bot_msgs)
    for m in bot_msgs:
        if not _is_safe_to_delete(m):
            continue
        try:
            await m.delete()
        except Exception as ex:
            print(
                f"[academy] cleanup delete {channel.name!r} "
                f"failed: {ex!r}"
            )
    try:
        await channel.send(components=new_cont)
        return "recreated" if had_msgs else "sent"
    except Exception as ex:
        print(
            f"[academy] refresh send {channel.name!r} failed: {ex!r}"
        )
        return "failed"


async def _setup_academy_channel(
    guild: disnake.Guild,
    member: disnake.Member,
    moderator: disnake.Member | disnake.User,
    stage: str = "young",
    accepted_at_ts: int | None = None,
) -> disnake.TextChannel | None:
    """Создаёт личный канал кандидата с ветками и эмбедом.

    Канал не виден `@everyone`. Кандидат видит канал и читает историю,
    но **писать в корень не может** — может только в трёх публичных
    ветках (`РП` / `Арена` / `Общение с рекрутёром`).
    Доступ имеют только кандидат и роль `RECRUITMENT_ROLE_ID`.
    """
    base_category_id = (
        YOUNG_CATEGORY_ID if stage == "young" else ACADEMY_CATEGORY_ID
    )
    prefix = "young" if stage == "young" else "академ"
    category = await _pick_category_with_slots(guild, base_category_id)
    if category is None:
        print(
            f"[academy] no free category for stage={stage}, "
            f"base_id={base_category_id}"
        )
        return None

    base_name = _normalize_channel_name(member.display_name)
    channel_name = f"{prefix}-{base_name}"[:95]

    overwrites = _build_academy_overwrites(guild, member)

    try:
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            topic=str(member.id),
            overwrites=overwrites,
            reason=(
                f"academy {stage}: {member} ({member.id}) "
                f"by {moderator}"
            ),
        )
    except Exception as ex:
        print(f"[academy] create_text_channel failed: {ex!r}")
        return None

    if accepted_at_ts is None:
        accepted_at_ts = int(datetime.datetime.utcnow().timestamp())
    try:
        cont = _build_academy_card_container(
            member=member, accepted_at_ts=accepted_at_ts
        )
        await channel.send(components=cont)
    except Exception as ex:
        print(f"[academy] send main embed failed: {ex!r}")

    # Создаём публичные ветки (РП / Арена / Общение с рекрутёром).
    # Используем общий helper, чтобы логика создания была единой
    # (повторные попытки duration, паузы между запросами, лог).
    try:
        await _ensure_academy_threads(channel)
    except Exception as ex:
        print(
            f"[academy] ensure threads for {channel.name!r} failed: "
            f"{ex!r}"
        )

    return channel


class FinalRoleSelectView(disnake.ui.View):
    """Эфемерный select для выдачи финальной роли вместо `ACADEMY`.

    Видит только модератор, который нажал «Повысить» у кандидата с
    `ACADEMY`. После выбора:
    - снимается роль `ACADEMY` (и `YOUNG`, если осталась),
    - выдаётся выбранная роль,
    - перерисовывается карточка в личном канале кандидата.
    """

    def __init__(
        self,
        member: disnake.Member,
        message_to_refresh: disnake.Message,
    ):
        super().__init__(timeout=10 * 60)
        self.member = member
        self.message_to_refresh = message_to_refresh

        # Доступные роли: ниже бота, не managed, не @everyone,
        # не YOUNG/ACADEMY.
        bot_member = member.guild.me
        bot_top = bot_member.top_role.position if bot_member else 0
        candidates: list[disnake.Role] = []
        for role in sorted(
            member.guild.roles, key=lambda r: r.position, reverse=True
        ):
            if role.is_default():
                continue
            if role.managed:
                continue
            if role.id in (YOUNG_ROLE_ID, ACADEMY_ROLE_ID):
                continue
            if bot_member is not None and role.position >= bot_top:
                continue
            candidates.append(role)
            if len(candidates) >= 25:
                break

        options = [
            disnake.SelectOption(label=r.name[:100], value=str(r.id))
            for r in candidates
        ] or [
            disnake.SelectOption(
                label="— нет доступных ролей —",
                value="none",
                default=True,
            )
        ]
        select = disnake.ui.Select(
            placeholder="Выберите финальную роль для кандидата",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="academy_final_role_select",
        )
        select.callback = self.on_select  # type: ignore[assignment]
        self.add_item(select)

    async def on_select(self, inter: disnake.MessageInteraction):
        if not _author_is_academy_moderator(
            inter.author if isinstance(inter.author, disnake.Member) else None
        ):
            return await inter.response.send_message(
                f"{e('REJECT')}Только модераторы могут выдавать роли.",
                ephemeral=True,
            )
        values = list(getattr(inter, "values", None) or [])
        if not values or values[0] == "none":
            return await inter.response.send_message(
                f"{e('REJECT')}Выберите роль.", ephemeral=True
            )
        try:
            role_id = int(values[0])
        except Exception:
            return await inter.response.send_message(
                f"{e('ERROR')}Некорректное значение.", ephemeral=True
            )
        role = inter.guild.get_role(role_id) if inter.guild else None
        if not role:
            return await inter.response.send_message(
                f"{e('ERROR')}Роль не найдена.", ephemeral=True
            )

        # Снимаем YOUNG/ACADEMY и выдаём выбранную роль.
        try:
            to_remove: list[disnake.Role] = []
            for rid in (YOUNG_ROLE_ID, ACADEMY_ROLE_ID):
                r = inter.guild.get_role(rid)
                if r and r in self.member.roles:
                    to_remove.append(r)
            if to_remove:
                await self.member.remove_roles(
                    *to_remove, reason="Финал академии"
                )
            await self.member.add_roles(role, reason="Финал академии")
        except disnake.Forbidden:
            return await inter.response.send_message(
                f"{e('REJECT')}Нет прав на изменение ролей.",
                ephemeral=True,
            )
        except Exception as ex:
            return await inter.response.send_message(
                f"{e('ERROR')}Ошибка: {ex!r}", ephemeral=True
            )

        try:
            new_cont = _build_academy_card_container(
                member=self.member,
                accepted_at_ts=int(
                    datetime.datetime.utcnow().timestamp()
                ),
                show_buttons=False,
                footer_text=(
                    f"**Этап:** Завершён — выдана роль {role.mention}"
                ),
            )
            await self.message_to_refresh.edit(components=new_cont)
        except Exception:
            pass

        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        try:
            await inter.response.edit_message(
                content=f"{e('SUCCESS')}Выдана финальная роль {role.mention}.",
                view=self,
            )
        except disnake.HTTPException:
            try:
                await inter.followup.send(
                    f"{e('SUCCESS')}Выдана финальная роль {role.mention}.",
                    ephemeral=True,
                )
            except Exception:
                pass


class AcceptModal(disnake.ui.Modal):
    def __init__(self, target_user_id: str, message_id: str):
        self.target_user_id = target_user_id
        self.message_id = message_id
        components = [
            disnake.ui.TextInput(
                label="Введите новый ник",
                custom_id="new_nickname",
                style=disnake.TextInputStyle.short,
            )
        ]
        super().__init__(title="Смена никнейма", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        target_id = int(self.target_user_id)

        member = inter.guild.get_member(target_id)
        if not member:
            try:
                member = await inter.guild.fetch_member(target_id)
            except Exception:
                pass

        new_nickname = inter.text_values["new_nickname"]
        nick_status = f"{e('WARNING')}Игрок не найден"
        role_status = f"{e('WARNING')}Игрок не найден"

        if member:
            try:
                await member.edit(nick=new_nickname)
                nick_status = f"{e('SUCCESS')}Изменен на `{new_nickname}`"
            except disnake.Forbidden:
                nick_status = (
                    f"{e('WARNING')}Не хватает прав (роль бота ниже игрока)"
                )
            except Exception:
                nick_status = f"{e('WARNING')}Ошибка"

            try:
                roles_to_add = []

                for specific_role_id in config.get("ROLES", {}).get(
                    "FAMILY_ROLES", []
                ):
                    role = inter.guild.get_role(int(specific_role_id))
                    if role:
                        roles_to_add.append(role)

                for r_id in config.get("ROLES", {}).get("STAFF", []):
                    role = inter.guild.get_role(int(r_id))
                    if role and role not in roles_to_add:
                        roles_to_add.append(role)

                # На приём — выдаём роль YOUNG (1 часть академии).
                # Роль ACADEMY (2 часть) выдаётся только по кнопке
                # «Повысить» в личном канале кандидата.
                young_role_id = int(
                    config.get("ACADEMY", {}).get(
                        "RANK_YOUNG", YOUNG_ROLE_ID
                    )
                )
                young_role = inter.guild.get_role(young_role_id)
                if young_role and young_role not in roles_to_add:
                    roles_to_add.append(young_role)

                if roles_to_add:
                    await member.add_roles(*roles_to_add)
                    role_status = f"{e('SUCCESS')}Выданы успешно"
                else:
                    role_status = (
                        f"{e('WARNING')}Роли не найдены на сервере/конфиге"
                    )
            except disnake.Forbidden:
                role_status = (
                    f"{e('WARNING')}Нет прав (поднимите роль бота выше)"
                )
            except Exception:
                role_status = f"{e('WARNING')}Неизвестная ошибка"

            try:
                academy_panel_id = config.get("ACADEMY", {}).get(
                    "PANEL_CHANNEL"
                )
                desc_text = (
                    f"Добро пожаловать в семью **Trappa Famq**!\n"
                    f"Вам выдана роль Академии.\n\n"
                    f"**{e('FIRE')}Что делать дальше?**\n"
                    f"Обязательно перейдите в канал <#{academy_panel_id}> "
                    f"и нажмите кнопку **«Начать прохождение»**, чтобы бот "
                    f"создал вам личную ветку и выдал список заданий для повышения."
                )

                dm_embed = disnake.Embed(
                    title=f"{e('PARTY')}Ваша заявка ОДОБРЕНА!",
                    description=desc_text,
                    color=disnake.Color.green(),
                )
                logo = get_safe_logo()
                if logo:
                    dm_embed.set_thumbnail(url=logo)
                await member.send(embed=dm_embed)
            except Exception:
                pass

        is_farm = False
        async with aiosqlite.connect("data/database.sqlite") as db:
            async with db.execute(
                "SELECT candidate_id FROM rewarded_candidates WHERE candidate_id = ?",
                (str(self.target_user_id),),
            ) as cursor:
                if await cursor.fetchone():
                    is_farm = True

            if not is_farm:
                await db.execute(
                    "INSERT INTO user_coins (user_id, balance) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "balance = balance + ?",
                    (
                        str(inter.author.id),
                        ACCEPT_COIN_REWARD,
                        ACCEPT_COIN_REWARD,
                    ),
                )
                await db.execute(
                    "INSERT INTO rewarded_candidates (candidate_id) "
                    "VALUES (?)",
                    (str(self.target_user_id),),
                )

            accepted_at_iso = datetime.datetime.utcnow().isoformat(
                timespec="seconds"
            )
            await db.execute(
                "UPDATE applications SET status = ?, recruiter_id = ?, "
                "accepted_at = ? WHERE message_id = ?",
                (
                    "accepted",
                    str(inter.author.id),
                    accepted_at_iso,
                    self.message_id,
                ),
            )
            await db.commit()

        app_text = ""
        app_msg = None
        try:
            app_msg = await inter.channel.fetch_message(int(self.message_id))
            app_text = _extract_application_text(app_msg)
        except Exception:
            pass

        # Общие данные для всех форвардов: строки из анкеты и URLы скринов.
        from_line = ""
        nick_static_line = ""
        if app_text:
            for ln in app_text.splitlines():
                stripped = ln.strip()
                if not stripped:
                    continue
                if stripped.startswith("**От:**"):
                    from_line = stripped
                elif stripped.startswith("**Ник и статик:**"):
                    nick_static_line = stripped
        if not from_line:
            from_line = f"**От:** <@{self.target_user_id}>"

        screenshot_urls: list[str] = []
        if app_msg is not None:
            screenshot_urls = _extract_media_urls(app_msg)

        # Объявление о принятии в канал семьи: тихий пинг + первая строка
        # анкеты + скриншоты кандидата из исходной заявки.
        welcome_channel_id = int(
            config.get("CHANNELS", {}).get(
                "FAMILY_WELCOME_CHANNEL", 1503157600857100359
            )
        )
        welcome_channel = inter.bot.get_channel(welcome_channel_id)
        if not welcome_channel:
            try:
                welcome_channel = await inter.bot.fetch_channel(
                    welcome_channel_id
                )
            except Exception:
                welcome_channel = None

        if welcome_channel:
            welcome_text = from_line
            if nick_static_line:
                welcome_text += "\n" + nick_static_line
            welcome_text += f"\n**Принял:** {inter.author.mention}"

            # 1) Тихий пинг отдельным сообщением (silent=True — без push-
            #    уведомления, но @ остаётся как ссылка-меншн).
            try:
                await welcome_channel.send(
                    content=f"<@{self.target_user_id}>",
                    allowed_mentions=disnake.AllowedMentions(
                        users=True, roles=False, everyone=False
                    ),
                    flags=disnake.MessageFlags(
                        suppress_notifications=True
                    ),
                )
            except Exception:
                pass

            # 2) V2 Container со скриншотами и блоком «От / Ник-Статик-
            #    Возраст / Принял».
            body_children: list = []
            if welcome_text:
                body_children.append(disnake.ui.TextDisplay(welcome_text))
            if screenshot_urls:
                body_children.append(
                    disnake.ui.MediaGallery(
                        *[
                            disnake.MediaGalleryItem(u)
                            for u in screenshot_urls
                        ]
                    )
                )
            if body_children:
                body_cont = [
                    disnake.ui.Container(
                        *body_children, accent_colour=SUCCESS_COLOR
                    )
                ]
                try:
                    await welcome_channel.send(
                        components=body_cont,
                        flags=disnake.MessageFlags(
                            suppress_notifications=True
                        ),
                    )
                except Exception:
                    pass

        # Отдельный канал для скринов принятых кандидатов (безшумно).
        # ID можно переопределить в config["CHANNELS"]["SCREENS_CHANNEL"].
        screens_channel_id = int(
            config.get("CHANNELS", {}).get(
                "SCREENS_CHANNEL", 1500077818749653012
            )
        )
        screens_channel = inter.bot.get_channel(screens_channel_id)
        if not screens_channel:
            try:
                screens_channel = await inter.bot.fetch_channel(
                    screens_channel_id
                )
            except Exception:
                screens_channel = None

        if screens_channel:
            screens_lines: list[str] = [
                f"**Кандидат:** <@{self.target_user_id}>"
            ]
            if nick_static_line:
                # Строка уже в формате "**Ник и статик:** ...".
                screens_lines.append(nick_static_line)
            screens_lines.append(
                f"**Принял:** {inter.author.mention}"
            )
            screens_text_block = "\n".join(screens_lines)

            screens_children: list = [
                disnake.ui.TextDisplay(screens_text_block)
            ]
            if screenshot_urls:
                screens_children.append(
                    disnake.ui.MediaGallery(
                        *[
                            disnake.MediaGalleryItem(u)
                            for u in screenshot_urls
                        ]
                    )
                )
            screens_cont = [
                disnake.ui.Container(
                    *screens_children, accent_colour=SUCCESS_COLOR
                )
            ]
            # Безшумно: пинг кандидата остаётся в тексте (он получает
            # визуальный mention в чате), но пуша нет (suppress_notifications).
            try:
                await screens_channel.send(
                    components=screens_cont,
                    allowed_mentions=disnake.AllowedMentions(
                        users=True, roles=False, everyone=False
                    ),
                    flags=disnake.MessageFlags(
                        suppress_notifications=True
                    ),
                )
            except Exception as ex:
                print(
                    f"[applications] send to SCREENS_CHANNEL failed: {ex!r}"
                )

        global_logs_channel_id = int(
            config.get("CHANNELS", {}).get(
                "GLOBAL_LOGS_CHANNEL", 1482857963428516010
            )
        )
        global_channel = inter.bot.get_channel(global_logs_channel_id)
        if not global_channel:
            try:
                global_channel = await inter.bot.fetch_channel(
                    global_logs_channel_id
                )
            except Exception:
                pass

        if global_channel:
            global_embed = disnake.Embed(
                title=f"{e('LOGS')}Глобальный лог: Одобрение",
                color=disnake.Color.green(),
                timestamp=datetime.datetime.now(),
            )
            global_embed.add_field(
                name="Кандидат",
                value=f"<@{self.target_user_id}>",
                inline=True,
            )
            global_embed.add_field(
                name="Проверил", value=inter.author.mention, inline=True
            )

            reward_amount = 0 if is_farm else ACCEPT_COIN_REWARD
            global_embed.add_field(
                name="Награда модератора",
                value=f"`{reward_amount} TC`",
                inline=True,
            )

            global_embed.add_field(
                name="Смена ника", value=nick_status, inline=True
            )
            global_embed.add_field(
                name="Выдача ролей", value=role_status, inline=True
            )
            global_embed.add_field(
                name="Был в семье?",
                value=f"{e('SUCCESS')}Да (Анти-Абуз)"
                if is_farm
                else f"{e('ERROR')}Нет",
                inline=True,
            )

            join_date = (
                f"<t:{int(member.joined_at.timestamp())}:D>"
                if member and member.joined_at
                else "Неизвестно"
            )
            global_embed.add_field(
                name="Зашел на сервер", value=join_date, inline=True
            )

            if app_text:
                global_embed.description = (
                    f"**Анкета кандидата:**\n\n{app_text}"
                )

            await global_channel.send(embed=global_embed)

        # === Личный канал YOUNG для принятого кандидата ===
        # Создаём в категории 1462480155418034301 (или соседней «-N»,
        # если базовая забита). В канале висит главный эмбед +
        # карточка кандидата + кнопки `Повысить`/`Выгнать`, а также
        # три публичные ветки: РП / Арена / Общение с рекрутёром.
        if member is not None and inter.guild is not None:
            try:
                accepted_at_ts = int(
                    datetime.datetime.utcnow().timestamp()
                )
                await _setup_academy_channel(
                    guild=inter.guild,
                    member=member,
                    moderator=inter.author,
                    stage="young",
                    accepted_at_ts=accepted_at_ts,
                )
            except Exception as ex:
                print(
                    f"[academy] _setup_academy_channel(young) failed: "
                    f"{ex!r}"
                )

        await inter.channel.delete(reason="Заявка принята")


class RejectModal(disnake.ui.Modal):
    def __init__(self, target_user_id: str, message_id: str):
        self.target_user_id = target_user_id
        self.message_id = message_id
        components = [
            disnake.ui.TextInput(
                label="Причина отказа",
                placeholder="Слабые откаты, не подходит по возрасту...",
                custom_id="reason",
                style=disnake.TextInputStyle.paragraph,
                max_length=500,
            )
        ]
        super().__init__(title="Отклонение заявки", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        reason = inter.text_values["reason"]

        formatted_reason = "\n".join(
            [f"> {line}" for line in reason.split("\n")]
        )

        target_id = int(self.target_user_id)
        member = inter.guild.get_member(target_id)
        if not member:
            try:
                member = await inter.guild.fetch_member(target_id)
            except Exception:
                pass

        if member:
            try:
                dm_embed = disnake.Embed(
                    description="К сожалению, ваша заявка была **отклонена**.",
                    color=INVISIBLE_COLOR,
                )
                dm_embed.add_field(name="Причина:", value=formatted_reason)
                logo = get_safe_logo()
                if logo:
                    dm_embed.set_thumbnail(url=logo)
                await member.send(embed=dm_embed)
            except Exception:
                pass

        is_farm = False
        async with aiosqlite.connect("data/database.sqlite") as db:
            async with db.execute(
                "SELECT candidate_id FROM rewarded_candidates WHERE candidate_id = ?",
                (str(self.target_user_id),),
            ) as cursor:
                if await cursor.fetchone():
                    is_farm = True

            # Отклонение — никаких коинов (REJECT_COIN_REWARD = 0).
            # `rewarded_candidates` тоже не трогаем, чтобы при повторной
            # заявке и принятии модератор всё же получил положенный
            # +1. Оставляем is_farm = False, чтобы эмбед ниже не сломался.
            _ = is_farm  # пользуем в глобальном логе ниже

            await db.execute(
                "UPDATE applications SET status = ? WHERE message_id = ?",
                ("rejected", self.message_id),
            )
            await db.commit()

        app_text = ""
        try:
            msg = await inter.channel.fetch_message(int(self.message_id))
            app_text = _extract_application_text(msg)
        except Exception:
            pass

        results_channel_id = int(
            config.get("CHANNELS", {}).get(
                "RESULTS_CHANNEL", 1463104920268836999
            )
        )
        log_channel = inter.bot.get_channel(results_channel_id)
        if not log_channel:
            try:
                log_channel = await inter.bot.fetch_channel(
                    results_channel_id
                )
            except Exception:
                pass

        if log_channel:
            desc = (
                f"Заявка от пользователя <@{self.target_user_id}>\n\n"
                f"<:red:1486616915186159636>На вступление в семью была "
                f"**отклонена**\n\n"
                f"**Причина:**\n"
                f"{formatted_reason}\n\n"
                f"Рассматривал заявку: {inter.author.mention}"
            )
            log_embed = disnake.Embed(
                title="Заявка отклонена",
                description=desc,
                color=disnake.Color.red(),
            )

            if member and getattr(member, "display_avatar", None):
                log_embed.set_thumbnail(url=member.display_avatar.url)
            elif get_safe_logo():
                log_embed.set_thumbnail(url=get_safe_logo())

            if get_safe_logo():
                log_embed.set_footer(
                    text="Trappa Famq", icon_url=get_safe_logo()
                )
            else:
                log_embed.set_footer(text="Trappa Famq")

            await log_channel.send(embed=log_embed)

        global_logs_channel_id = int(
            config.get("CHANNELS", {}).get(
                "GLOBAL_LOGS_CHANNEL", 1482857963428516010
            )
        )
        global_channel = inter.bot.get_channel(global_logs_channel_id)
        if not global_channel:
            try:
                global_channel = await inter.bot.fetch_channel(
                    global_logs_channel_id
                )
            except Exception:
                pass

        if global_channel:
            global_embed = disnake.Embed(
                title=f"{e('LOGS')}Глобальный лог: Отклонение",
                color=disnake.Color.red(),
                timestamp=datetime.datetime.now(),
            )
            global_embed.add_field(
                name="Кандидат",
                value=f"<@{self.target_user_id}>",
                inline=True,
            )
            global_embed.add_field(
                name="Проверил", value=inter.author.mention, inline=True
            )
            global_embed.add_field(
                name="Причина", value=f"{formatted_reason}", inline=True
            )

            reward_amount = REJECT_COIN_REWARD
            global_embed.add_field(
                name="Награда модератора",
                value=f"`{reward_amount} TC`",
                inline=True,
            )
            global_embed.add_field(
                name="Был в семье?",
                value=f"{e('SUCCESS')}Да (Анти-Абуз)"
                if is_farm
                else f"{e('ERROR')}Нет",
                inline=True,
            )

            join_date = (
                f"<t:{int(member.joined_at.timestamp())}:D>"
                if member and member.joined_at
                else "Неизвестно"
            )
            global_embed.add_field(
                name="Зашел на сервер", value=join_date, inline=True
            )

            if app_text:
                global_embed.description = (
                    f"**Анкета кандидата:**\n\n{app_text}"
                )

            await global_channel.send(embed=global_embed)

        await inter.channel.delete(reason="Заявка отклонена")


# ==========================================
# COG
# ==========================================
class ApplicationsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS applications "
                "(user_id TEXT, message_id TEXT, status TEXT)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS rewarded_candidates "
                "(candidate_id TEXT PRIMARY KEY)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS user_coins "
                "(user_id TEXT PRIMARY KEY, balance INTEGER DEFAULT 0)"
            )
            # Лёгкая миграция: добавляем колонки для статистики рекрутеров.
            for column_sql in (
                "ALTER TABLE applications ADD COLUMN recruiter_id TEXT",
                "ALTER TABLE applications ADD COLUMN accepted_at TEXT",
            ):
                try:
                    await db.execute(column_sql)
                except Exception:
                    pass

            # Таблицы для учёта обзвонов:
            # 1) call_invites — кто кого вызвал на обзвон (уникально по заявке)
            # 2) call_voice_sessions — сессии входа/выхода в каналы обзвона
            await db.execute(
                "CREATE TABLE IF NOT EXISTS call_invites ("
                "  message_id TEXT PRIMARY KEY,"
                "  recruiter_id TEXT NOT NULL,"
                "  candidate_id TEXT NOT NULL,"
                "  called_at TEXT NOT NULL"
                ")"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_call_invites_rec_called "
                "ON call_invites(recruiter_id, called_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_call_invites_candidate "
                "ON call_invites(candidate_id)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS call_voice_sessions ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  user_id TEXT NOT NULL,"
                "  channel_id TEXT NOT NULL,"
                "  joined_at TEXT NOT NULL,"
                "  left_at TEXT"
                ")"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_call_voice_user_joined "
                "ON call_voice_sessions(user_id, joined_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_call_voice_open "
                "ON call_voice_sessions(user_id) WHERE left_at IS NULL"
            )

            # На рестарте бота закрываем все «зависшие» сессии текущим
            # временем — иначе они будут расти бесконечно.
            await db.execute(
                "UPDATE call_voice_sessions SET left_at = ? "
                "WHERE left_at IS NULL",
                (_iso_utc_now(),),
            )
            await db.commit()

        # На случай если бот стартовал когда участники уже сидят в каналах
        # обзвона — открываем для них новые сессии прямо сейчас.
        try:
            for guild in self.bot.guilds:
                for ch_id in CALL_VOICE_CHANNEL_IDS_INT:
                    ch = guild.get_channel(ch_id)
                    if ch is None or not isinstance(
                        ch, disnake.VoiceChannel
                    ):
                        continue
                    for member in ch.members:
                        await _start_call_voice_session(
                            str(member.id), str(ch_id)
                        )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: disnake.Member,
        before: disnake.VoiceState,
        after: disnake.VoiceState,
    ) -> None:
        """Засекает вход/выход в любой из каналов обзвона.

        Только обычное членство — мьюты/глухоту игнорируем. Хранит
        одну открытую сессию на (user_id, channel_id); при сменe канала
        корректно закрывает старую и открывает новую.
        """
        before_ch = before.channel.id if before.channel else None
        after_ch = after.channel.id if after.channel else None
        if before_ch == after_ch:
            return  # просто mute/deaf/server-move внутри того же канала

        if before_ch in CALL_VOICE_CHANNEL_IDS_INT:
            await _close_call_voice_session(str(member.id), str(before_ch))

        if after_ch in CALL_VOICE_CHANNEL_IDS_INT:
            await _start_call_voice_session(str(member.id), str(after_ch))

    @commands.Cog.listener()
    async def on_dropdown(self, inter: disnake.MessageInteraction):
        """Обработчик встроенного селекта в Components V2 панели."""
        if inter.component.custom_id != APPLICATION_SELECT_CID:
            return

        # Если значение не из ожидаемых — просто сбрасываем селект и выходим.
        if not inter.values or inter.values[0] != APPLICATION_OPTION_CREATE:
            try:
                await inter.message.edit(components=build_application_panel())
            except Exception:
                pass
            return

        category = inter.guild.get_channel(
            int(config["CHANNELS"]["APPLICATION_REVIEW"])
        )
        already_open: disnake.TextChannel | None = None
        if category and isinstance(category, disnake.CategoryChannel):
            for ch in category.text_channels:
                if str(inter.author.id) in (ch.topic or ""):
                    already_open = ch
                    break

        if already_open is not None:
            await inter.response.send_message(
                f"У вас уже открыта заявка: {already_open.mention}",
                ephemeral=True,
            )
        else:
            await inter.response.send_modal(ApplicationModal())

        # После любого клика по селекту всегда сбрасываем его состояние,
        # чтобы кнопка снова была «чистой» и пользователь мог выбрать пункт
        # повторно без обновления страницы.
        try:
            await inter.message.edit(components=build_application_panel())
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_button_click(self, inter: disnake.MessageInteraction):
        custom_id = inter.component.custom_id
        if not custom_id:
            return

        if custom_id.startswith(TOPREC_BUTTON_PREFIX):
            if not inter.author.guild_permissions.administrator:
                return await inter.response.send_message(
                    f"{e('REJECT')}Панель доступна только администраторам.",
                    ephemeral=True,
                )
            period_key = custom_id[len(TOPREC_BUTTON_PREFIX):]
            if period_key not in {k for k, _, _ in TOPREC_PERIODS}:
                period_key = TOPREC_DEFAULT_PERIOD
            cont = await _build_toprec_container(
                period_key, guild=inter.guild
            )
            try:
                await inter.response.edit_message(components=cont)
            except Exception:
                try:
                    await inter.message.edit(components=cont)
                except Exception:
                    pass
            return

        if custom_id.startswith(
            ("academy_promote_", "academy_expel_")
        ):
            await self._handle_academy_button(inter, custom_id)
            return

        if custom_id.startswith(
            ("accept_", "reject_", "call_", "edit_")
        ):
            moderator_roles = config.get("ROLES", {}).get("MODERATOR", [])
            mod_role_ids_int = {int(x) for x in moderator_roles}
            is_mod = any(
                r.id in mod_role_ids_int for r in inter.author.roles
            )
            if not is_mod and not inter.author.guild_permissions.administrator:
                return await inter.response.send_message(
                    f"{e('REJECT')}У вас нет прав.", ephemeral=True
                )

        if custom_id.startswith("accept_"):
            await inter.response.send_modal(
                AcceptModal(custom_id.split("_")[1], str(inter.message.id))
            )

        elif custom_id.startswith("reject_"):
            await inter.response.send_modal(
                RejectModal(custom_id.split("_")[1], str(inter.message.id))
            )

        elif custom_id.startswith("edit_"):
            try:
                target_user_id = int(custom_id.split("_")[1])
            except (ValueError, IndexError):
                return await inter.response.send_message(
                    f"{e('ERROR')}Некорректный ID кандидата в кнопке.",
                    ephemeral=True,
                )
            current_text = ""
            try:
                current_text = _extract_application_text(inter.message)
            except Exception:
                current_text = ""
            current = _parse_application_fields(current_text)
            await inter.response.send_modal(
                EditApplicationModal(
                    inter.message, target_user_id, current
                )
            )

        elif custom_id.startswith("call_"):
            await inter.response.defer(ephemeral=True)
            user_id = custom_id.split("_")[1]
            message_id = str(inter.message.id)

            channel_id = 1463605913117134900

            async with aiosqlite.connect("data/database.sqlite") as db:
                await db.execute(
                    "UPDATE applications SET status = ? WHERE user_id = ?",
                    ("interview", user_id),
                )
                await db.commit()

            # Фиксируем вызов в таблице call_invites — один кандидат
            # на одну заявку (повторные клики переписывают рекрутёра).
            try:
                await _record_call_invite(
                    message_id=message_id,
                    recruiter_id=str(inter.author.id),
                    candidate_id=str(user_id),
                )
            except Exception:
                pass

            member = inter.guild.get_member(int(user_id))
            if not member:
                try:
                    member = await inter.guild.fetch_member(int(user_id))
                except Exception:
                    pass

            if member:
                try:
                    await inter.channel.edit(name=f"обзвон-{member.name}")
                except Exception:
                    pass
                try:
                    dm_embed = disnake.Embed(
                        description=(
                            f"Ваша заявка находится на рассмотрении.\n\n"
                            f"Свяжитесь со мной, если готовы пройти обзвон — "
                            f"{inter.author.mention}"
                        ),
                        color=INVISIBLE_COLOR,
                    )
                    logo = get_safe_logo()
                    if logo:
                        dm_embed.set_thumbnail(url=logo)
                    await member.send(embed=dm_embed)
                except Exception:
                    pass

            try:
                msg = await inter.channel.fetch_message(int(message_id))
                if msg.components:
                    # «Обзвон» не должен убирать кнопки — оставляем
                    # все 4 (Принять/Отклонить/Обзвон/Изменить) и только
                    # добавляем внизу текстовую пометку «Переведено на обзвон».
                    ui_container = _to_ui_container(msg.components[0])
                    new_children: list = []
                    note_text = (
                        f"-# Переведено на обзвон: "
                        f"{inter.author.display_name}"
                    )
                    already_marked = False
                    for child in list(
                        getattr(ui_container, "children", []) or []
                    ):
                        if (
                            type(child).__name__ == "TextDisplay"
                            and getattr(child, "content", "").startswith(
                                "-# Переведено на обзвон:"
                            )
                        ):
                            # Перезаписываем, если рекрутёра поменяли.
                            new_children.append(
                                disnake.ui.TextDisplay(note_text)
                            )
                            already_marked = True
                        else:
                            new_children.append(child)
                    if not already_marked:
                        new_children.append(
                            disnake.ui.TextDisplay(note_text)
                        )
                    new_cont = [
                        disnake.ui.Container(
                            *new_children, accent_colour=ORANGE_COLOR
                        )
                    ]
                    await msg.edit(components=new_cont)
                elif msg.embeds:
                    embed = msg.embeds[0]
                    embed.color = disnake.Color.orange()
                    embed.set_footer(
                        text=f"Переведено на обзвон: "
                        f"{inter.author.display_name}"
                    )
                    # Легаси-эмбед: тоже сохраняем все 4 кнопки.
                    view = disnake.ui.View(timeout=None)
                    view.add_item(
                        disnake.ui.Button(
                            label="Принять",
                            emoji=e_btn("SUCCESS"),
                            style=disnake.ButtonStyle.success,
                            custom_id=f"accept_{user_id}",
                        )
                    )
                    view.add_item(
                        disnake.ui.Button(
                            label="Отклонить",
                            emoji=e_btn("REJECT"),
                            style=disnake.ButtonStyle.danger,
                            custom_id=f"reject_{user_id}",
                        )
                    )
                    view.add_item(
                        disnake.ui.Button(
                            label="Обзвон",
                            emoji=e_btn("CALL"),
                            style=disnake.ButtonStyle.primary,
                            custom_id=f"call_{user_id}",
                        )
                    )
                    view.add_item(
                        disnake.ui.Button(
                            label="Изменить",
                            emoji=e_btn("EDIT") or e_btn("SETTINGS"),
                            style=disnake.ButtonStyle.secondary,
                            custom_id=f"edit_{user_id}",
                        )
                    )
                    await msg.edit(embed=embed, view=view)
            except Exception:
                pass

            results_channel_id = int(
                config.get("CHANNELS", {}).get(
                    "RESULTS_CHANNEL", 1463104920268836999
                )
            )
            res_channel = inter.bot.get_channel(results_channel_id)
            if not res_channel:
                try:
                    res_channel = await inter.bot.fetch_channel(
                        results_channel_id
                    )
                except Exception:
                    pass

            if res_channel:
                desc = (
                    f"Заявка от пользователя <@{user_id}>\n\n"
                    f"<:green:1486608277046562926>На вступление в семью была "
                    f"рассмотрена!\n\n"
                    f"Для прохода обзвона ожидаем вас в канале:\n"
                    f"<a:strelka1:1485470220905746654> <#{channel_id}>\n\n"
                    f"Рассматривал заявку: {inter.author.mention}"
                )
                call_res_embed = disnake.Embed(
                    description=desc, color=disnake.Color.green()
                )

                if member and getattr(member, "display_avatar", None):
                    call_res_embed.set_thumbnail(
                        url=member.display_avatar.url
                    )
                elif get_safe_logo():
                    call_res_embed.set_thumbnail(url=get_safe_logo())

                if get_safe_logo():
                    call_res_embed.set_footer(
                        text="Trappa Famq", icon_url=get_safe_logo()
                    )
                else:
                    call_res_embed.set_footer(text="Trappa Famq")

                await res_channel.send(embed=call_res_embed)

            global_logs_channel_id = int(
                config.get("CHANNELS", {}).get(
                    "GLOBAL_LOGS_CHANNEL", 1482857963428516010
                )
            )
            global_channel = inter.bot.get_channel(global_logs_channel_id)
            if not global_channel:
                try:
                    global_channel = await inter.bot.fetch_channel(
                        global_logs_channel_id
                    )
                except Exception:
                    pass

            if global_channel:
                call_log = disnake.Embed(
                    title=f"{e('CALL')}Глобальный лог: Перевод на обзвон",
                    color=disnake.Color.orange(),
                    timestamp=datetime.datetime.now(),
                )
                call_log.add_field(
                    name="Кандидат", value=f"<@{user_id}>", inline=True
                )
                call_log.add_field(
                    name="Модератор", value=inter.author.mention, inline=True
                )
                call_log.add_field(
                    name="Канал", value=f"<#{channel_id}>", inline=True
                )
                await global_channel.send(embed=call_log)

            await inter.channel.send(
                f"{e('CALL')}<@{user_id}>, модератор {inter.author.mention} "
                f"готов! Зайдите в <#{channel_id}>"
            )
            await inter.followup.send(
                f"{e('SUCCESS')}Кандидат вызван.", ephemeral=True
            )

    # ==========================================
    # ACADEMY: обработчики кнопок + /fix_academy
    # ==========================================

    async def _handle_academy_button(
        self,
        inter: disnake.MessageInteraction,
        custom_id: str,
    ) -> None:
        """Обработчик `academy_promote_<id>` и `academy_expel_<id>`.

        Доступ только модераторам (роли из _get_moderator_role_ids
        или administrator/manage_channels).
        """
        author = inter.author if isinstance(
            inter.author, disnake.Member
        ) else None
        if not _author_is_academy_moderator(author):
            return await inter.response.send_message(
                f"{e('REJECT')}Кнопки доступны только модераторам.",
                ephemeral=True,
            )
        if inter.guild is None:
            return

        try:
            target_user_id = int(custom_id.rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            return await inter.response.send_message(
                f"{e('ERROR')}Некорректный ID.", ephemeral=True
            )
        member = inter.guild.get_member(target_user_id)
        if member is None:
            try:
                member = await inter.guild.fetch_member(target_user_id)
            except Exception:
                member = None

        young_role = inter.guild.get_role(YOUNG_ROLE_ID)
        academy_role = inter.guild.get_role(ACADEMY_ROLE_ID)

        if custom_id.startswith("academy_expel_"):
            await inter.response.defer(ephemeral=True)
            if member is not None:
                to_remove: list[disnake.Role] = []
                for r in (young_role, academy_role):
                    if r is not None and r in member.roles:
                        to_remove.append(r)
                if to_remove:
                    try:
                        await member.remove_roles(
                            *to_remove, reason="academy: выгнан"
                        )
                    except Exception as ex:
                        print(
                            f"[academy] expel remove_roles failed: "
                            f"{ex!r}"
                        )
            try:
                await inter.followup.send(
                    f"{e('SUCCESS')}Кандидат выгнан, канал будет удалён.",
                    ephemeral=True,
                )
            except Exception:
                pass
            try:
                await inter.channel.delete(
                    reason=f"academy: выгнан {member} пользователем "
                    f"{inter.author}"
                )
            except Exception as ex:
                print(f"[academy] expel delete channel failed: {ex!r}")
            return

        # academy_promote_<id>
        if member is None:
            return await inter.response.send_message(
                f"{e('REJECT')}Пользователь не найден на сервере.",
                ephemeral=True,
            )

        has_young = young_role in member.roles if young_role else False
        has_academy = (
            academy_role in member.roles if academy_role else False
        )

        if has_young and not has_academy:
            # Young → Academy: перенести канал + смена ролей.
            await inter.response.defer(ephemeral=True)
            new_category = await _pick_category_with_slots(
                inter.guild, ACADEMY_CATEGORY_ID
            )
            if new_category is None:
                return await inter.followup.send(
                    f"{e('REJECT')}Не получилось получить категорию академии.",
                    ephemeral=True,
                )
            new_name = (
                f"академ-"
                f"{_normalize_channel_name(member.display_name)}"
            )[:95]
            try:
                await inter.channel.edit(
                    category=new_category,
                    name=new_name,
                    overwrites=_build_academy_overwrites(
                        inter.guild, member
                    ),
                    reason=f"academy: повышение {member} до ACADEMY",
                )
            except Exception as ex:
                print(f"[academy] promote edit channel failed: {ex!r}")
            try:
                if young_role:
                    await member.remove_roles(
                        young_role, reason="academy: повышение"
                    )
                if academy_role:
                    await member.add_roles(
                        academy_role, reason="academy: повышение"
                    )
            except disnake.Forbidden:
                return await inter.followup.send(
                    f"{e('REJECT')}Нет прав на изменение ролей.",
                    ephemeral=True,
                )
            except Exception as ex:
                return await inter.followup.send(
                    f"{e('ERROR')}Ошибка: {ex!r}", ephemeral=True
                )
            try:
                new_cont = _build_academy_card_container(
                    member=member,
                    accepted_at_ts=int(
                        datetime.datetime.utcnow().timestamp()
                    ),
                    footer_text="**Этап:** ACADEMY (2 часть)",
                )
                await inter.message.edit(components=new_cont)
            except Exception as ex:
                print(f"[academy] promote refresh card failed: {ex!r}")
            return await inter.followup.send(
                f"{e('SUCCESS')}Кандидат повышен до ACADEMY.",
                ephemeral=True,
            )

        if has_academy:
            # Academy → final: снять ACADEMY (и оставшийся YOUNG), выдать
            # финальную роль (FINAL_ROLE_ID / RANK_FINAL) и удалить канал.
            await inter.response.defer(ephemeral=True)
            final_role_id = int(
                config.get("ACADEMY", {}).get(
                    "RANK_FINAL", FINAL_ROLE_ID
                )
            )
            final_role = inter.guild.get_role(final_role_id)
            if final_role is None:
                return await inter.followup.send(
                    f"{e('REJECT')}Финальная роль "
                    f"`{final_role_id}` не найдена на сервере.",
                    ephemeral=True,
                )
            try:
                to_remove: list[disnake.Role] = []
                for r in (young_role, academy_role):
                    if r is not None and r in member.roles:
                        to_remove.append(r)
                if to_remove:
                    await member.remove_roles(
                        *to_remove, reason="academy: финал академии"
                    )
                await member.add_roles(
                    final_role, reason="academy: финал академии"
                )
            except disnake.Forbidden:
                return await inter.followup.send(
                    f"{e('REJECT')}Нет прав на изменение ролей (роль "
                    f"бота должна быть выше ACADEMY/финальной).",
                    ephemeral=True,
                )
            except Exception as ex:
                return await inter.followup.send(
                    f"{e('ERROR')}Ошибка: {ex!r}", ephemeral=True
                )
            try:
                await inter.followup.send(
                    f"{e('SUCCESS')}Финал: выдана роль {final_role.mention}, "
                    f"канал `{inter.channel.name}` будет удалён.",
                    ephemeral=True,
                    allowed_mentions=disnake.AllowedMentions.none(),
                )
            except Exception:
                pass
            try:
                await inter.channel.delete(
                    reason=(
                        f"academy: финал {member} пользователем "
                        f"{inter.author}"
                    )
                )
            except Exception as ex:
                print(f"[academy] final delete channel failed: {ex!r}")
            return

        return await inter.response.send_message(
            f"{e('WARNING')}У кандидата нет ни роли YOUNG, ни ACADEMY.",
            ephemeral=True,
        )

    @commands.slash_command(
        name="fix_academy",
        description="Корректировка каналов академии по категории",
    )
    async def fix_academy(
        self,
        inter: disnake.GuildCommandInteraction,
        category: disnake.CategoryChannel = commands.Param(
            description="Категория для корректировки"
        ),
    ) -> None:
        """Корректировка личных каналов академии по категории.

        - Обходит все текстовые каналы в категории.
        - Для каждого канала берёт user_id из топика (бот кладёт его
          при создании).
        - Если пользователя нет на сервере или у него нет роли YOUNG/
          ACADEMY — канал удаляется.
        - Иначе обновляет первое ботовое сообщение в канале (карточку).

        Доступ: только роль RECRUITMENT_ROLE_ID (или administrator).
        """
        author = inter.author if isinstance(
            inter.author, disnake.Member
        ) else None
        if author is None:
            return
        is_recruit = any(
            r.id == RECRUITMENT_ROLE_ID for r in author.roles
        )
        if not is_recruit and not author.guild_permissions.administrator:
            return await inter.response.send_message(
                f"{e('REJECT')}Команда доступна только роли "
                f"<@&{RECRUITMENT_ROLE_ID}>.",
                ephemeral=True,
            )

        await inter.response.defer(ephemeral=True)

        young_role = inter.guild.get_role(YOUNG_ROLE_ID)
        academy_role = inter.guild.get_role(ACADEMY_ROLE_ID)
        bot_id = inter.bot.user.id if inter.bot.user else 0

        deleted: list[str] = []
        updated: list[str] = []
        recreated: list[str] = []
        moved: list[str] = []
        renamed: list[str] = []
        threads_fixed: list[str] = []
        thread_errors: list[str] = []
        skipped: list[str] = []

        for ch in list(category.text_channels):
            member = await _resolve_academy_candidate(
                inter.guild, ch, bot_id
            )

            is_academy = bool(
                member
                and academy_role
                and academy_role in member.roles
            )
            is_young = bool(
                member
                and young_role
                and young_role in member.roles
            )
            has_role = is_academy or is_young

            if member is None:
                skipped.append(ch.name)
                continue

            if not has_role:
                try:
                    await ch.delete(
                        reason=(
                            "fix_academy: нет роли YOUNG/ACADEMY или вне "
                            "сервера"
                        )
                    )
                    deleted.append(ch.name)
                except Exception as ex:
                    print(
                        f"[fix_academy] delete {ch.name!r} failed: "
                        f"{ex!r}"
                    )
                continue

            # Определяем целевую категорию и имя по роли. ACADEMY
            # выигрывает у YOUNG, если обе роли одновременно.
            if is_academy:
                target_base_id = ACADEMY_CATEGORY_ID
                target_prefix = "академ"
            else:
                target_base_id = YOUNG_CATEGORY_ID
                target_prefix = "young"

            target_name = (
                f"{target_prefix}-"
                f"{_normalize_channel_name(member.display_name)}"
            )[:95]

            # Если канал не в нужной категории — переносим.
            new_category: disnake.CategoryChannel | None = None
            if not _is_channel_in_category_chain(
                inter.guild, ch, target_base_id
            ):
                new_category = await _pick_category_with_slots(
                    inter.guild, target_base_id
                )

            edit_kwargs: dict = {
                "overwrites": _build_academy_overwrites(
                    inter.guild, member
                ),
                "topic": str(member.id),
                "reason": (
                    "fix_academy: синхронизация категории/имени/"
                    "доступа"
                ),
            }
            if new_category is not None:
                edit_kwargs["category"] = new_category
            if ch.name != target_name:
                edit_kwargs["name"] = target_name

            try:
                await ch.edit(**edit_kwargs)
            except Exception as ex:
                print(
                    f"[fix_academy] edit {ch.name!r} failed: {ex!r}"
                )
            else:
                if new_category is not None:
                    moved.append(target_name)
                if "name" in edit_kwargs:
                    renamed.append(target_name)

            footer = None
            if is_academy:
                footer = "**Этап:** ACADEMY (2 часть)"
            elif is_young:
                footer = "**Этап:** YOUNG (1 часть)"

            try:
                result = await _refresh_academy_card_message(
                    ch, member, bot_id, footer
                )
            except Exception as ex:
                print(
                    f"[fix_academy] update {ch.name!r} failed: {ex!r}"
                )
                result = "failed"

            if result == "edited":
                updated.append(ch.name)
            elif result == "recreated":
                recreated.append(ch.name)

            # Восстанавливаем пропавшие ветки + пинг-извинение.
            try:
                created_threads, errs = await _ensure_academy_threads(
                    ch
                )
            except Exception as ex:
                print(
                    f"[fix_academy] threads {ch.name!r} failed: {ex!r}"
                )
                created_threads, errs = [], [f"all: {ex!r}"]

            if errs:
                for err in errs:
                    thread_errors.append(f"`{ch.name}` → {err}")

            if created_threads:
                threads_fixed.append(ch.name)
                try:
                    await ch.send(
                        content=(
                            f"{e('WARNING')} {member.mention}, "
                            f"извини — произошёл сбой, ветки "
                            f"были удалены. Автоматически "
                            f"восстановил: "
                            f"{', '.join(created_threads)}."
                        ),
                        allowed_mentions=disnake.AllowedMentions(
                            users=[member],
                            roles=False,
                            everyone=False,
                        ),
                    )
                except Exception as ex:
                    print(
                        f"[fix_academy] apology send {ch.name!r} "
                        f"failed: {ex!r}"
                    )

        report_lines = [
            f"**Категория:** {category.mention}",
            f"Удалено: **{len(deleted)}**",
            f"Обновлено карточек: **{len(updated)}**",
            f"Пересоздано эмбедов: **{len(recreated)}**",
            f"Перенесено по роли: **{len(moved)}**",
            f"Переименовано: **{len(renamed)}**",
            f"Восстановлены ветки: **{len(threads_fixed)}**",
            f"Ошибок создания веток: **{len(thread_errors)}**",
            f"Пропущено (не нашёл кандидата): **{len(skipped)}**",
        ]
        if deleted:
            report_lines.append(
                f"_Deleted:_ {', '.join(deleted[:15])}"
                + (
                    f" и ещё {len(deleted) - 15}..."
                    if len(deleted) > 15
                    else ""
                )
            )
        if thread_errors:
            head = thread_errors[:8]
            report_lines.append(
                "_Ошибки веток:_\n" + "\n".join(head)
                + (
                    f"\n... и ещё {len(thread_errors) - 8}"
                    if len(thread_errors) > 8
                    else ""
                )
            )
        await inter.followup.send(
            components=simple_container(
                "\n".join(report_lines), SUCCESS_COLOR
            ),
            ephemeral=True,
        )

    @commands.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def setup_panel(self, ctx):
        """Постит Components V2 панель заявок в текущий канал."""
        components = build_application_panel()
        await ctx.send(components=components)
        try:
            await ctx.message.delete()
        except Exception:
            pass

    @commands.command(name="toprec")
    @commands.has_permissions(administrator=True)
    async def toprec(self, ctx: commands.Context):
        """Топ рекрутеров: один период с переключением кнопками (админ-only)."""
        cont = await _build_toprec_container(
            TOPREC_DEFAULT_PERIOD, guild=ctx.guild
        )
        await ctx.send(
            components=cont,
            allowed_mentions=disnake.AllowedMentions.none(),
        )

    @toprec.error
    async def toprec_error(
        self, ctx: commands.Context, error: commands.CommandError
    ):
        if isinstance(error, commands.MissingPermissions):
            try:
                await ctx.reply(
                    f"{e('REJECT')}Команда доступна только администраторам.",
                    mention_author=False,
                    delete_after=10,
                )
            except Exception:
                pass


    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        """Общий fallback-обработчик ошибок кога.

        Если у команды есть собственный `.error` хэндлер — пропускаем.
        Иначе печатаем stacktrace в stderr, чтобы ошибки не терялись.
        """
        cmd = ctx.command
        if cmd is not None and cmd.has_error_handler():
            return

        import sys
        import traceback
        print(
            f"Ignoring exception in command {cmd}:",
            file=sys.stderr,
        )
        traceback.print_exception(
            type(error), error, error.__traceback__, file=sys.stderr
        )


def setup(bot):
    bot.add_cog(ApplicationsCog(bot))
