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
import time
import logging
from typing import Dict, Any
from contextlib import suppress

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (CallbackQuery, Message, LabeledPrice,
                           PreCheckoutQuery, SuccessfulPayment, FSInputFile, InlineKeyboardMarkup)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database
from logic import GameLogic
from utils.helpers import (format_time, format_value, back_to_menu_kb,
                           safe_edit_text, answer_in_private)

router = Router()

# === Кейсы ===

async def show_won_car(call: CallbackQuery, bot: Bot, car_data: Dict[str, Any], db: Database):
    user_id = call.from_user.id
    style = config.RARITY_STYLES.get(car_data['rarity'], {})
    text = (
        "✨Забирай новую карту!✨\n\n"
        f"🚘 {car_data['name']}\n"
        f"💎 Редкость: {style.get('name', car_data['rarity'])}\n"
        f"💵 Стоимость: {format_value(car_data['value'])}\n\n"
        "@carcollect_bot"
    )
    
    photo_id = car_data.get("image_file_id")
    photo_to_send = photo_id if (isinstance(photo_id, str) and photo_id) else FSInputFile("images/default_car.png")

    user = db.get_user(user_id)
    attempts_left = user.get('extra_attempts', 0)
    builder = InlineKeyboardBuilder()

    if attempts_left > 0:
        builder.button(text=f"Открыть следующую ({attempts_left})", callback_data="confirm_open_case")
    if attempts_left >= 2 and db.check_and_update_pass_status(user_id):
        builder.button(text=f"⭐ Открыть все ({attempts_left})", callback_data="open_all_cases")
    builder.button(text="↩️ В меню", callback_data="main_menu")
    builder.adjust(1)
    
    with suppress(TelegramBadRequest):
        await call.message.delete()
        
    try:
        await bot.send_photo(call.from_user.id, photo=photo_to_send, caption=text, reply_markup=builder.as_markup())
    except TelegramBadRequest as e:
        logging.warning(f"Failed to send photo by file_id, falling back. Error: {e}")
        try:
            fallback_photo = FSInputFile("images/default_car.png")
            await bot.send_photo(call.from_user.id, photo=fallback_photo, caption=text, reply_markup=builder.as_markup())
        except Exception as final_e:
            logging.error(f"Failed to send even fallback photo. Error: {final_e}")
            await bot.send_message(call.from_user.id, text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "open_case_menu")
async def cq_open_case_menu(call: CallbackQuery, db: Database, bot: Bot):
    if call.message.chat.type != 'private':
        return await answer_in_private(call, bot, "Перехожу к открытию кейсов...")

    user_id = call.from_user.id
    db.check_and_update_pass_status(user_id)
    user = db.get_user(user_id)
	
    if not user:
        db.add_user(user_id, call.from_user.username)
        user = db.get_user(user_id)
        if not user:
            await call.answer("Произошла ошибка с вашим профилем. Пожалуйста, попробуйте перезапустить бота командой /start.", show_alert=True)
            return
			
    has_pass = user.get('collect_pass_active', False)
    last_time = user.get('last_free_case', 0)
    pass_activation_time = user.get('collect_pass_expires_at', 0) - config.COLLECT_PASS_DURATION
    is_pass_active = has_pass and last_time >= pass_activation_time
    cooldown = config.FREE_CASE_COOLDOWN_PASS if is_pass_active else config.FREE_CASE_COOLDOWN

    remaining_seconds = cooldown - (int(time.time()) - last_time)
    extra_attempts = user.get('extra_attempts', 0)

    text = f"До бесплатного кейса: <b>{format_time(remaining_seconds)}</b>\nДоп. попыток: <b>{extra_attempts}</b>"
    builder = InlineKeyboardBuilder()
    if extra_attempts > 0 or remaining_seconds <= 0:
        builder.button(text="Открыть кейс", callback_data="confirm_open_case")
    builder.button(text="↩️ В меню", callback_data="main_menu")
    builder.adjust(1)
    
    await safe_edit_text(call, text, reply_markup=builder.as_markup())
    await call.answer()

@router.callback_query(F.data == "confirm_open_case")
async def cq_confirm_open_case(call: CallbackQuery, bot: Bot, db: Database, logic: GameLogic):
    user_id = call.from_user.id
    user = db.get_user(user_id)
    use_cooldown = True

    if user.get('extra_attempts', 0) > 0:
        db.use_extra_attempt(user_id)
        use_cooldown = False
        await call.answer("Используем доп. попытку...", show_alert=False)

    result = logic.open_case(user_id, "free", use_cooldown=use_cooldown)

    if result["status"] == "success":
        await show_won_car(call, bot, result["car"], db)
    elif result["status"] == "cooldown":
        await call.answer(f"⌛ Кейс будет доступен через: {format_time(result['remaining'])}", show_alert=True)
        await cq_open_case_menu(call, db, bot)
    else:
        await call.answer(f"❌ Ошибка: {result.get('message', 'Неизвестная ошибка')}", show_alert=True)


@router.callback_query(F.data == "open_all_cases")
async def cq_open_all_cases(call: CallbackQuery, bot: Bot, db: Database, logic: GameLogic):
    user_id = call.from_user.id
    if not db.check_and_update_pass_status(user_id):
        return await call.answer("⭐ Эта функция доступна только с CollectPass.", show_alert=True)
    
    user = db.get_user(user_id)
    attempts = user.get('extra_attempts', 0)
    if attempts < 2:
        return await call.answer("Недостаточно попыток.", show_alert=True)

    await call.message.edit_caption(caption=f"Открываем {attempts} кейсов...")
    won_cars = [res["car"] for _ in range(attempts) if (res := logic.open_case(user_id, "free", False))["status"] == "success"]

    if not won_cars:
        await call.answer("Не удалось открыть кейсы.", show_alert=True)
        return await cq_open_case_menu(call, db, bot)

    db.clear_extra_attempts(user_id)
    car_counts = {}
    for car in won_cars:
        car_counts[car['name']] = car_counts.get(car['name'], {'count': 0, 'rarity': car['rarity']})
        car_counts[car['name']]['count'] += 1

    sorted_cars = sorted(car_counts.items(), key=lambda i: list(config.RARITY_STYLES.keys()).index(i[1]['rarity']), reverse=True)
    result_text = f"<b>🎉 Ваш улов из {len(won_cars)} кейсов:</b>\n\n" + "\n".join([
        f"{config.RARITY_STYLES.get(data['rarity'], {}).get('color', '')} {name}{f' x{data['count']}' if data['count'] > 1 else ''}"
        for name, data in sorted_cars
    ])
    
    with suppress(TelegramBadRequest):
        await call.message.delete()
    await call.message.answer(result_text, reply_markup=back_to_menu_kb())
    await call.answer()


# === Магазин ===

async def shop_menu_kb(db: Database, user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    has_pass = db.check_and_update_pass_status(user_id)

    if page == 0:
        builder.button(text="⭐ CollectPass", callback_data="collect_pass_shop_info")
        for pack_id, pack in config.ATTEMPT_PACKS.items():
            cost = round(pack['cost'] * (1 - config.ATTEMPTS_DISCOUNT_PERCENT / 100)) if has_pass else pack['cost']
            builder.button(text=f"Купить {pack['attempts']} попыток ({cost} 🛞)", callback_data=f"buy_attempt:{pack_id}")
        builder.button(text="Купить покрышки за ⭐ ➡️", callback_data="shop_page:1")
    elif page == 1:
        for pack_id, pack in config.TIRE_PACKS.items():
            builder.button(text=f"Купить {pack['tires']} 🛞 (за {pack['stars']} ⭐)", callback_data=f"buy_tires:{pack_id}")
        builder.button(text="⬅️ Назад", callback_data="shop_page:0")
    
    builder.button(text="↩️ В меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

@router.callback_query(F.data == "shop_menu")
async def cq_shop_menu(call: CallbackQuery, bot: Bot, db: Database):
    if call.message.chat.type != 'private':
        return await answer_in_private(call, bot, "Перехожу в магазин...")

    user = db.get_user(call.from_user.id)
    text = (
        f"<b>🛒 Магазин</b>\n\n"
        "Здесь вы можете приобрести доп. попытки или купить покрышки за Telegram Stars.\n\n"
        f"Ваш баланс: <b>{user.get('tires', 0)} 🛞</b>"
    )
    await safe_edit_text(call, text, reply_markup=await shop_menu_kb(db, call.from_user.id))
    await call.answer()

@router.callback_query(F.data.startswith("shop_page:"))
async def cq_shop_page(call: CallbackQuery, db: Database):
    page = int(call.data.split(":")[1])
    user = db.get_user(call.from_user.id)
    text = f"<b>🛒 Магазин</b>\n\nВаш баланс: <b>{user.get('tires', 0)} 🛞</b>"
    await safe_edit_text(call, text, reply_markup=await shop_menu_kb(db, call.from_user.id, page))
    await call.answer()

@router.callback_query(F.data.startswith("buy_attempt:"))
async def cq_buy_attempt(call: CallbackQuery, bot: Bot, db: Database):
    pack_id = call.data.split(":")[1]
    pack = config.ATTEMPT_PACKS.get(pack_id)
    user_id = call.from_user.id
    user = db.get_user(user_id)
    
    has_pass = db.check_and_update_pass_status(user_id)
    cost = round(pack['cost'] * (1 - config.ATTEMPTS_DISCOUNT_PERCENT / 100)) if has_pass else pack['cost']

    if user.get('tires', 0) >= cost:
        db.change_tires(user_id, -cost, f"Покупка {pack['attempts']} попыток")
        db.add_extra_attempts(user_id, pack['attempts'])
        await call.answer(f"✅ Покупка успешна! Начислено {pack['attempts']} доп. попыток.", show_alert=True)
        await cq_shop_menu(call, bot, db)
    else:
        await call.answer(f"Недостаточно покрышек! Нужно: {cost} 🛞", show_alert=True)

@router.callback_query(F.data == "collect_pass_shop_info")
async def cq_collect_pass_shop_info(call: CallbackQuery, db: Database):
    user = db.get_user(call.from_user.id)
    has_pass = db.check_and_update_pass_status(call.from_user.id)
    text = (
        f"<b>⭐ CollectPass</b>\n\n"
        "Это месячная подписка, дающая вам бонусы:\n"
        f"✅ Лимит обмена: <b>{config.COLLECT_PASS_TRADE_LIMIT}</b> машин.\n"
        f"✅ Кулдауны снижены в <b>2 раза</b>.\n"
        f"✅ Скидка на попытки: <b>{config.ATTEMPTS_DISCOUNT_PERCENT}%</b>.\n"
        f"✅ Цена смены ника: <b>{config.COLLECT_PASS_NICK_CHANGE_COST} 🛞</b>.\n\n"
    )
    builder = InlineKeyboardBuilder()
    if has_pass:
        remaining = user.get('collect_pass_expires_at', 0) - int(time.time())
        text += f"<b>Ваша подписка активна!</b> Осталось: <b>{format_time(remaining)}</b>\n\n"
        builder.button(text=f"Продлить за {config.COLLECT_PASS_COST} 🛞", callback_data="buy_collect_pass")
    else:
        text += "Хотите активировать все бонусы?"
        builder.button(text=f"Купить за {config.COLLECT_PASS_COST} 🛞", callback_data="buy_collect_pass")
    
    builder.button(text="↩️ Назад в магазин", callback_data="shop_menu")
    builder.adjust(1)
    await safe_edit_text(call, text, reply_markup=builder.as_markup())
    await call.answer()

@router.callback_query(F.data == "buy_collect_pass")
async def cq_buy_collect_pass(call: CallbackQuery, db: Database):
    user = db.get_user(call.from_user.id)
    if user.get('tires', 0) >= config.COLLECT_PASS_COST:
        db.change_tires(call.from_user.id, -config.COLLECT_PASS_COST, "Покупка CollectPass")
        db.activate_collect_pass(call.from_user.id, config.COLLECT_PASS_DURATION)
        await call.answer("✅ Подписка CollectPass активирована!", show_alert=True)
        await cq_collect_pass_shop_info(call, db)
    else:
        await call.answer(f"❌ Недостаточно покрышек!", show_alert=True)

# === Платежи ===

@router.callback_query(F.data.startswith("buy_tires:"))
async def cq_buy_tires_pack(call: CallbackQuery, bot: Bot):
    pack_id = call.data.split(":")[1]
    pack = config.TIRE_PACKS.get(pack_id)
    if not pack: return await call.answer("Набор не найден.", show_alert=True)
    
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=pack['title'],
        description=f"Покупка {pack['tires']} 🛞.",
        payload=f"buy_tires:{pack_id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{pack['tires']} 🛞", amount=pack['stars'])],
    )
    await call.answer()

@router.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, db: Database):
    payment = message.successful_payment
    payload = payment.invoice_payload
    if payload.startswith("buy_tires:"):
        pack_id = payload.split(":")[1]
        pack = config.TIRE_PACKS.get(pack_id)
        if pack:
            db.log_transaction(
                payment.telegram_payment_charge_id,
                message.from_user.id,
                payment.total_amount,
                payment.currency,
                payload
            )
            db.change_tires(message.from_user.id, pack['tires'], f"Покупка '{pack['title']}'")
            await message.answer(f"✅ Оплата прошла успешно! Начислено <b>{pack['tires']} 🛞</b>.")
        else:
            await message.answer("Ошибка начисления покупки. Обратитесь в поддержку (/paysupporrt)")
