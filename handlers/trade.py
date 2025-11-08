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
from contextlib import suppress
from typing import List, Dict, Any

from aiogram import F, Bot, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardMarkup

import config
from db import Database
from handlers.garage import display_garage
from utils.fsm import Form
from utils.helpers import get_main_menu_content, safe_edit_text

router = Router()


# --- Вспомогательные функции для генерации интерфейса ---

def _format_offer_text(offer_ids: List[int], db: Database) -> str:
    """
    Преобразует список ID машин в форматированную строку для отображения.
    Группирует одинаковые машины, добавляя счетчик (напр., 'x2').
    """
    if not offer_ids:
        return "<i>(пусто)</i>"

    cars = db.get_cars_by_ids(offer_ids)
    if not cars:
        return "<i>(ошибка загрузки)</i>"

    car_counts: Dict[str, int] = {}
    for car in cars:
        name = car['car_name']
        car_counts[name] = car_counts.get(name, 0) + 1

    offer_lines = [
        f"- {name}{f' x{count}' if count > 1 else ''}"
        for name, count in sorted(car_counts.items())
    ]
    return "\n".join(offer_lines)


def _build_trade_keyboard(trade: Dict[str, Any], user_id: int) -> InlineKeyboardMarkup:
    """Собирает клавиатуру управления обменом для указанного пользователя."""
    is_initiator = (user_id == trade['initiator_id'])
    my_offer = trade['initiator_offer'] if is_initiator else trade['partner_offer']
    is_confirmed = trade['initiator_confirm'] if is_initiator else trade['partner_confirm']
    trade_id = trade['trade_id']

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить машину", callback_data=f"trade:add_car:{trade_id}")
    if my_offer:
        builder.button(text="🗑️ Убрать последнюю", callback_data=f"trade:remove_last:{trade_id}")

    confirm_text = "✅ Подтверждено" if is_confirmed else "✅ Подтвердить"
    builder.button(text=confirm_text, callback_data=f"trade:confirm:{trade_id}")
    builder.button(text="❌ Отменить", callback_data=f"trade:cancel:{trade_id}")
    builder.adjust(2)
    return builder.as_markup()


async def update_trade_interface(trade_id: int, bot: Bot, db: Database):
    """
    Ключевая функция, обновляющая сообщения об обмене для обоих участников.
    """
    trade = db.get_trade(trade_id)
    if not trade or trade['status'] != 'active':
        return

    try:
        initiator = await bot.get_chat(trade['initiator_id'])
        partner = await bot.get_chat(trade['partner_id'])
    except TelegramBadRequest:
        db.update_trade_status(trade_id, 'cancelled')
        return

    initiator_offer_text = _format_offer_text(trade['initiator_offer'], db)
    partner_offer_text = _format_offer_text(trade['partner_offer'], db)

    # Обновляем сообщение для инициатора
    with suppress(TelegramBadRequest):
        text = (
            f"<b>Обмен с {partner.full_name}</b>\n\n"
            f"<b>Ваше предложение:</b>\n{initiator_offer_text}\n\n"
            f"<b>Предложение партнера:</b>\n{partner_offer_text}"
        )
        if trade['initiator_confirm']:
            text += "\n\n<i>Вы подтвердили. Ожидаем партнера...</i>"
        elif trade['partner_confirm']:
            text += "\n\n<i>Партнер подтвердил. Подтвердите с вашей стороны для завершения.</i>"

        await bot.edit_message_text(
            text,
            chat_id=trade['initiator_id'],
            message_id=trade['initiator_message_id'],
            reply_markup=_build_trade_keyboard(trade, trade['initiator_id'])
        )

    # Обновляем сообщение для партнера
    with suppress(TelegramBadRequest):
        text = (
            f"<b>Обмен с {initiator.full_name}</b>\n\n"
            f"<b>Ваше предложение:</b>\n{partner_offer_text}\n\n"
            f"<b>Предложение партнера:</b>\n{initiator_offer_text}"
        )
        if trade['partner_confirm']:
            text += "\n\n<i>Вы подтвердили. Ожидаем партнера...</i>"
        elif trade['initiator_confirm']:
            text += "\n\n<i>Партнер подтвердил. Подтвердите с вашей стороны для завершения.</i>"

        await bot.edit_message_text(
            text,
            chat_id=trade['partner_id'],
            message_id=trade['partner_message_id'],
            reply_markup=_build_trade_keyboard(trade, trade['partner_id'])
        )


# --- Этап 1: Инициация обмена ---

@router.callback_query(F.data == "trade:start")
async def start_trade(call: CallbackQuery, state: FSMContext):
    """Запускает процесс обмена, запрашивая никнейм партнера."""
    await state.set_state(Form.trade_enter_nickname)
    await safe_edit_text(
        call,
        "Введите никнейм игрока для обмена:",
        reply_markup=InlineKeyboardBuilder().button(text="Отмена", callback_data="main_menu").as_markup()
    )


# --- Этап 2: Обработка никнейма и отправка приглашения ---

@router.message(Form.trade_enter_nickname)
async def process_partner_nickname(message: Message, state: FSMContext, db: Database, bot: Bot):
    """
    Проверяет никнейм, создает обмен в БД и отправляет приглашение партнеру.
    """
    await state.clear()
    initiator_id = message.from_user.id
    initiator_user = db.get_user(initiator_id)

    if not initiator_user:
        return

    if message.text == initiator_user.get('nickname'):
        await message.answer("Вы не можете начать обмен с самим собой.")
        text, kb = await get_main_menu_content(db, initiator_id)
        return await message.answer(text, reply_markup=kb)

    partner = db.get_user_by_nickname(message.text)
    if not partner:
        await message.answer(f"Игрок с ником «{message.text}» не найден.")
        text, kb = await get_main_menu_content(db, initiator_id)
        return await message.answer(text, reply_markup=kb)

    trade_id = db.create_trade(initiator_id, partner['user_id'])

    invitation_kb = InlineKeyboardBuilder()
    invitation_kb.button(text="✅ Принять", callback_data=f"trade:accept:{trade_id}")
    invitation_kb.button(text="❌ Отклонить", callback_data=f"trade:decline:{trade_id}")

    try:
        await bot.send_message(
            partner['user_id'],
            f"Игрок <b>{initiator_user['nickname']}</b> предлагает вам обмен.",
            reply_markup=invitation_kb.as_markup()
        )
        await message.answer(f"Приглашение отправлено игроку <b>{partner['nickname']}</b>. Ожидаем ответа.")
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.answer("Не удалось отправить приглашение. Возможно, игрок заблокировал бота.")
        db.update_trade_status(trade_id, 'cancelled')


# --- Этап 3: Реакция партнера на приглашение ---

@router.callback_query(F.data.startswith("trade:decline:"))
async def handle_invitation_decline(call: CallbackQuery, db: Database, bot: Bot):
    """Обрабатывает отклонение приглашения."""
    trade_id = int(call.data.split(":")[2])
    trade = db.get_trade(trade_id)
    if not trade:
        return await call.answer("Обмен уже неактуален.", show_alert=True)

    db.update_trade_status(trade_id, 'cancelled')
    with suppress(TelegramForbiddenError):
        await bot.send_message(trade['initiator_id'], f"Игрок {call.from_user.full_name} отклонил обмен.")
    await safe_edit_text(call, "Вы отклонили предложение.")


@router.callback_query(F.data.startswith("trade:accept:"))
async def handle_invitation_accept(call: CallbackQuery, db: Database, bot: Bot):
    """Обрабатывает принятие приглашения и запускает сессию обмена."""
    trade_id = int(call.data.split(":")[2])
    trade = db.get_trade(trade_id)
    if not trade:
        return await call.answer("Обмен уже неактуален.", show_alert=True)

    db.update_trade_status(trade_id, 'active')

    initiator_msg = await bot.send_message(trade['initiator_id'], "<i>Загрузка обмена...</i>")
    partner_msg = await call.message.edit_text("<i>Загрузка обмена...</i>")

    db.update_trade_message_id(trade_id, trade['initiator_id'], initiator_msg.message_id)
    db.update_trade_message_id(trade_id, trade['partner_id'], partner_msg.message_id)

    await update_trade_interface(trade_id, bot, db)


# --- Этап 4: Управление активным обменом ---

@router.callback_query(F.data.startswith("trade:add_car:"))
async def redirect_to_garage_for_selection(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    """Переводит пользователя в гараж для выбора машин."""
    trade_id = int(call.data.split(":")[2])
    trade = db.get_trade(trade_id)
    if not trade:
        return await call.answer("Обмен не найден.", show_alert=True)

    is_initiator = (call.from_user.id == trade['initiator_id'])
    current_offer = trade['initiator_offer'] if is_initiator else trade['partner_offer']

    has_pass = db.check_and_update_pass_status(call.from_user.id)
    limit = config.COLLECT_PASS_TRADE_LIMIT if has_pass else config.DEFAULT_TRADE_LIMIT
    if len(current_offer) >= limit:
        return await call.answer(f"Вы достигли лимита в {limit} машин.", show_alert=True)

    await state.set_state(Form.trade_add_car)
    await state.update_data(
        trade_data={"trade_id": trade_id, "offer": current_offer},
        view_mode='cards', page=0, filters={}
    )
    await display_garage(bot, call.from_user.id, call.message.chat.id, state, db, call.message)


@router.callback_query(F.data.startswith("trade:remove_last:"))
async def remove_last_car_from_offer(call: CallbackQuery, db: Database, bot: Bot):
    """Удаляет последнюю добавленную машину из предложения."""
    trade_id = int(call.data.split(":")[2])
    user_id = call.from_user.id
    trade = db.get_trade(trade_id)
    if not trade:
        return await call.answer("Обмен не найден.", show_alert=True)

    is_initiator = (user_id == trade['initiator_id'])
    current_offer = trade['initiator_offer'] if is_initiator else trade['partner_offer']

    if current_offer:
        current_offer.pop()
        db.update_trade_offer(trade_id, user_id, current_offer)
        await update_trade_interface(trade_id, bot, db)
    await call.answer()


@router.callback_query(F.data.startswith("trade:confirm:"))
async def handle_confirmation(call: CallbackQuery, db: Database, bot: Bot):
    """Обрабатывает подтверждение. Если оба подтвердили — запускает сделку."""
    trade_id = int(call.data.split(":")[2])
    db.confirm_trade(trade_id, call.from_user.id)
    trade = db.get_trade(trade_id)

    if trade['initiator_confirm'] and trade['partner_confirm']:
        if not trade['initiator_offer'] and not trade['partner_offer']:
            db.update_trade_offer(trade_id, trade['initiator_id'], [])
            await call.answer("Нельзя провести пустой обмен!", show_alert=True)
            return await update_trade_interface(trade_id, bot, db)

        success = db.execute_trade(trade_id)

        with suppress(TelegramBadRequest):
            await bot.delete_message(trade['initiator_id'], trade['initiator_message_id'])
            await bot.delete_message(trade['partner_id'], trade['partner_message_id'])

        result_text = "✅ Обмен успешно завершен!" if success else "❌ Ошибка! У одного из игроков нет нужных машин. Обмен отменен."
        kb = InlineKeyboardBuilder().button(text="В меню", callback_data="main_menu").as_markup()
        with suppress(TelegramForbiddenError):
            await bot.send_message(trade['initiator_id'], result_text, reply_markup=kb)
            await bot.send_message(trade['partner_id'], result_text, reply_markup=kb)
    else:
        await update_trade_interface(trade_id, bot, db)
        await call.answer("Вы подтвердили обмен.")


@router.callback_query(F.data.startswith("trade:cancel:"))
async def cancel_trade(call: CallbackQuery, db: Database, bot: Bot):
    """Обрабатывает отмену обмена одним из участников."""
    trade_id = int(call.data.split(":")[2])
    trade = db.get_trade(trade_id)
    if not trade or trade['status'] != 'active':
        return await call.answer("Обмен уже неактуален.", show_alert=True)

    db.update_trade_status(trade_id, 'cancelled')
    kb = InlineKeyboardBuilder().button(text="В меню", callback_data="main_menu").as_markup()

    other_user_id = trade['partner_id'] if call.from_user.id == trade['initiator_id'] else trade['initiator_id']
    with suppress(TelegramForbiddenError):
        await bot.send_message(other_user_id, f"Игрок <b>{call.from_user.full_name}</b> отменил обмен.", reply_markup=kb)

    await safe_edit_text(call, "Вы отменили обмен.", reply_markup=kb)


# --- Этап 5: Интеграция с гаражом ---

@router.callback_query(F.data.startswith("trade:select_car:"), Form.trade_add_car)
async def select_car_in_garage(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    """
    Обрабатывает нажатие кнопок "+"/"-" в гараже в режиме выбора для обмена.
    """
    _, _, action, car_id_str = call.data.split(":")
    data = await state.get_data()
    trade_data = data.get('trade_data', {})
    offer = trade_data.get('offer', [])

    car_name = db.get_car_name_by_id(int(car_id_str))
    if not car_name:
        return await call.answer("Машина не найдена.", show_alert=True)

    user_car_instances = db.get_all_user_cars_by_name(call.from_user.id, car_name)
    instance_ids = [car['car_id'] for car in user_car_instances]

    if action == '+':
        has_pass = db.check_and_update_pass_status(call.from_user.id)
        limit = config.COLLECT_PASS_TRADE_LIMIT if has_pass else config.DEFAULT_TRADE_LIMIT
        if len(offer) >= limit:
            return await call.answer(f"Достигнут лимит в {limit} машин.", show_alert=True)
        for car_id in instance_ids:
            if car_id not in offer:
                offer.append(car_id)
                break
    elif action == '-':
        for car_id in reversed(instance_ids):
            if car_id in offer:
                offer.remove(car_id)
                break

    trade_data['offer'] = offer
    await state.update_data(trade_data=trade_data)
    await display_garage(bot, call.from_user.id, call.message.chat.id, state, db, call.message)


@router.callback_query(F.data.startswith("trade:back_to_session:"), Form.trade_add_car)
async def return_from_garage_to_trade(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    """
    Возвращает пользователя из гаража в интерфейс обмена.
    """
    trade_id = int(call.data.split(":")[2])
    data = await state.get_data()
    final_offer = data.get('trade_data', {}).get('offer', [])

    db.update_trade_offer(trade_id, call.from_user.id, final_offer)
    await state.clear()
    await call.message.delete()

    msg = await bot.send_message(call.from_user.id, "<i>Возвращаемся к обмену...</i>")
    db.update_trade_message_id(trade_id, call.from_user.id, msg.message_id)
    await update_trade_interface(trade_id, bot, db)