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
from contextlib import suppress
from typing import Tuple, Union

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import (InlineKeyboardMarkup, CallbackQuery,
                           InlineKeyboardButton)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database


# === Форматирование данных ===

def format_value(value: int) -> str:
    """Форматирует число, добавляя точки как разделители тысяч и 'CR' в конце."""
    if value is None:
        value = 0
    return f"{value:,}".replace(",", ".") + " CR"


def format_time(seconds: int) -> str:
    """Форматирует секунды в читаемый формат (дни, часы, минуты, секунды)."""
    if seconds <= 0:
        return "Готово!"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds_rem = divmod(remainder, 60)
    if days > 0:
        return f"{int(days)}д {int(hours)}ч"
    elif hours > 0:
        return f"{int(hours)}ч {int(minutes)}м"
    else:
        return f"{int(minutes)}м {int(seconds_rem)}с"


# === Безопасные операции с сообщениями ===

async def safe_edit_text(call: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup = None, **kwargs):
    """
    Безопасно редактирует сообщение. Если это было фото - удаляет и отправляет новое.
    """
    try:
        await call.message.edit_text(text, reply_markup=reply_markup, **kwargs)
    except TelegramBadRequest as e:
        if "message to edit not found" in e.message:
            # Если сообщение не найдено (уже удалено), отправляем новое
            await call.message.answer(text, reply_markup=reply_markup, **kwargs)
        elif "there is no text in the message to edit" in e.message:
            # Если это было фото, удаляем его и отправляем текстовое сообщение
            with suppress(TelegramBadRequest):
                await call.message.delete()
            await call.message.answer(text, reply_markup=reply_markup, **kwargs)
        else:
            print(f"Unhandled TelegramBadRequest in safe_edit_text: {e}")


async def answer_in_private(call: CallbackQuery, bot: Bot, text: str, reply_markup: InlineKeyboardMarkup = None, **kwargs):
    """Отправляет ответ пользователю в личные сообщения из группового чата."""
    try:
        await bot.send_message(call.from_user.id, text, reply_markup=reply_markup, **kwargs)
        await call.answer("Ответ отправлен вам в личные сообщения.", show_alert=False)
    except (TelegramBadRequest, TelegramForbiddenError):
        bot_info = await bot.get_me()
        await call.answer(
            f"Не могу отправить вам сообщение. Пожалуйста, начните диалог с ботом: @{bot_info.username}",
            show_alert=True
        )


# === Генераторы клавиатур ===

async def get_main_menu_content(db: Database, user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Генерирует текст и клавиатуру для главного меню."""
    user = db.get_user(user_id)
    collection_value = db.get_collection_value(user_id)
    car_count = db.get_garage_count(user_id)
    tires = user.get('tires', 0) if user else 0
    nickname = user.get('nickname', user_id) if user else user_id

    collection_value_formatted = format_value(collection_value)
    text = (
        f"<b>{nickname}</b>\n\n"
        f"🏎️ Машин в гараже: <b>{car_count}</b>\n"
        f"💰 Стоимость коллекции: <b>{collection_value_formatted}</b>\n"
        f"🛞 Покрышек: <b>{tires}</b>\n\n"
        "Используй кнопки ниже для навигации."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Открыть кейс", callback_data="open_case_menu")
    builder.button(text="🛒 Магазин", callback_data="shop_menu")
    builder.button(text="🏎️ Мой гараж", callback_data="garage_menu")
    builder.button(text="🛠️ Крафт", callback_data="craft_menu")
    
    is_tester_or_admin = user_id in config.ADMIN_IDS or user_id in config.TESTER_IDS
    if is_tester_or_admin:
        builder.button(text="🤝 Обмен", callback_data="trade:start")
        
    builder.button(text="🎲 Мини игры", callback_data="minigames_menu")
    builder.button(text="👤 Профиль", callback_data="profile_menu")
    builder.button(text="📞 Поддержка", callback_data="support_menu")

    if is_tester_or_admin:
        builder.adjust(2, 2, 2, 2)
    else:
        # Корректная раскладка для 7 кнопок
        builder.adjust(2, 2, 2, 1)
        
    return text, builder.as_markup()


def back_to_menu_kb(minigame=False) -> InlineKeyboardMarkup:
    """Клавиатура для возврата в меню или в раздел мини-игр."""
    builder = InlineKeyboardBuilder()
    callback_data = "minigames_menu" if minigame else "main_menu"
    text = "↩️ В мини-игры" if minigame else "↩️ В меню"
    builder.button(text=text, callback_data=callback_data)
    return builder.as_markup()

