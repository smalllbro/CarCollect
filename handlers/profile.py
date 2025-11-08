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
import re
import asyncio
import time 

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database
from logic import GameLogic
from utils.fsm import Form
from utils.helpers import format_time, safe_edit_text, get_main_menu_content, answer_in_private

router = Router()


# === Клавиатуры ===

def profile_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Сменить ник", callback_data="change_nick_start")
    builder.button(text="🤝 Пригласить друзей", callback_data="referral_info")
    builder.button(text="↩️ В меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


# === Обработчики ===

@router.callback_query(F.data == "profile_menu")
async def cq_profile_menu(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    if call.message.chat.type != 'private':
        return await answer_in_private(call, bot, "Перехожу в ваш профиль...")

    await state.clear()
    user = db.get_user(call.from_user.id)
    if not user:
        return await call.answer("Не удалось найти ваш профиль.", show_alert=True)

    has_pass = db.check_and_update_pass_status(call.from_user.id)
    text = (
        f"<b>👤 Ваш профиль</b>\n\n"
        f"<b>Никнейм:</b> {user.get('nickname', call.from_user.id)}\n"
        f"<b>Приглашено друзей:</b> {user.get('referral_count', 0)}\n"
        f"<b>Бесплатных смен ника:</b> {user.get('free_nick_changes', 0)}\n"
    )

    if has_pass:
        remaining = user.get('collect_pass_expires_at', 0) - int(time.time())
        text += f"\n⭐ <b>CollectPass активен еще:</b> {format_time(remaining)}"
    
    await safe_edit_text(call, text, reply_markup=profile_menu_kb())
    await call.answer()


@router.callback_query(F.data == "referral_info")
async def cq_referral_info(call: CallbackQuery, db: Database, bot: Bot):
    user = db.get_user(call.from_user.id)
    if not user:
        return await call.answer("Не удалось найти ваш профиль.", show_alert=True)

    bot_info = await bot.get_me()
    referral_link = f"https://t.me/{bot_info.username}?start={call.from_user.id}"
    text = (
        f"🤝 <b>Ваша реферальная программа</b>\n\n"
        "За каждых 5 приглашенных друзей вы получите 5 доп. попыток открытия кейса.\n\n"
        f"<b>Приглашено друзей:</b> {user.get('referral_count', 0)}\n\n"
        f"<b>Ваша ссылка для приглашения:</b>\n"
        f"<code>{referral_link}</code>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="↩️ Назад в профиль", callback_data="profile_menu")
    await safe_edit_text(call, text, reply_markup=builder.as_markup())
    await call.answer()


@router.message(Command("promo"))
async def cmd_activate_promo(message: Message, db: Database, logic: GameLogic):
    user_id = message.from_user.id
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("Пожалуйста, введите промокод после команды.\nПример: <code>/promo MYCODE123</code>")
        
    code_text = parts[1].upper()
    promo = db.get_promo_by_text(code_text)
    
    # 1. Проверка существования и активности промокода
    if not promo or not promo['is_active']:
        return await message.answer("❌ Промокод не найден или неактивен.")
        
    # 2. Проверка лимита активаций
    if promo['max_activations'] > 0 and promo['current_activations'] >= promo['max_activations']:
        return await message.answer("❌ Этот промокод уже достиг лимита активаций.")
        
    # 3. Проверка, активировал ли пользователь этот промокод ранее
    if db.get_user_activation(user_id, promo['code_id']):
        return await message.answer("❌ Вы уже активировали этот промокод.")
        
    # Все проверки пройдены, выдаем награду
    reward_type = promo['reward_type']
    reward_value = promo['reward_value']
    reward_car_name = promo['reward_car_name']
    
    success_message = ""
    
    if reward_type == 'tires':
        db.change_tires(user_id, reward_value, f"Активация промокода {code_text}")
        success_message = f"✅ Промокод успешно активирован! Вам начислено <b>{reward_value} 🛞</b>."
    
    elif reward_type == 'extra_attempts':
        db.add_extra_attempts(user_id, reward_value)
        success_message = f"✅ Промокод успешно активирован! Вам начислено <b>{reward_value}</b> доп. попыток."
        
    elif reward_type == 'car':
        found_car = None
        for case_data in logic.cases.values():
            for car in case_data['cars']:
                if car['name'] == reward_car_name:
                    found_car = car
                    break
            if found_car: break
            
        if found_car:
            db.add_car(
                user_id=user_id,
                name=found_car["name"],
                rarity=found_car["rarity"],
                value=found_car["value"],
                brand=found_car.get("brand"),
                season=found_car.get("season"),
                image_file_id=found_car.get("image_file_id")
            )
            success_message = f"✅ Промокод успешно активирован! Вы получили машину: <b>{found_car['name']}</b>."
        else:
            return await message.answer("❌ Ошибка: не удалось найти машину из промокода. Обратитесь в поддержку.")

    # Завершаем активацию
    db.activate_promo_for_user(user_id, promo['code_id'])
    await message.answer(success_message)

# === Смена ника ===

@router.callback_query(F.data == "change_nick_start")
async def cq_change_nick_start(call: CallbackQuery, state: FSMContext, db: Database):
    await state.set_state(Form.changing_nickname)
    user = db.get_user(call.from_user.id)
    has_pass = db.check_and_update_pass_status(call.from_user.id)

    text = "Введите ваш новый никнейм.\n\n"
    if user.get('free_nick_changes', 0) > 0:
        text += f"У вас осталось <b>{user['free_nick_changes']}</b> бесплатных смен."
    else:
        cost = config.COLLECT_PASS_NICK_CHANGE_COST if has_pass else config.NICK_CHANGE_COST
        text += f"Стоимость смены: <b>{cost} 🛞</b>"

    kb = InlineKeyboardBuilder().button(text="Отмена", callback_data="cancel_nick_change").as_markup()
    await safe_edit_text(call, text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "cancel_nick_change", Form.changing_nickname)
async def cq_cancel_nick_change(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    await state.clear()
    await cq_profile_menu(call, state, db, bot)


@router.message(Form.changing_nickname)
async def process_new_nickname(message: Message, state: FSMContext, db: Database):
    await state.clear()
    user_id = message.from_user.id
    new_nick = message.text

    # Валидация
    if not re.match("^[a-zA-Zа-яА-Я0-9_]{4,20}$", new_nick):
        await message.answer("❌ Ник может содержать только латиницу, кириллицу, цифры и '_', длина от 4 до 20 символов.")
        await asyncio.sleep(2)
        text, kb = await get_main_menu_content(db, user_id)
        return await message.answer(text, reply_markup=kb)
    
    if db.is_nickname_taken(new_nick):
        await message.answer("❌ Этот никнейм уже занят.")
        await asyncio.sleep(2)
        text, kb = await get_main_menu_content(db, user_id)
        return await message.answer(text, reply_markup=kb)

    user = db.get_user(user_id)
    is_free_change = user.get('free_nick_changes', 0) > 0
    has_pass = db.check_and_update_pass_status(user_id)
    cost = config.COLLECT_PASS_NICK_CHANGE_COST if has_pass else config.NICK_CHANGE_COST
    user_tires = user.get('tires', 0)

    if not is_free_change and user_tires < cost:
        await message.answer(f"❌ Недостаточно покрышек! Нужно: {cost} 🛞")
        await asyncio.sleep(2)
        text, kb = await get_main_menu_content(db, user_id)
        return await message.answer(text, reply_markup=kb)

    if not is_free_change:
        db.change_tires(user_id, -cost, "Смена никнейма")

    db.change_nickname(user_id, new_nick, is_free=is_free_change)
    
    await message.answer(f"✅ Никнейм успешно изменен на <b>{new_nick}</b>!")
    await asyncio.sleep(2)
    text, kb = await get_main_menu_content(db, user_id)
    await message.answer(text, reply_markup=kb)

