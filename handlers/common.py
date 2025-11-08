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

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.enums.chat_member_status import ChatMemberStatus

import config
from db import Database
from utils.helpers import get_main_menu_content

router = Router()


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start_or_menu(message: Message, db: Database, bot: Bot):
    """
    Обработчик команд /start и /menu.
    Регистрирует нового пользователя (если необходимо) и выводит главное меню.
    """
    referrer_id = None
    if message.text and len(message.text.split()) > 1:
        try:
            referrer_id = int(message.text.split()[1])
        except (IndexError, ValueError):
            pass

    is_new_user = db.add_user(message.from_user.id, message.from_user.username, referrer_id)
    if is_new_user and referrer_id:
        try:
            referrer = db.get_user(referrer_id)
            if referrer:
                await bot.send_message(referrer_id, f"🤝 По вашей ссылке присоединился новый игрок!")
        except TelegramBadRequest:
            pass  # Подавляем ошибки, если бот заблокирован реферером

    text, kb = await get_main_menu_content(db, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "main_menu")
async def cq_main_menu(call: CallbackQuery, state: FSMContext, db: Database):
    """
    Обработчик кнопки "В меню".
    Сбрасывает состояние FSM и возвращает пользователя в главное меню.
    """
    await state.clear()
    text, kb = await get_main_menu_content(db, call.from_user.id)
    
    # Пытаемся отредактировать, если не получается (например, это было фото) - удаляем и отправляем новое
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        with suppress(TelegramBadRequest):
            await call.message.delete()
        await call.message.answer(text, reply_markup=kb)
        
    await call.answer()


@router.callback_query(F.data == "check_subscription")
async def cq_check_subscription(call: CallbackQuery, bot: Bot, db: Database):
    """
    Обработчик кнопки для повторной проверки подписки на канал.
    """
    user_id = call.from_user.id

    if user_id in config.ADMIN_IDS:
        with suppress(TelegramBadRequest):
            await call.message.delete()
        text, kb = await get_main_menu_content(db, user_id)
        await call.message.answer(text, reply_markup=kb)
        return

    try:
        member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
        if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            await call.answer("✅ Спасибо за подписку!", show_alert=True)
            with suppress(TelegramBadRequest):
                await call.message.delete()
            text, kb = await get_main_menu_content(db, user_id)
            await call.message.answer(text, reply_markup=kb)
        else:
            await call.answer("❌ Вы все еще не подписаны на канал.", show_alert=True)
    except Exception as e:
        await call.answer("Произошла ошибка при проверке. Попробуйте позже.", show_alert=True)
        print(f"Ошибка повторной проверки подписки для {user_id}: {e}")

