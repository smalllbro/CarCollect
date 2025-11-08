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
import asyncio
import random
import time

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database
from utils.helpers import format_time, back_to_menu_kb, safe_edit_text, answer_in_private

router = Router()


# === Клавиатуры ===

def minigames_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Кинуть кубик", callback_data="roll_dice")
    builder.button(text="🪙 Бросить монетку", callback_data="coin_flip_menu")
    builder.button(text="↩️ В меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def coin_flip_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Орел", callback_data="flip:heads")
    builder.button(text="Решка", callback_data="flip:tails")
    return builder.as_markup()


# === Обработчики ===

@router.callback_query(F.data == "minigames_menu")
async def cq_minigames_menu(call: CallbackQuery, db: Database, bot: Bot):
    if call.message.chat.type != 'private':
        return await answer_in_private(call, bot, "Перехожу в раздел мини-игр...")

    user = db.get_user(call.from_user.id)
    attempts = user.get('extra_attempts', 0) if user else 0
    text = (
        "<b>🎲 Мини игры</b>\n\n"
        "Здесь вы можете испытать свою удачу и получить бонусы!\n\n"
        f"Дополнительных попыток: <b>{attempts}</b>"
    )
    await safe_edit_text(call, text, reply_markup=minigames_menu_kb())
    await call.answer()


@router.callback_query(F.data == "roll_dice")
async def cq_roll_dice(call: CallbackQuery, db: Database, bot: Bot):
    user_id = call.from_user.id
    db.check_and_update_pass_status(user_id)
    user = db.get_user(user_id)

    has_pass = user.get('collect_pass_active', False)
    last_roll = user.get('last_dice_roll', 0)
    
    pass_activation_time = user.get('collect_pass_expires_at', 0) - config.COLLECT_PASS_DURATION
    is_pass_active = has_pass and last_roll >= pass_activation_time
    cooldown = config.DICE_COOLDOWN_PASS if is_pass_active else config.DICE_COOLDOWN
    
    now = int(time.time())
    if now - last_roll < cooldown:
        remaining = format_time(int(cooldown - (now - last_roll)))
        return await call.answer(f"⌛ Кинуть кубик можно через: {remaining}", show_alert=True)

    dice_message = await bot.send_dice(call.from_user.id)
    await call.answer()
    await asyncio.sleep(4)
    dice_roll = dice_message.dice.value
    db.update_dice_roll(user_id, dice_roll)
    new_attempts = user.get('extra_attempts', 0) + dice_roll
    text = f"Вам выпало: <b>{dice_roll}</b>!\n\nВы получили {dice_roll} доп. попыток.\nТеперь у вас: <b>{new_attempts}</b>"
    await bot.send_message(call.from_user.id, text, reply_markup=back_to_menu_kb(minigame=True))


@router.callback_query(F.data == "coin_flip_menu")
async def cq_coin_flip_menu(call: CallbackQuery, db: Database):
    user_id = call.from_user.id
    db.check_and_update_pass_status(user_id)
    user = db.get_user(user_id)
    
    has_pass = user.get('collect_pass_active', False)
    last_flip = user.get('last_coin_flip', 0)
    pass_activation_time = user.get('collect_pass_expires_at', 0) - config.COLLECT_PASS_DURATION
    is_pass_active = has_pass and last_flip >= pass_activation_time
    cooldown = config.COIN_FLIP_COOLDOWN_PASS if is_pass_active else config.COIN_FLIP_COOLDOWN
        
    now = int(time.time())
    if now - last_flip < cooldown:
        remaining = format_time(int(cooldown - (now - last_flip)))
        return await call.answer(f"⌛ Бросить монетку можно через: {remaining}", show_alert=True)
    
    await safe_edit_text(call, "Орел или решка?", reply_markup=coin_flip_kb())
    await call.answer()


@router.callback_query(F.data.startswith("flip:"))
async def cq_play_coin_flip(call: CallbackQuery, db: Database):
    user_choice = call.data.split(":")[1]
    user_id = call.from_user.id
    
    db.check_and_update_pass_status(user_id)
    user = db.get_user(user_id)
    
    db.set_last_coin_flip_time(user_id)
    bot_choice = random.choice(['heads', 'tails'])
    
    if user_choice == bot_choice:
        db.change_tires(user_id, 1, "Победа в 'Броске монетки'")
        new_total = user.get('tires', 0) + 1
        result_text = f"Выпал(а) <b>{'орел' if bot_choice == 'heads' else 'решка'}</b>! Вы угадали!\n\n" \
                      f"🎉 +1 покрышка! Теперь у вас: <b>{new_total} 🛞</b>"
    else:
        result_text = f"Выпал(а) <b>{'орел' if bot_choice == 'heads' else 'решка'}</b>! Вы не угадали.\n\n" \
                      "Повезет в следующий раз!"
                      
    await safe_edit_text(call, result_text, reply_markup=back_to_menu_kb(minigame=True))
    await call.answer()
