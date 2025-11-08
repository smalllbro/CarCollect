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

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database
from utils.fsm import Form
from utils.helpers import safe_edit_text, get_main_menu_content, answer_in_private

router = Router()


# === Клавиатуры ===

def support_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Написать в поддержку", callback_data="create_ticket")
    builder.button(text="↩️ В меню", callback_data="main_menu")
    return builder.as_markup()


# === Обработчики ===

@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, state: FSMContext):
    await state.set_state(Form.writing_ticket)
    await state.update_data(source='pay')
    builder = InlineKeyboardBuilder().button(text="Отменить", callback_data="cancel_ticket")
    await message.answer("Опишите вашу проблему с платежом.", reply_markup=builder.as_markup())


@router.callback_query(F.data == "support_menu")
async def cq_support_menu(call: CallbackQuery, bot: Bot):
    if call.message.chat.type != 'private':
        return await answer_in_private(call, bot, "Перехожу в раздел поддержки...")

    text = (
        "<b>📞 Поддержка</b>\n\n"
        "Если у вас возник вопрос или проблема, вы можете создать заявку.\n\n"
        f"Разработчик: @{config.DEVELOPER_USERNAME}"
    )
    await safe_edit_text(call, text, reply_markup=support_menu_kb())


@router.callback_query(F.data == "create_ticket")
async def cq_create_ticket(call: CallbackQuery, state: FSMContext):
    await state.set_state(Form.writing_ticket)
    await state.update_data(source='general')
    builder = InlineKeyboardBuilder().button(text="Отменить", callback_data="cancel_ticket")
    await safe_edit_text(call, "Напишите свое обращение прямо в чат.", reply_markup=builder.as_markup())


@router.callback_query(F.data == "cancel_ticket")
async def cq_cancel_ticket(call: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    text, kb = await get_main_menu_content(db, call.from_user.id)
    await safe_edit_text(call, text, reply_markup=kb)


@router.message(Form.writing_ticket)
async def process_ticket_message(message: Message, state: FSMContext, db: Database):
    data = await state.get_data()
    ticket_id = db.create_ticket(message.from_user.id, message.text, source=data.get('source', 'general'))
    await state.clear()

    await message.answer(f"✅ Ваша заявка #{ticket_id} принята! Мы рассмотрим ее в ближайшее время.")
    await asyncio.sleep(1)
    text, kb = await get_main_menu_content(db, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("user_close_ticket:"))
async def cq_user_close_ticket(call: CallbackQuery, db: Database, bot: Bot):
    ticket_id = int(call.data.split(":")[1])
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return await call.answer("Тикет не найден.", show_alert=True)

    db.update_ticket_status(ticket_id, 'closed')
    await safe_edit_text(call, "Спасибо за ваш отзыв! Заявка закрыта.")

    if ticket.get('admin_id'):
        try:
            await bot.send_message(ticket['admin_id'], f"Пользователь <code>{ticket['user_id']}</code> закрыл тикет #{ticket_id}.")
        except Exception:
            pass # Ignore if admin blocked bot

# === Админские обработчики тикетов ===

@router.callback_query(F.data.startswith("close_ticket_prompt:"))
async def cq_close_ticket_prompt(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    action, ticket_id_str = call.data.split(":")[1:]
    ticket_id = int(ticket_id_str)
    
    ticket = db.get_ticket(ticket_id)
    if not ticket or ticket['status'] != 'open':
        return await safe_edit_text(call, "Тикет не найден или уже неактуален.")

    if action == "with_message":
        await state.set_state(Form.admin_reply_to_ticket)
        await state.update_data(ticket_id_to_reply=ticket_id)
        await safe_edit_text(call, f"Введите ваше сообщение для ответа на тикет #{ticket_id}:")
    elif action == "without_message":
        db.request_ticket_close(ticket_id, call.from_user.id)
        kb = InlineKeyboardBuilder().button(text="Да, закрыть заявку", callback_data=f"user_close_ticket:{ticket_id}").as_markup()
        try:
            await bot.send_message(ticket['user_id'], f"<b>Ответ по вашей заявке #{ticket_id}</b>\n\nПомогла ли вам поддержка?", reply_markup=kb)
            await safe_edit_text(call, f"Запрос на закрытие тикета #{ticket_id} отправлен.")
        except Exception:
            await safe_edit_text(call, "Не удалось отправить сообщение пользователю.")
    elif action == "force_close":
        db.update_ticket_status(ticket_id, 'closed')
        await safe_edit_text(call, f"Тикет #{ticket_id} принудительно закрыт.")
    elif action == "cancel":
        await call.message.delete()
    await call.answer()

@router.message(Form.admin_reply_to_ticket)
async def process_admin_ticket_reply(message: Message, state: FSMContext, db: Database, bot: Bot):
    data = await state.get_data()
    ticket_id = data.get('ticket_id_to_reply')
    await state.clear()

    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return await message.answer("Тикет не найден.")

    db.request_ticket_close(ticket_id, message.from_user.id)
    kb = InlineKeyboardBuilder().button(text="Да, закрыть заявку", callback_data=f"user_close_ticket:{ticket_id}").as_markup()
    try:
        text = f"<b>Ответ по вашей заявке #{ticket_id}</b>\n\n{message.text}\n\nПомогла ли вам поддержка?"
        await bot.send_message(ticket['user_id'], text, reply_markup=kb)
        await message.answer(f"Ваш ответ на тикет #{ticket_id} отправлен.")
    except Exception:
        await message.answer("Не удалось отправить сообщение пользователю.")
