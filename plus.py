from __future__ import annotations

import asyncio
import json
import logging
import aiosqlite
import time
import re
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import disnake
from disnake.ext import commands, tasks

log = logging.getLogger("kraymore")

with open("config.json", "r", encoding="utf-8") as f:
    _cfg = json.load(f)

# ==========================================
# БЛОК НАСТРОЕК (ДЛЯ БЫСТРОЙ ЗАМЕНЫ)
# ==========================================
FAM_NAME = "Trappa Famq"                # Название семьи
MAIN_ROLE_ID = 1416748449096925204       # ID главной роли семьи
EMBED_COLOR = 0x40e0d0                   # Цвет эмбедов (бирюзовый)

# --- НАСТРОЙКИ РОЛЕЙ ---
TIER1_ROLE_ID = 1417097295555727422      # Роль 1-го тира
TIER2_ROLE_ID = 1417097269471084565      # Роль 2-го тира
TIER3_ROLE_ID = 1417097202303631471      # Роль 3-го тира

BAN_CAPT_ROLE_ID = 1473679375613296724   # Роль BAN CAPT (блокировка участия)

# ID ролей (до 3 штук), которые имеют доступ к кнопке "Настройки"
SETTINGS_ROLE_IDS = [
    1416748244305973348,                 # Роль 1
    1416748130300461239,                 # Роль 2
    1416748033361576068                  # Роль 3
]

# --- НАСТРОЙКИ ЭМОДЗИ ---
# Эмодзи для тиров
TIER1_EMOJI = "<:SSS:1499407637618622705>"
TIER2_EMOJI = "<:AAA:1499407633730506912>"
TIER3_EMOJI = "<:BBB:1499407635697500341>"
TIER_NONE_EMOJI = "▫️"

# Глобальные эмодзи бота теперь берутся из config.json
EMOJIS = _cfg.get("EMOJIS", {})

# --- КАРТЫ ДЛЯ /mcl ---
# Имя -> URL картинки карты, отображается в эмбеде сбора /mcl
MCL_MAPS: dict[str, str] = {
    "weenmeel": "https://media.discordapp.net/attachments/1416897708949504050/1502804308415086743/1aacac99578a30fc.png",
    "Vinewood": "https://media.discordapp.net/attachments/1416897708949504050/1502804308763217960/48fc22092a34a60f.png",
    "Sandy-Shoers": "https://media.discordapp.net/attachments/1416897708949504050/1502804308763217960/48fc22092a34a60f.png",
    "Ghetto": "https://media.discordapp.net/attachments/1416897708949504050/1502804309614526535/64ba868332fd1157.png",
    "City": "https://media.discordapp.net/attachments/1416897708949504050/1502804309954269235/db62c7fff04c0aa2.png",
    "Industrial": "https://media.discordapp.net/attachments/1416897708949504050/1502804310298329109/ffcf90011eff9429.png",
    "Farm": "https://media.discordapp.net/attachments/1416897708949504050/1502804310616965220/e4a6ece426edde92.png",
    "пред.плюса": "https://media.discordapp.net/attachments/1284634464835862588/1420957113118883931/image_13.gif?ex=6a03deef&is=6a028d6f&hm=3554e9b597880c555114bf3eac261c90604d3a7b07ba25098e4b7adca1875e95&=&width=321&height=300",
}

# --- РЕАКЦИИ ДЛЯ /mcl ---
APPROVE_EMOJI = "✅"   # Модератор -> в основной список
RESERVE_EMOJI = "⌛"   # Модератор -> в резерв (\N{HOURGLASS})
RESERVE_EMOJI_ALT = "⏳"  # \N{HOURGLASS WITH FLOWING SAND} - тоже принимаем

# Базовое количество слотов для /plus (CAPT) по умолчанию
PLUS_CAPT_DEFAULT_BASE_SLOTS = 35
# ==========================================

# ==========================================
# ПОМОЩНИКИ ДЛЯ ЭМОДЗИ И ЛОГО
# ==========================================
def e(key: str) -> str:
    """Для текста: возвращает эмодзи с пробелом или пустоту."""
    val = EMOJIS.get(key, "")
    return f"{val} " if val else ""

def e_btn(key: str):
    """Для кнопок/меню: возвращает эмодзи или None."""
    val = EMOJIS.get(key, "")
    return val if val else None

def get_safe_logo():
    logo = _cfg.get("IMAGES", {}).get("LOGO", "").strip()
    if logo.startswith("Https"):
        logo = logo.replace("Https", "https")
    return logo
# ==========================================

def get_safe_url(url: str) -> str:
    url = url.strip()
    if url.startswith("Https"):
        url = url.replace("Https", "https")
    return url

class PlusConfig:
    CAPT_STATS_CHANNEL_ID = _cfg.get("PLUS", {}).get("STATS_CHANNEL", 0)
    PLUS_PARTICIPANTS_MAX_LINES = 35 
    PLUS_PARTICIPANTS_PAGE_SIZE = 35
    PLUS_DM_MAX_RECIPIENTS = _cfg.get("PLUS", {}).get("DM_MAX_RECIPIENTS", 50)
    
    CAPT_BANNER_URL = get_safe_url(_cfg.get("IMAGES", {}).get("PLUS_BANNER", ""))

config = PlusConfig()
TZ_UTC3 = timezone(timedelta(hours=3))

def brand_embed(title: str, description: str, banner_url: str = "", color: int = EMBED_COLOR) -> disnake.Embed:
    emb = disnake.Embed(title=title, description=description, color=color)
    if banner_url:
        try: emb.set_image(url=banner_url)
        except: pass
        
    logo = get_safe_logo()
    if logo:
        emb.set_footer(text=FAM_NAME, icon_url=logo)
    else:
        emb.set_footer(text=FAM_NAME)
        
    return emb

def _is_banned(user) -> bool:
    try:
        member = user.author if hasattr(user, "author") else user
        if isinstance(member, disnake.Member):
            return member.get_role(BAN_CAPT_ROLE_ID) is not None
        return False
    except Exception:
        return False

def _has_settings_access(member: disnake.Member) -> bool:
    if member.guild_permissions.administrator: 
        return True
    try: 
        return any(r.id in set(SETTINGS_ROLE_IDS) for r in member.roles)
    except Exception: 
        return False

def _tier_number_from_member(member: disnake.Member) -> tuple[int, str]:
    role_ids = {r.id for r in member.roles}
    if TIER1_ROLE_ID in role_ids: return 1, TIER1_EMOJI
    if TIER2_ROLE_ID in role_ids: return 2, TIER2_EMOJI
    if TIER3_ROLE_ID in role_ids: return 3, TIER3_EMOJI
    return 9, TIER_NONE_EMOJI

# ==========================================
# ПАНЕЛЬ ЗАБЛОКИРОВАННЫХ (BAN CAPT)
# ==========================================
async def update_ban_panel(bot):
    async with aiosqlite.connect("data/database.sqlite") as db:
        async with db.execute("SELECT value FROM ban_config WHERE key = 'channel_id'") as cursor:
            c_row = await cursor.fetchone()
        async with db.execute("SELECT value FROM ban_config WHERE key = 'message_id'") as cursor:
            m_row = await cursor.fetchone()

        if not c_row or not m_row: return
        
        channel = bot.get_channel(int(c_row[0]))
        if not channel: return
        
        current_ts = int(time.time())
        async with db.execute("SELECT user_id FROM banned_users WHERE expire_ts <= ?", (current_ts,)) as cursor:
            expired = await cursor.fetchall()
        
        for (uid,) in expired:
            guild = channel.guild
            member = guild.get_member(int(uid))
            if not member:
                try: member = await guild.fetch_member(int(uid))
                except: pass
            if member:
                role = guild.get_role(BAN_CAPT_ROLE_ID)
                if role:
                    try: await member.remove_roles(role, reason="Срок BAN CAPT истек")
                    except: pass
            await db.execute("DELETE FROM banned_users WHERE user_id = ?", (uid,))
        await db.commit()

        async with db.execute("SELECT user_id, admin_id, reason, expire_ts FROM banned_users ORDER BY expire_ts ASC") as cursor:
            bans = await cursor.fetchall()

    desc = ""
    if bans:
        for uid, aid, rsn, ets in bans:
            desc += f"👤 <@{uid}>\n└ **Спадёт:** <t:{ets}:R> | **Выдал:** <@{aid}>\n└ **Причина:** *{rsn}*\n\n"
    else:
        desc = "> *Список заблокированных пуст.*"

    embed = disnake.Embed(
        title="Список заблокированных - BAN CAPT",
        description=desc,
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc)
    )
    logo = get_safe_logo()
    if logo:
        embed.set_footer(text=f"{FAM_NAME} • Авто-обновление каждую минуту", icon_url=logo)
    else:
        embed.set_footer(text=f"{FAM_NAME} • Авто-обновление каждую минуту")

    try:
        msg = await channel.fetch_message(int(m_row[0]))
        await msg.edit(embed=embed)
    except:
        pass

_STATS_LOCK = asyncio.Lock()
_STATS_PATH = Path("data/plus_stats.json")

def _stats_default() -> dict:
    return {
        "message_id": 0,
        "counts": {"capt": {"win": 0, "loss": 0}, "mcl": {"win": 0, "loss": 0}, "взз": {"win": 0, "loss": 0}, "взм": {"win": 0, "loss": 0}},
        "updated_ts": 0,
    }

def _stats_load() -> dict:
    try:
        if _STATS_PATH.exists():
            with _STATS_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict): return _stats_default()
                data.setdefault("message_id", 0)
                data.setdefault("counts", {})
                for k in ("capt", "mcl", "взз", "взм"):
                    v = data["counts"].get(k)
                    if isinstance(v, int): data["counts"][k] = {"win": int(v), "loss": 0}
                    elif isinstance(v, dict): v.setdefault("win", 0); v.setdefault("loss", 0)
                    else: data["counts"][k] = {"win": 0, "loss": 0}
                data.setdefault("updated_ts", 0)
                return data
    except Exception: pass
    return _stats_default()

def _stats_save(data: dict) -> None:
    try:
        _STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _STATS_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception: pass

def _build_stats_embed(data: dict) -> disnake.Embed:
    ts = int(data.get("updated_ts") or 0)
    counts = data.get("counts") or {}
    
    total_wins = 0
    total_losses = 0
    
    for k, v in counts.items():
        if isinstance(v, int):
            total_wins += v
        elif isinstance(v, dict):
            total_wins += int(v.get("win", 0))
            total_losses += int(v.get("loss", 0))
            
    total_games = total_wins + total_losses
    
    emb = brand_embed(
        title=f"{e('STATS')}Статистика PLUS", 
        description=f"Последнее обновление: <t:{ts}:R>" if ts else "—", 
        banner_url=config.CAPT_BANNER_URL
    )
    
    emb.add_field(
        name=f"{e('STATS')}Общая статистика", 
        value=f"> {e('GAME')}Сыграно игр: **{total_games}**\n> {e('WIN')}Побед: **{total_wins}**\n> {e('LOSS')}Поражений: **{total_losses}**", 
        inline=False
    )
    
    logo = get_safe_logo()
    if logo:
        emb.set_footer(text=f"{FAM_NAME} • Авто-обновление каждую минуту", icon_url=logo)
    else:
        emb.set_footer(text=f"{FAM_NAME} • Авто-обновление каждую минуту")
        
    return emb

async def _update_or_send_stats(bot, channel, embed, data):
    found_msgs = []
    try:
        async for msg in channel.history(limit=50):
            if msg.author == bot.user and msg.embeds and "Статистика PLUS" in str(msg.embeds[0].title):
                found_msgs.append(msg)
    except Exception:
        pass

    bot_msg = None
    if found_msgs:
        bot_msg = found_msgs[0]
        data["message_id"] = bot_msg.id
        
        for m in found_msgs[1:]:
            try: await m.delete()
            except Exception: pass

    if bot_msg:
        try: await bot_msg.edit(embed=embed)
        except Exception: pass
    else:
        try:
            new_msg = await channel.send(embed=embed)
            data["message_id"] = new_msg.id
        except Exception: pass

    _stats_save(data)


@dataclass
class PlusState:
    event_type: str
    ts: int
    base_slots: int
    extra_slots: int
    closed: bool = False
    image_url: str = ""
    thumbnail_url: str = ""
    logs_enabled: bool = False
    logs_thread_id: int = 0
    revealed: bool = False
    warned: bool = False
    members: list[int] = field(default_factory=list)
    pending_members: list[int] = field(default_factory=list)
    reserve: list[int] = field(default_factory=list)
    # mode: "plus" -> кнопка сразу заносит в эмбед (старое поведение),
    #       "mcl"  -> кнопка только пишет заявку в ветку, модератор реакцией одобряет
    mode: str = "plus"
    opponent: str = ""
    map_name: str = ""
    map_image: str = ""

    @property
    def total_slots(self) -> int: return self.base_slots + self.extra_slots
    @property
    def used(self) -> int: return len(self.members)
    @property
    def reserve_used(self) -> int: return len(self.reserve)
    @property
    def is_main_full(self) -> bool: return self.used >= self.base_slots
    @property
    def is_reserve_full(self) -> bool: return self.reserve_used >= self.extra_slots
    @property
    def is_full(self) -> bool: return self.is_main_full and self.is_reserve_full

async def save_plus_state(message_id: int, channel_id: int, state: PlusState):
    async with aiosqlite.connect("data/database.sqlite") as db:
        await db.execute(
            "INSERT OR REPLACE INTO active_plus_events ("
            "message_id, channel_id, event_type, ts, base_slots, extra_slots, "
            "closed, members, revealed, warned, logs_enabled, logs_thread_id, "
            "image_url, pending_members, reserve, mode, opponent, map_name, map_image"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(message_id), str(channel_id), state.event_type, state.ts,
                state.base_slots, state.extra_slots,
                int(state.closed), json.dumps(state.members),
                int(state.revealed), int(state.warned),
                int(state.logs_enabled), str(state.logs_thread_id),
                state.image_url, json.dumps(state.pending_members),
                json.dumps(state.reserve), state.mode,
                state.opponent, state.map_name, state.map_image,
            )
        )
        await db.commit()

async def delete_plus_state(message_id: int):
    async with aiosqlite.connect("data/database.sqlite") as db:
        await db.execute("DELETE FROM active_plus_events WHERE message_id = ?", (str(message_id),))
        await db.commit()


# Полный список колонок active_plus_events в порядке, который ожидает _row_to_state.
PLUS_EVENT_COLUMNS = (
    "message_id, channel_id, event_type, ts, base_slots, extra_slots, "
    "closed, members, revealed, warned, logs_enabled, logs_thread_id, "
    "image_url, pending_members, reserve, mode, opponent, map_name, map_image"
)


def _row_to_state(row) -> tuple[str, str, "PlusState"]:
    """Распаковать строку active_plus_events (в порядке PLUS_EVENT_COLUMNS) в (message_id, channel_id, PlusState)."""
    (
        message_id, channel_id, event_type, ts, base_slots, extra_slots,
        closed, members_json, revealed, warned, logs_enabled, logs_thread_id,
        image_url, pending_json, reserve_json, mode, opponent, map_name, map_image,
    ) = row
    try: members = json.loads(members_json)
    except Exception: members = []
    try: pending_members = json.loads(pending_json)
    except Exception: pending_members = []
    try: reserve = json.loads(reserve_json) if reserve_json else []
    except Exception: reserve = []
    state = PlusState(
        event_type=event_type, ts=int(ts), base_slots=int(base_slots), extra_slots=int(extra_slots),
        closed=bool(closed),
        members=members, pending_members=pending_members, reserve=reserve,
        revealed=bool(revealed), warned=bool(warned),
        logs_enabled=bool(logs_enabled), logs_thread_id=int(logs_thread_id),
        image_url=image_url or "",
        mode=mode or "plus", opponent=opponent or "",
        map_name=map_name or "", map_image=map_image or "",
    )
    return str(message_id), str(channel_id), state


class PlusEventView(disnake.ui.View):
    def __init__(self, bot: commands.InteractionBot, state: PlusState):
        super().__init__(timeout=None)
        self.bot = bot
        self.state = state
        self.message: Optional[disnake.Message] = None
        self._tier_cache: dict[int, tuple[int, str]] = {}
        
        join_btn = disnake.ui.Button(label="Присоединиться", style=disnake.ButtonStyle.success, custom_id="plus_join", emoji=e_btn("JOIN"), row=0)
        join_btn.callback = self.join_callback
        self.add_item(join_btn)

        leave_btn = disnake.ui.Button(label="Покинуть", style=disnake.ButtonStyle.danger, custom_id="plus_leave", emoji=e_btn("LEAVE"), row=0)
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

        settings_btn = disnake.ui.Button(label="Настройки", style=disnake.ButtonStyle.secondary, custom_id="plus_settings", emoji=e_btn("SETTINGS"), row=0)
        settings_btn.callback = self.handle_settings_btn
        self.add_item(settings_btn)

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if _is_banned(inter):
            await inter.response.send_message(f"{e('REJECT')}Вы заблокированы и не можете взаимодействовать со сборами PLUS.", ephemeral=True)
            return False
        return True

    async def join_callback(self, inter: disnake.MessageInteraction):
        self.message = inter.message

        if isinstance(inter.user, disnake.Member):
            if not any(r.id == MAIN_ROLE_ID for r in inter.user.roles):
                return await inter.response.send_message(f"{e('REJECT')}Вам нужна главная роль семьи, чтобы участвовать в сборе.", ephemeral=True)

        if self.state.closed:
            return await inter.response.send_message(f"{e('REJECT')}Сбор закрыт.", ephemeral=True)
        if inter.user.id in self.state.members:
            return await inter.response.send_message(f"{e('WARNING')}Ты уже в списке участников.", ephemeral=True)
        if inter.user.id in self.state.reserve:
            return await inter.response.send_message(f"{e('WARNING')}Ты уже в резерве.", ephemeral=True)

        # /mcl режим: кнопка не вносит в эмбед, а отправляет заявку модератору в ветку
        if self.state.mode == "mcl":
            thread = None
            if self.state.logs_thread_id:
                thread = inter.guild.get_thread(self.state.logs_thread_id) or self.bot.get_channel(self.state.logs_thread_id)
            if not thread:
                return await inter.response.send_message(f"{e('ERROR')}Ветка сбора не найдена. Сообщите старшему составу.", ephemeral=True)

            if inter.user.id in self.state.pending_members:
                return await inter.response.send_message(f"{e('WARNING')}Заявка уже отправлена. Ожидай реакции модератора.", ephemeral=True)

            self.state.pending_members.append(inter.user.id)
            await save_plus_state(inter.message.id, inter.channel.id, self.state)

            _, tier_label = await self._get_tier(inter.guild, inter.user.id)
            await thread.send(
                f"{e('JOIN')} {tier_label} {inter.user.mention} подал заявку на сбор."
            )

            return await inter.response.send_message(
                f"{e('SUCCESS')}Заявка на участие отправлена в ветку сбора. Ожидай подтверждения от модератора.",
                ephemeral=True,
            )

        # /plus режим: кнопка сразу заносит в основной список или в резерв (если основной полон)
        if self.state.is_full:
            return await inter.response.send_message(f"{e('ERROR')}Слоты закончились.", ephemeral=True)

        added_to_reserve = False
        if not self.state.is_main_full:
            self.state.members.append(inter.user.id)
        else:
            self.state.reserve.append(inter.user.id)
            added_to_reserve = True

        if inter.user.id in self.state.pending_members:
            self.state.pending_members.remove(inter.user.id)

        await save_plus_state(inter.message.id, inter.channel.id, self.state)
        await self.refresh_message(inter.guild)

        if self.state.logs_thread_id:
            thread = inter.guild.get_thread(self.state.logs_thread_id)
            if thread:
                _, tier_label = await self._get_tier(inter.guild, inter.user.id)
                where = "в резерв" if added_to_reserve else "к сбору"
                await thread.send(f"{e('JOIN')} {tier_label} {inter.user.mention} присоединился {where}!")

        if added_to_reserve:
            return await inter.response.send_message(
                f"{e('SUCCESS')}Основной список заполнен — ты добавлен в резерв.",
                ephemeral=True,
            )
        return await inter.response.send_message(f"{e('SUCCESS')}Ты успешно присоединился к сбору!", ephemeral=True)

    async def leave_callback(self, inter: disnake.MessageInteraction):
        self.message = inter.message

        in_members = inter.user.id in self.state.members
        in_pending = inter.user.id in self.state.pending_members
        in_reserve = inter.user.id in self.state.reserve

        if not in_members and not in_pending and not in_reserve:
            return await inter.response.send_message(f"{e('WARNING')}Тебя нет в списках.", ephemeral=True)

        if self.state.closed:
            return await inter.response.send_message(f"{e('REJECT')}Сбор уже закрыт.", ephemeral=True)

        if in_members:
            self.state.members.remove(inter.user.id)
            self._tier_cache.pop(inter.user.id, None)
            # Освободился слот — поднимаем первого из резерва (только в режиме /plus)
            if self.state.mode == "plus" and self.state.reserve and not self.state.is_main_full:
                promoted_id = self.state.reserve.pop(0)
                self.state.members.append(promoted_id)
                if self.state.logs_thread_id:
                    thread = inter.guild.get_thread(self.state.logs_thread_id)
                    if thread:
                        try:
                            await thread.send(f"{e('JOIN')} <@{promoted_id}> поднят из резерва в основной список.")
                        except disnake.HTTPException:
                            pass
        if in_reserve:
            self.state.reserve.remove(inter.user.id)
        if in_pending:
            self.state.pending_members.remove(inter.user.id)

        await save_plus_state(inter.message.id, inter.channel.id, self.state)

        await self.refresh_message(inter.guild)
        await inter.response.send_message(f"{e('SUCCESS')}Ты покинул сбор.", ephemeral=True)

        if self.state.logs_thread_id:
            thread = inter.guild.get_thread(self.state.logs_thread_id)
            if thread:
                await thread.send(f"{e('LEAVE')} {inter.user.mention} покинул сбор.")

    async def handle_settings_btn(self, inter: disnake.MessageInteraction):
        self.message = inter.message
        await self.handle_settings(inter)

    async def _get_tier(self, guild: disnake.Guild, user_id: int) -> tuple[int, str]:
        if user_id in self._tier_cache: return self._tier_cache[user_id]
        
        member = guild.get_member(user_id)
        if not member:
            try: member = await guild.fetch_member(user_id)
            except Exception: member = None
                
        res = _tier_number_from_member(member) if member else (9, TIER_NONE_EMOJI)
        self._tier_cache[user_id] = res
        return res

    async def _participants_text(self, guild: disnake.Guild) -> str:
        if not self.state.members: return "> —"
        lines = await self._participants_lines(guild)
        if len(lines) > config.PLUS_PARTICIPANTS_MAX_LINES:
            rest = len(lines) - config.PLUS_PARTICIPANTS_MAX_LINES
            lines = lines[:config.PLUS_PARTICIPANTS_MAX_LINES]
            lines.append(f"> … + ещё {rest} участн.")
        return "\n".join(lines)

    async def _participants_lines(self, guild: disnake.Guild) -> list[str]:
        if not self.state.members: return []
        enriched = []
        for idx, uid in enumerate(self.state.members):
            tier_num, tier_label = await self._get_tier(guild, uid)
            enriched.append((tier_num, idx, uid, tier_label))
        enriched.sort(key=lambda x: (x[0], x[1]))
        return [f"> `{i:02d}.` {tier_label} <@{uid}>" for i, (_, _, uid, tier_label) in enumerate(enriched, start=1)]

    async def _reserve_lines(self, guild: disnake.Guild) -> list[str]:
        if not self.state.reserve: return []
        result = []
        for i, uid in enumerate(self.state.reserve, start=1):
            _, tier_label = await self._get_tier(guild, uid)
            result.append(f"> `{i:02d}.` {tier_label} <@{uid}>")
        return result

    async def _reserve_text(self, guild: disnake.Guild) -> str:
        if not self.state.reserve: return "> —"
        lines = await self._reserve_lines(guild)
        if len(lines) > config.PLUS_PARTICIPANTS_MAX_LINES:
            rest = len(lines) - config.PLUS_PARTICIPANTS_MAX_LINES
            lines = lines[:config.PLUS_PARTICIPANTS_MAX_LINES]
            lines.append(f"> … + ещё {rest} в резерве.")
        return "\n".join(lines)

    def _title_suffix(self) -> str:
        if self.state.mode == "plus" and self.state.opponent:
            return self.state.opponent
        return self.state.event_type.upper()

    async def build_embed(self, guild: disnake.Guild) -> disnake.Embed:
        current_ts = datetime.now(timezone.utc).timestamp()

        if self.state.closed: status = f"{e('CLOSED')}**ЗАКРЫТ**"
        elif self.state.revealed or current_ts >= self.state.ts:
            status = f"{e('TIMER')}**ОЖИДАНИЕ ИТОГОВ**"
        elif self.state.is_main_full and (self.state.extra_slots == 0 or self.state.is_reserve_full):
            status = f"{e('FULL')}**СЛОТЫ ЗАПОЛНЕНЫ**"
        else: status = f"{e('OPEN')}**СБОР ОТКРЫТ**"

        desc = (
            f"{status} • ⏳ <t:{self.state.ts}:f> (<t:{self.state.ts}:R>)\n\n"
            f"**Участники:** {e('PEOPLE')}`{self.state.used}/{self.state.base_slots}`\n"
            f"{await self._participants_text(guild)}"
        )

        if self.state.extra_slots > 0:
            desc += (
                f"\n\n**Резерв:** {e('PEOPLE')}`{self.state.reserve_used}/{self.state.extra_slots}`\n"
                f"{await self._reserve_text(guild)}"
            )

        if self.state.map_name:
            desc += f"\n\n**Карта:** `{self.state.map_name}`"

        emb = brand_embed(title=f"{e('PLUS')}Plus | {self._title_suffix()}", description=desc)

        if self.state.logs_enabled and self.state.logs_thread_id:
            emb.add_field(name=f"{e('RECEIPT')}Ветка сбора", value=f"<#{self.state.logs_thread_id}>", inline=False)
        if self.state.thumbnail_url: emb.set_thumbnail(url=self.state.thumbnail_url)
        # Приоритет: пользовательская картинка > картинка карты
        if self.state.image_url:
            emb.set_image(url=self.state.image_url)
        elif self.state.map_image:
            emb.set_image(url=self.state.map_image)
        return emb

    async def refresh_message(self, guild: disnake.Guild):
        if not self.message: return
        for child in self.children:
            if getattr(child, "custom_id", "") == "plus_join":
                # В режиме mcl кнопка остаётся активной (заявка уйдёт модератору),
                # пока сбор не закрыт. В режиме plus — пока есть слоты или резерв.
                if self.state.mode == "mcl":
                    child.disabled = self.state.closed
                else:
                    child.disabled = self.state.closed or self.state.is_full
            elif getattr(child, "custom_id", "") == "plus_leave":
                child.disabled = self.state.closed
            elif getattr(child, "custom_id", "") == "plus_settings":
                child.disabled = self.state.closed

        try: 
            embed = await self.build_embed(guild)
            await self.message.edit(embed=embed, view=self)
        except disnake.HTTPException: 
            pass

    async def _ensure_logs_thread(self) -> Optional[disnake.Thread]:
        if not self.state.logs_enabled or not self.message: return None
        if self.state.logs_thread_id:
            ch = self.bot.get_channel(int(self.state.logs_thread_id))
            if isinstance(ch, disnake.Thread): return ch
        return None

    async def log_to_thread(self, text: str):
        if thread := await self._ensure_logs_thread():
            try: await thread.send(text)
            except disnake.HTTPException: pass

    async def ping_main_role(self, channel: disnake.abc.Messageable):
        mentions = f"<@&{MAIN_ROLE_ID}>"
        try: await channel.send(mentions)
        except disnake.HTTPException: pass

    async def notify_main_role_dm(self, guild: disnake.Guild, actor_id: int):
        target_members = set()
        
        role = guild.get_role(MAIN_ROLE_ID)
        if role:
            for member in role.members:
                if not member.bot:
                    target_members.add(member)
                        
        if not target_members: return
        
        embed = disnake.Embed(
            title=f"{e('PING')}Открыт сбор PLUS!",
            description=f"Старший состав открыл сбор на **{self.state.event_type.upper()}**!\n\n{e('TIME')}**Начало:** <t:{self.state.ts}:F> (<t:{self.state.ts}:R>)\n\n[🔗 Перейдите в канал, чтобы поставить плюс]({self.message.jump_url if self.message else '#'})",
            color=disnake.Color.green()
        )
        
        logo = get_safe_logo()
        if logo:
            embed.set_footer(text=FAM_NAME, icon_url=logo)
        else:
            embed.set_footer(text=FAM_NAME)
        
        success = 0
        for member in target_members:
            try:
                await member.send(embed=embed)
                success += 1
                await asyncio.sleep(0.1) 
            except disnake.HTTPException:
                pass
                
        await self.log_to_thread(f"{e('PING')}Рассылка в ЛС завершена. Успешно: {success} чел. (админ: <@{actor_id}>)")

    async def notify_5_min_warning(self):
        if not self.state.members: return
        
        embed = disnake.Embed(
            title=f"{e('ALARM')}Скоро начало!",
            description=f"Мероприятие **PLUS | {self.state.event_type.upper()}** начнется менее чем через 5 минут!\n\nПожалуйста, заходите в игру и будьте готовы!\n\n[🔗 Перейти к сбору]({self.message.jump_url if self.message else '#'})",
            color=disnake.Color.orange()
        )
        
        logo = get_safe_logo()
        if logo:
            embed.set_footer(text=FAM_NAME, icon_url=logo)
        else:
            embed.set_footer(text=FAM_NAME)
        
        for uid in self.state.members:
            user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
            if user:
                try:
                    await user.send(embed=embed)
                    await asyncio.sleep(0.1) 
                except disnake.HTTPException:
                    pass
                    
        await self.log_to_thread(f"{e('ALARM')}Авто-уведомление за 5 минут успешно разослано участникам.")

    async def finish_plus(self, *, actor_id: int, result: str) -> tuple[bool, str]:
        if result not in ("win", "loss"): return False, "Неверный результат."
        
        stats_channel_id = int(config.CAPT_STATS_CHANNEL_ID)
        if stats_channel_id != 0:
            stats_channel = self.bot.get_channel(stats_channel_id)
            if isinstance(stats_channel, disnake.TextChannel):
                async with _STATS_LOCK:
                    data = _stats_load()
                    counts = data.get("counts") or {}
                    for k in ("capt", "mcl", "взз", "взм"):
                        if isinstance(counts.get(k), int): counts[k] = {"win": int(counts[k]), "loss": 0}
                        elif isinstance(counts.get(k), dict): counts[k].setdefault("win", 0); counts[k].setdefault("loss", 0)
                        else: counts[k] = {"win": 0, "loss": 0}
                    
                    if self.state.event_type in counts:
                        counts[self.state.event_type][result] += 1
                        
                    data["counts"], data["updated_ts"] = counts, int(datetime.now(timezone.utc).timestamp())
                    emb = _build_stats_embed(data)
                    
                    await _update_or_send_stats(self.bot, stats_channel, emb, data)
            
        res_text = "ПОБЕДА" if result == "win" else "ПОРАЖЕНИЕ"
        await self.log_to_thread(f"{e('FINISH')}PLUS завершён ({res_text}): тип={self.state.event_type.upper()}, участников={self.state.used}/{self.state.total_slots} (админ: <@{actor_id}>)")
        
        self.state.closed = True
        
        if self.message:
            await delete_plus_state(self.message.id)
            try:
                await self.message.delete()
                return True, "Сбор успешно завершён."
            except Exception:
                for item in self.children:
                    item.disabled = True
                try: await self.message.edit(view=self)
                except Exception: pass
                return True, "Сбор завершён: меню заблокировано."
        return True, "Сбор завершён."

    async def handle_settings(self, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
        await inter.response.send_message("Управление сбором:", ephemeral=True, view=PlusSettingsView(self))

    async def handle_list(self, inter: disnake.MessageInteraction):
        if not inter.guild: return await inter.response.send_message("Только на сервере.", ephemeral=True)
        lines = await self._participants_lines(inter.guild)
        if not lines: return await inter.response.send_message("Список пуст.", ephemeral=True)
        view = ParticipantListView(self, page=0)
        view._update_buttons(len(lines))
        await inter.response.send_message(embed=await view.build_page_embed(inter.guild), view=view, ephemeral=True)


class ParticipantListView(disnake.ui.View):
    def __init__(self, parent: PlusEventView, page: int = 0):
        super().__init__(timeout=180)
        self.parent = parent
        self.page = max(0, int(page))

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if _is_banned(inter):
            await inter.response.send_message(f"{e('REJECT')}Вы заблокированы.", ephemeral=True)
            return False
        return True

    async def build_page_embed(self, guild: disnake.Guild) -> disnake.Embed:
        lines = await self.parent._participants_lines(guild)
        total = len(lines)
        if total == 0: 
            desc, pages, self.page, chunk = "> Список пуст.", 1, 0, []
        else:
            pages = max(1, (total + config.PLUS_PARTICIPANTS_PAGE_SIZE - 1) // config.PLUS_PARTICIPANTS_PAGE_SIZE)
            self.page = min(self.page, pages - 1)
            chunk = lines[self.page * config.PLUS_PARTICIPANTS_PAGE_SIZE:(self.page + 1) * config.PLUS_PARTICIPANTS_PAGE_SIZE]
            
        chunk_text = "\n".join(chunk) if chunk else "> Список пуст."
        
        desc = f"**Тип:** `{self.parent.state.event_type.upper()}`\n**Слоты:** `{self.parent.state.used} / {self.parent.state.total_slots}`\n**Страница:** `{self.page + 1} / {pages}`\n\n**Участники:**\n{chunk_text}"
        
        emb = brand_embed(title=f"{e('LIST')}Список участников", description=desc)
        return emb
        
    def _update_buttons(self, total: int):
        pages = max(1, (total + config.PLUS_PARTICIPANTS_PAGE_SIZE - 1) // config.PLUS_PARTICIPANTS_PAGE_SIZE)
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= pages - 1
        
    async def _refresh(self, inter: disnake.MessageInteraction):
        if not inter.guild: return
        self._update_buttons(len(await self.parent._participants_lines(inter.guild)))
        await inter.response.edit_message(embed=await self.build_page_embed(inter.guild), view=self)
        
    @disnake.ui.button(label="Назад", style=disnake.ButtonStyle.secondary, emoji=e_btn("PREV"))
    async def prev_btn(self, button, inter): 
        self.page = max(0, self.page - 1); await self._refresh(inter)
        
    @disnake.ui.button(label="Вперед", style=disnake.ButtonStyle.secondary, emoji=e_btn("NEXT"))
    async def next_btn(self, button, inter): 
        self.page += 1; await self._refresh(inter)
        
    @disnake.ui.button(label="Закрыть", style=disnake.ButtonStyle.danger, emoji=e_btn("REJECT"))
    async def close_btn(self, button, inter): 
        await inter.response.edit_message(view=None)


class MapSelectView(disnake.ui.View):
    """Селект для смены карты у уже опубликованного сбора /mcl."""

    def __init__(self, event_view: PlusEventView):
        super().__init__(timeout=2 * 60)
        self.event_view = event_view

        current_map = event_view.state.map_name
        options: list[disnake.SelectOption] = []
        for name in MCL_MAPS.keys():
            options.append(
                disnake.SelectOption(
                    label=name[:100],
                    value=name[:100],
                    default=(name == current_map),
                )
            )

        select = disnake.ui.Select(
            placeholder="Выберите новую карту",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="plus_change_map_select",
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user):
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)

        ev = self.event_view
        if not ev.message:
            return await inter.response.send_message(
                f"{e('ERROR')}Не удалось найти исходный эмбед сбора.", ephemeral=True
            )

        try:
            values = list(getattr(inter, "values", None) or [])
            if not values:
                # Фолбэк на сырые данные интеракции, если SDK по какой-то причине
                # не пробросил inter.values.
                raw = getattr(inter, "data", None)
                if raw is not None:
                    try:
                        values = list(raw["values"])
                    except Exception:
                        values = list(getattr(raw, "values", []) or [])
            new_map_name = values[0]
        except Exception:
            return await inter.response.send_message(
                f"{e('ERROR')}Не удалось определить выбранную карту.", ephemeral=True
            )

        if new_map_name not in MCL_MAPS:
            return await inter.response.send_message(
                f"{e('ERROR')}Карта `{new_map_name}` не найдена в списке.", ephemeral=True
            )

        old_map_name = ev.state.map_name or "—"
        ev.state.map_name = new_map_name
        ev.state.map_image = MCL_MAPS.get(new_map_name, "")

        await save_plus_state(ev.message.id, ev.message.channel.id, ev.state)
        await ev.refresh_message(inter.guild)

        for child in self.children:
            child.disabled = True
        try:
            await inter.response.edit_message(
                content=f"{e('SUCCESS')}Карта сбора изменена: `{old_map_name}` → `{new_map_name}`.",
                view=self,
            )
        except disnake.HTTPException:
            pass

        await ev.log_to_thread(
            f"{e('SETTINGS')}<@{inter.user.id}> сменил карту сбора: `{old_map_name}` → `{new_map_name}`."
        )


class PlusSettingsView(disnake.ui.View):
    def __init__(self, event_view: PlusEventView):
        super().__init__(timeout=5 * 60)
        self.event_view = event_view

        # Кнопка «Сменить карту» доступна только для сборов /mcl,
        # где карта в принципе используется.
        if event_view.state.mode == "mcl":
            change_map_btn = disnake.ui.Button(
                label="Сменить карту",
                style=disnake.ButtonStyle.primary,
                row=2,
                emoji=e_btn("MAP"),
                custom_id="plus_change_map_btn",
            )
            change_map_btn.callback = self.handle_change_map
            self.add_item(change_map_btn)

    async def handle_change_map(self, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user):
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)

        ev = self.event_view
        ev.message = ev.message or inter.message

        if ev.state.mode != "mcl":
            return await inter.response.send_message(
                f"{e('WARNING')}Смена карты доступна только для сборов /mcl.",
                ephemeral=True,
            )
        if ev.state.closed:
            return await inter.response.send_message(
                f"{e('WARNING')}Сбор уже закрыт — карту менять нельзя.",
                ephemeral=True,
            )

        current = ev.state.map_name or "—"
        await inter.response.send_message(
            content=f"Текущая карта: `{current}`\nВыберите новую карту из списка:",
            view=MapSelectView(ev),
            ephemeral=True,
        )

    @disnake.ui.button(label="Список", style=disnake.ButtonStyle.secondary, row=0, emoji=e_btn("LIST"))
    async def list_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
        await self.event_view.handle_list(inter)

    @disnake.ui.button(label="Затянуть в Voice", style=disnake.ButtonStyle.primary, row=0, emoji=e_btn("VOICE"))
    async def pull_to_voice_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
            
        if not inter.user.voice or not inter.user.voice.channel:
            return await inter.response.send_message(f"{e('ERROR')}Ошибка: Вы должны находиться в голосовом канале, чтобы затянуть туда участников!", ephemeral=True)

        ev = self.event_view
        ev.message = ev.message or inter.message
        target_channel = inter.user.voice.channel

        await inter.response.defer(ephemeral=True)

        moved = 0
        for uid in ev.state.members:
            member = inter.guild.get_member(uid)
            if member and member.voice and member.voice.channel:
                if member.voice.channel.id != target_channel.id:
                    try:
                        await member.move_to(target_channel)
                        moved += 1
                        await asyncio.sleep(0.2) 
                    except:
                        pass

        await inter.followup.send(f"{e('SUCCESS')}Успешно затянуто **{moved}** участников в канал `{target_channel.name}`!", ephemeral=True)
        await ev.log_to_thread(f"{e('VOICE')}Админ <@{inter.user.id}> массово затянул {moved} участников в голосовой канал {target_channel.name}.")
        
    @disnake.ui.button(label="Оповестить в ЛС", style=disnake.ButtonStyle.primary, row=0, emoji=e_btn("DM"))
    async def notify_main_ls_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
        ev = self.event_view
        ev.message = ev.message or inter.message
        
        await inter.response.send_message("Начинаю массовую рассылку в ЛС... Это может занять несколько секунд.", ephemeral=True)
        await ev.notify_main_role_dm(inter.guild, inter.user.id)

    @disnake.ui.button(label="Победа", style=disnake.ButtonStyle.success, row=1, emoji=e_btn("WIN"))
    async def win_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        ok, msg = await self.event_view.finish_plus(actor_id=inter.user.id, result="win")
        await inter.followup.send(msg, ephemeral=True)
        if ok: await inter.edit_original_response(view=None)

    @disnake.ui.button(label="Поражение", style=disnake.ButtonStyle.danger, row=1, emoji=e_btn("LOSS"))
    async def loss_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        ok, msg = await self.event_view.finish_plus(actor_id=inter.user.id, result="loss")
        await inter.followup.send(msg, ephemeral=True)
        if ok: await inter.edit_original_response(view=None)

    @disnake.ui.button(label="Принудительно закрыть", style=disnake.ButtonStyle.danger, row=1, emoji=e_btn("LOCK"))
    async def force_close_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
            
        ev = self.event_view
        ev.message = ev.message or inter.message
        
        if ev.state.closed or ev.state.revealed:
            return await inter.response.send_message(f"{e('WARNING')}Сбор уже закрыт или время уже вышло!", ephemeral=True)
            
        await inter.response.defer(ephemeral=True)
        
        ev.state.revealed = True
        ev.state.warned = True 
        
        new_view = PlusEventView(ev.bot, ev.state)
        new_view.message = ev.message
        
        embed = await new_view.build_embed(inter.guild)
        await ev.message.edit(embed=embed, view=new_view)
        
        await save_plus_state(ev.message.id, ev.message.channel.id, ev.state)
        await ev.log_to_thread(f"{e('LOCK')}Админ <@{inter.user.id}> принудительно закрыл сбор раньше времени.")
        
        for child in self.children:
            child.disabled = True
        await inter.edit_original_response(view=self)
        
        await inter.followup.send(f"{e('SUCCESS')}Сбор принудительно закрыт. Меню обновлено.", ephemeral=True)


class PlusCog(commands.Cog):
    def __init__(self, bot): 
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_ready(self):
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS active_plus_events (
                message_id TEXT PRIMARY KEY,
                channel_id TEXT,
                event_type TEXT,
                ts INTEGER,
                base_slots INTEGER,
                extra_slots INTEGER,
                closed INTEGER,
                members TEXT,
                revealed INTEGER DEFAULT 0,
                warned INTEGER DEFAULT 0,
                logs_enabled INTEGER DEFAULT 0,
                logs_thread_id TEXT DEFAULT '0',
                image_url TEXT DEFAULT '',
                pending_members TEXT DEFAULT '[]',
                reserve TEXT DEFAULT '[]',
                mode TEXT DEFAULT 'plus',
                opponent TEXT DEFAULT '',
                map_name TEXT DEFAULT '',
                map_image TEXT DEFAULT ''
            )""")

            await db.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id TEXT PRIMARY KEY, admin_id TEXT, reason TEXT, expire_ts INTEGER)")
            await db.execute("CREATE TABLE IF NOT EXISTS ban_config (key TEXT PRIMARY KEY, value TEXT)")

            for stmt in (
                "ALTER TABLE active_plus_events ADD COLUMN revealed INTEGER DEFAULT 0",
                "ALTER TABLE active_plus_events ADD COLUMN warned INTEGER DEFAULT 0",
                "ALTER TABLE active_plus_events ADD COLUMN logs_enabled INTEGER DEFAULT 0",
                "ALTER TABLE active_plus_events ADD COLUMN logs_thread_id TEXT DEFAULT '0'",
                "ALTER TABLE active_plus_events ADD COLUMN image_url TEXT DEFAULT ''",
                "ALTER TABLE active_plus_events ADD COLUMN pending_members TEXT DEFAULT '[]'",
                "ALTER TABLE active_plus_events ADD COLUMN reserve TEXT DEFAULT '[]'",
                "ALTER TABLE active_plus_events ADD COLUMN mode TEXT DEFAULT 'plus'",
                "ALTER TABLE active_plus_events ADD COLUMN opponent TEXT DEFAULT ''",
                "ALTER TABLE active_plus_events ADD COLUMN map_name TEXT DEFAULT ''",
                "ALTER TABLE active_plus_events ADD COLUMN map_image TEXT DEFAULT ''",
            ):
                try: await db.execute(stmt)
                except Exception: pass
            await db.commit()

            async with db.execute(f"SELECT {PLUS_EVENT_COLUMNS} FROM active_plus_events") as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                message_id, channel_id, state = _row_to_state(row)

                # Подтянуть актуальный URL картинки карты из MCL_MAPS,
                # если для этого имени карта известна — это даёт
                # обновление существующих эмбедов при изменении списка карт.
                if state.map_name and state.map_name in MCL_MAPS:
                    fresh_image = MCL_MAPS.get(state.map_name, "")
                    if fresh_image and fresh_image != state.map_image:
                        state.map_image = fresh_image
                        try:
                            await save_plus_state(int(message_id), int(channel_id), state)
                        except Exception:
                            pass

                view = PlusEventView(self.bot, state)
                self.bot.add_view(view, message_id=int(message_id))

                channel = self.bot.get_channel(int(channel_id))
                if channel:
                    try:
                        msg = await channel.fetch_message(int(message_id))
                        view.message = msg
                        embed = await view.build_embed(channel.guild)
                        await msg.edit(embed=embed, view=view)
                        await asyncio.sleep(0.3)
                    except Exception:
                        pass

        if not self.auto_update_loop.is_running():
            self.auto_update_loop.start()
            
    async def _resolve_target_user(self, channel, payload: disnake.RawReactionActionEvent):
        try: msg = await channel.fetch_message(payload.message_id)
        except Exception: return None, None
        target_user = None
        if msg.author.id == self.bot.user.id:
            if msg.mentions:
                target_user = msg.mentions[0]
        else:
            target_user = msg.author
        return msg, target_user

    async def _refresh_main_message(self, guild: disnake.Guild, channel_id: str, message_id: str, state: PlusState):
        main_channel = guild.get_channel(int(channel_id))
        if not main_channel:
            return
        try:
            main_msg = await main_channel.fetch_message(int(message_id))
            view = PlusEventView(self.bot, state)
            view.message = main_msg
            embed = await view.build_embed(guild)
            await main_msg.edit(embed=embed, view=view)
        except Exception:
            pass

    async def _load_state_for_thread(self, thread_id: int) -> Optional[tuple[str, str, PlusState]]:
        async with aiosqlite.connect("data/database.sqlite") as db:
            async with db.execute(
                f"SELECT {PLUS_EVENT_COLUMNS} FROM active_plus_events WHERE logs_thread_id = ?",
                (str(thread_id),),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_state(row)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: disnake.RawReactionActionEvent):
        emoji_name = str(payload.emoji.name)
        if emoji_name not in (APPROVE_EMOJI, RESERVE_EMOJI, RESERVE_EMOJI_ALT):
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return

        member = guild.get_member(payload.user_id)
        if not member or member.bot: return
        if not _has_settings_access(member): return

        loaded = await self._load_state_for_thread(payload.channel_id)
        if not loaded: return
        message_id, channel_id, state = loaded

        if state.closed or state.revealed: return

        channel = guild.get_thread(payload.channel_id) or guild.get_channel(payload.channel_id)
        if not channel: return

        msg, target_user = await self._resolve_target_user(channel, payload)
        if not target_user or target_user.bot: return
        if _is_banned(target_user): return

        is_reserve_action = emoji_name in (RESERVE_EMOJI, RESERVE_EMOJI_ALT)

        if is_reserve_action:
            if target_user.id in state.reserve: return
            if state.is_reserve_full: return
            if target_user.id in state.members:
                state.members.remove(target_user.id)
            state.reserve.append(target_user.id)
        else:
            if target_user.id in state.members: return
            if state.is_main_full:
                # Основной полон — кладём в резерв (если есть место)
                if state.is_reserve_full:
                    return
                if target_user.id not in state.reserve:
                    state.reserve.append(target_user.id)
            else:
                if target_user.id in state.reserve:
                    state.reserve.remove(target_user.id)
                state.members.append(target_user.id)

        if target_user.id in state.pending_members:
            state.pending_members.remove(target_user.id)

        await save_plus_state(message_id, channel_id, state)
        await self._refresh_main_message(guild, channel_id, message_id, state)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: disnake.RawReactionActionEvent):
        emoji_name = str(payload.emoji.name)
        if emoji_name not in (APPROVE_EMOJI, RESERVE_EMOJI, RESERVE_EMOJI_ALT):
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return

        member = guild.get_member(payload.user_id)
        if not member or member.bot: return
        if not _has_settings_access(member): return

        loaded = await self._load_state_for_thread(payload.channel_id)
        if not loaded: return
        message_id, channel_id, state = loaded

        if state.closed or state.revealed: return

        channel = guild.get_thread(payload.channel_id) or guild.get_channel(payload.channel_id)
        if not channel: return

        msg, target_user = await self._resolve_target_user(channel, payload)
        if not target_user or target_user.bot: return

        changed = False
        if emoji_name == APPROVE_EMOJI:
            if target_user.id in state.members:
                state.members.remove(target_user.id)
                changed = True
                # При освобождении слота поднимаем первого из резерва
                if state.reserve and not state.is_main_full:
                    promoted = state.reserve.pop(0)
                    state.members.append(promoted)
        else:
            if target_user.id in state.reserve:
                state.reserve.remove(target_user.id)
                changed = True

        if not changed:
            return

        await save_plus_state(message_id, channel_id, state)
        await self._refresh_main_message(guild, channel_id, message_id, state)

    @tasks.loop(minutes=1)
    async def auto_update_loop(self):
        await update_ban_panel(self.bot)

        stats_channel = self.bot.get_channel(config.CAPT_STATS_CHANNEL_ID)
        if stats_channel:
            async with _STATS_LOCK:
                data = _stats_load()
                emb = _build_stats_embed(data)
                await _update_or_send_stats(self.bot, stats_channel, emb, data)

        now = datetime.now(timezone.utc).timestamp()
        async with aiosqlite.connect("data/database.sqlite") as db:
            async with db.execute(
                f"SELECT {PLUS_EVENT_COLUMNS} FROM active_plus_events WHERE revealed = 0 OR warned = 0"
            ) as cursor:
                rows = await cursor.fetchall()

        for row in rows:
            message_id, channel_id, state = _row_to_state(row)
            channel = self.bot.get_channel(int(channel_id))
            if not channel: continue
            guild = channel.guild

            try:
                msg = await channel.fetch_message(int(message_id))

                changed = False

                if not state.warned and now >= (state.ts - 300) and now < state.ts:
                    view = PlusEventView(self.bot, state)
                    view.message = msg
                    await view.notify_5_min_warning()
                    state.warned = True
                    changed = True

                if not state.revealed and now >= state.ts:
                    state.revealed = True
                    view = PlusEventView(self.bot, state)
                    view.message = msg

                    embed = await view.build_embed(guild)
                    await msg.edit(embed=embed, view=view)
                    changed = True

                if changed:
                    async with aiosqlite.connect("data/database.sqlite") as db2:
                        await db2.execute(
                            "UPDATE active_plus_events SET revealed = ?, warned = ? WHERE message_id = ?",
                            (int(state.revealed), int(state.warned), str(message_id)),
                        )
                        await db2.commit()

            except Exception:
                pass
    
    @staticmethod
    def _parse_event_time(date_time: str) -> Optional[datetime]:
        now = datetime.now(TZ_UTC3)
        dt_str = date_time.strip()
        if re.match(r"^\d{1,2}:\d{2}$", dt_str):
            try:
                hour, minute = map(int, dt_str.split(":"))
                target_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target_dt <= now:
                    target_dt += timedelta(days=1)
                return target_dt
            except Exception:
                return None
        for fmt in ("%d.%m %H:%M", "%d.%m.%Y %H:%M", "%d/%m %H:%M", "%d-%m %H:%M"):
            try:
                parsed = datetime.strptime(dt_str, fmt)
                year = parsed.year if "%Y" in fmt else now.year
                return now.replace(year=year, month=parsed.month, day=parsed.day,
                                   hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
            except ValueError:
                continue
        return None

    async def _publish_plus_event(self, inter: disnake.ApplicationCommandInteraction, state: PlusState, *, intro_text: str):
        publish_channel = inter.channel

        event_view = PlusEventView(self.bot, state)
        await event_view.ping_main_role(publish_channel)
        msg = await publish_channel.send(embed=await event_view.build_embed(inter.guild), view=event_view)
        event_view.message = msg

        try:
            thread_name = f"сбор-{(state.opponent or state.event_type)}".lower()[:90]
            thread = await msg.create_thread(name=thread_name, auto_archive_duration=1440)
            state.logs_enabled = True
            state.logs_thread_id = thread.id

            await thread.edit(locked=False)
            await thread.send(intro_text)
            await msg.edit(embed=await event_view.build_embed(inter.guild))
        except Exception:
            pass

        await save_plus_state(msg.id, msg.channel.id, state)
        await inter.followup.send(
            f"{e('SUCCESS')}Сбор успешно создан и опубликован!\n[🔗 Перейти к сообщению]({msg.jump_url})",
            ephemeral=True,
        )

    @commands.slash_command(name="plus", description="Создать сбор PLUS на CAPT (с резервом)")
    async def plus(
        self,
        inter: disnake.ApplicationCommandInteraction,
        opponent: str = commands.Param(name="против_кого", description="Команда противника (выводится в заголовке эмбеда)"),
        date_time: str = commands.Param(name="время", description="Время и дата по МСК (например: 25.10 18:30 или 18:30)"),
        extra_slots: int = commands.Param(name="доп_слоты", default=0, description="Сколько слотов резерва открыть (по умолчанию 0)"),
        base_slots: int = commands.Param(name="количество", default=PLUS_CAPT_DEFAULT_BASE_SLOTS, description=f"Основные слоты (по умолчанию {PLUS_CAPT_DEFAULT_BASE_SLOTS})"),
        image_file: disnake.Attachment = commands.Param(name="картинка_файл", default=None, description="Загрузить картинку с устройства (ПК/Телефон)"),
        image_link: str = commands.Param(name="картинка_ссылка", default=None, description="Вставить ссылку на картинку (из интернета)"),
    ):
        if _is_banned(inter):
            return await inter.response.send_message(f"{e('REJECT')}Вы заблокированы и не можете создавать сборы.", ephemeral=True)

        target_dt = self._parse_event_time(date_time)
        if not target_dt:
            return await inter.response.send_message(
                f"{e('ERROR')}Неверный формат времени! Введите `ЧЧ:ММ` (на сегодня/завтра) или `ДД.ММ ЧЧ:ММ` (например: 25.10 18:30).",
                ephemeral=True,
            )

        if base_slots <= 0 or extra_slots < 0:
            return await inter.response.send_message(f"{e('ERROR')}Слоты должны быть положительными числами!", ephemeral=True)

        opponent_clean = opponent.strip()
        if not opponent_clean:
            return await inter.response.send_message(f"{e('ERROR')}Укажите команду противника.", ephemeral=True)

        final_image_url = ""
        if image_file:
            final_image_url = image_file.url
        elif image_link:
            final_image_url = image_link.strip()

        await inter.response.defer(ephemeral=True)

        state = PlusState(
            event_type="capt",
            ts=int(target_dt.timestamp()),
            base_slots=base_slots,
            extra_slots=extra_slots,
            image_url=final_image_url,
            mode="plus",
            opponent=opponent_clean,
        )
        intro = (
            f"{e('OPEN')}**Ветка сбора открыта!**\n"
            f"Кнопка под основным сообщением сразу заносит участника в список. "
            f"Если основной список заполнен, попадание идёт в резерв ({extra_slots} слотов)."
        )
        await self._publish_plus_event(inter, state, intro_text=intro)

    @commands.slash_command(name="mcl", description="Создать сбор MCL/ВЗЗ/ВЗМ (с подтверждением модератора)")
    async def mcl(
        self,
        inter: disnake.ApplicationCommandInteraction,
        event_type: str = commands.Param(name="мп", choices=["mcl", "взз", "взм"], description="Тип МП"),
        date_time: str = commands.Param(name="время", description="Время и дата по МСК (например: 25.10 18:30 или 18:30)"),
        base_slots: int = commands.Param(name="количество", description="Сколько участников (основные слоты)"),
        map_choice: str = commands.Param(name="карта", choices=list(MCL_MAPS.keys()), description="Выбери карту из списка"),
        extra_slots: int = commands.Param(name="доп_слоты", default=0, description="Сколько слотов резерва открыть (по умолчанию 0)"),
        image_file: disnake.Attachment = commands.Param(name="картинка_файл", default=None, description="Своя картинка с устройства"),
        image_link: str = commands.Param(name="картинка_ссылка", default=None, description="Своя ссылка на картинку"),
    ):
        if _is_banned(inter):
            return await inter.response.send_message(f"{e('REJECT')}Вы заблокированы и не можете создавать сборы.", ephemeral=True)

        target_dt = self._parse_event_time(date_time)
        if not target_dt:
            return await inter.response.send_message(
                f"{e('ERROR')}Неверный формат времени! Введите `ЧЧ:ММ` (на сегодня/завтра) или `ДД.ММ ЧЧ:ММ` (например: 25.10 18:30).",
                ephemeral=True,
            )

        if base_slots <= 0 or extra_slots < 0:
            return await inter.response.send_message(f"{e('ERROR')}Слоты должны быть положительными числами!", ephemeral=True)

        final_image_url = ""
        if image_file:
            final_image_url = image_file.url
        elif image_link:
            final_image_url = image_link.strip()

        map_name = (map_choice or "").strip()
        map_image = MCL_MAPS.get(map_name, "") if map_name else ""

        await inter.response.defer(ephemeral=True)

        state = PlusState(
            event_type=event_type,
            ts=int(target_dt.timestamp()),
            base_slots=base_slots,
            extra_slots=extra_slots,
            image_url=final_image_url,
            mode="mcl",
            map_name=map_name,
            map_image=map_image,
        )
        intro = (
            f"{e('OPEN')}**Ветка сбора открыта!**\n"
            f"Нажми «Присоединиться» под основным сообщением — заявка появится здесь. "
            f"Модератор поставит {APPROVE_EMOJI} чтобы внести в основной список или {RESERVE_EMOJI} чтобы внести в резерв."
        )
        await self._publish_plus_event(inter, state, intro_text=intro)

    @commands.slash_command(name="bancapt", description="Управление BAN CAPT")
    async def bancapt_base(self, inter): pass
    
    @bancapt_base.sub_command(name="setup_panel", description="[АДМИН] Установить панель BAN CAPT в текущий канал")
    async def bancapt_setup(self, inter: disnake.ApplicationCommandInteraction):
        if not inter.author.guild_permissions.administrator:
            return await inter.response.send_message(f"{e('REJECT')}Только для администраторов.", ephemeral=True)
            
        embed = disnake.Embed(title="Список заблокированных - BAN CAPT", description="Загрузка...", color=EMBED_COLOR)
        await inter.response.send_message("Создаю панель...", ephemeral=True)
        msg = await inter.channel.send(embed=embed)
        
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute("INSERT OR REPLACE INTO ban_config (key, value) VALUES ('channel_id', ?)", (str(inter.channel.id),))
            await db.execute("INSERT OR REPLACE INTO ban_config (key, value) VALUES ('message_id', ?)", (str(msg.id),))
            await db.commit()
            
        await update_ban_panel(self.bot)

    @bancapt_base.sub_command(name="add", description="[АДМИН] Выдать BAN CAPT игроку")
    async def bancapt_add(self, inter: disnake.ApplicationCommandInteraction, user: disnake.Member, days: int = commands.Param(description="На сколько дней выдать блокировку?"), reason: str = commands.Param(description="Причина бана")):
        if not _has_settings_access(inter.author):
            return await inter.response.send_message(f"{e('REJECT')}Нет прав.", ephemeral=True)
            
        if days <= 0:
            return await inter.response.send_message(f"{e('ERROR')}Срок должен быть больше 0.", ephemeral=True)
            
        expire_ts = int(time.time()) + (days * 86400)
        
        role = inter.guild.get_role(BAN_CAPT_ROLE_ID)
        if role:
            try: await user.add_roles(role, reason=f"Выдал: {inter.author.name} | {reason}")
            except: pass
            
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute("INSERT OR REPLACE INTO banned_users (user_id, admin_id, reason, expire_ts) VALUES (?, ?, ?, ?)", (str(user.id), str(inter.author.id), reason, expire_ts))
            await db.commit()
            
        await inter.response.send_message(f"{e('SUCCESS')}Пользователь {user.mention} получил BAN CAPT на {days} дн.", ephemeral=True)
        await update_ban_panel(self.bot)

    @bancapt_base.sub_command(name="remove", description="[АДМИН] Снять BAN CAPT досрочно")
    async def bancapt_remove(self, inter: disnake.ApplicationCommandInteraction, user: disnake.Member):
        if not _has_settings_access(inter.author):
            return await inter.response.send_message(f"{e('REJECT')}Нет прав.", ephemeral=True)
            
        role = inter.guild.get_role(BAN_CAPT_ROLE_ID)
        if role:
            try: await user.remove_roles(role, reason="Снято досрочно")
            except: pass
            
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute("DELETE FROM banned_users WHERE user_id = ?", (str(user.id),))
            await db.commit()
            
        await inter.response.send_message(f"{e('SUCCESS')}С {user.mention} снят BAN CAPT.", ephemeral=True)
        await update_ban_panel(self.bot)

def setup(bot): bot.add_cog(PlusCog(bot))