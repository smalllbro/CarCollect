# Copyright (C) 2025 smalllbro42
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database
from logic import GameLogic
from middlewares.main_middlewares import IsAdmin
from utils.helpers import format_value

router = Router()

# === Обработчики команд ===

@router.message(Command("enable_airdrops"), IsAdmin())
async def cmd_enable_airdrops(message: Message, db: Database):
    if message.chat.type not in ('group', 'supergroup'):
        return await message.reply("Эту команду можно использовать только в группах.")

    parts = message.text.split()
    cooldown_hours = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else config.DEFAULT_AIRDROP_COOLDOWN / 3600
    cooldown_seconds = int(cooldown_hours * 3600)

    db.add_or_update_chat(message.chat.id, message.chat.title)
    db.update_airdrop_settings(message.chat.id, enabled=True, cooldown_seconds=cooldown_seconds)
    await message.answer(f"✅ Дропы в этом чате включены! Периодичность: раз в {cooldown_hours} ч.")


@router.message(Command("disable_airdrops"), IsAdmin())
async def cmd_disable_airdrops(message: Message, db: Database):
    if message.chat.type not in ('group', 'supergroup'):
        return await message.reply("Эту команду можно использовать только в группах.")
    
    db.update_airdrop_settings(message.chat.id, enabled=False)
    await message.answer("❌ Дропы в этом чате отключены.")


# === Обработчики колбэков ===

@router.callback_query(F.data == "group:garage_list")
async def cq_group_garage_list(call: CallbackQuery, db: Database):
    all_cars = db.get_filtered_garage(call.from_user.id, {})
    if not all_cars:
        return await call.answer("Ваш гараж пуст!", show_alert=True)
    
    car_list_text = f"<b>🏎️ Гараж игрока {call.from_user.full_name}:</b>\n\n"
    for car in all_cars:
        style = config.RARITY_STYLES.get(car['rarity'], {})
        count_str = f" x{car['count']}" if car['count'] > 1 else ""
        car_list_text += f"{style.get('color', '')} {car['car_name']}{count_str} ({format_value(car['value'])})\n"
    
    await call.message.answer(car_list_text[:4000]) # Обрезаем на всякий случай
    await call.answer()


@router.callback_query(F.data == "group:leaderboard")
async def cq_group_leaderboard(call: CallbackQuery, db: Database):
    leaderboard_data = db.get_group_leaderboard(call.message.chat.id)
    if not leaderboard_data:
        return await call.answer("В этом чате пока нет игроков с машинами.", show_alert=True)

    text = f"🏆 <b>Топ игроков в чате \"{call.message.chat.title}\":</b>\n\n"
    for i, row in enumerate(leaderboard_data, 1):
        place_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"<b>{i}.</b>")
        text += f"{place_emoji} {row['nickname']} - {format_value(row['total_value'])}\n"
    
    await call.message.answer(text)
    await call.answer()


@router.callback_query(F.data.startswith("claim_airdrop:"))
async def cq_claim_airdrop(call: CallbackQuery, db: Database, logic: GameLogic):
    claim_id = int(call.data.split(":")[1])
    user_id = call.from_user.id

    if db.claim_airdrop(claim_id, user_id):
        result = logic.open_case(user_id, config.AIRDROP_CASE_NAME, use_cooldown=False)
        if result['status'] == 'success':
            car = result['car']
            style = config.RARITY_STYLES.get(car['rarity'], {})
            await call.answer(f"🎉 Вы получили машину: {car['name']}!", show_alert=True)
            
            new_text = (
                f"🎁 <b>Дроп забран!</b>\n\n"
                f"Счастливчик: {call.from_user.full_name}\n"
                f"Приз: {style.get('color', '')} {car['name']}"
            )
            await call.message.edit_text(new_text, reply_markup=None)
        else:
            await call.answer("Ошибка при выдаче приза. Обратитесь к администратору.", show_alert=True)
    else:
        await call.answer("Этот дроп уже кто-то забрал!", show_alert=True)

