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
from contextlib import suppress

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, InputMediaPhoto, FSInputFile)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database
from utils.fsm import Form
from utils.helpers import format_value, safe_edit_text, answer_in_private

router = Router()

# === Вспомогательные функции для генерации контента ===

def _format_car_card_caption(car: dict) -> str:
    """Формирует текст для карточки машины."""
    style = config.RARITY_STYLES.get(car['rarity'], {})
    count_str = f"<b>Количество:</b> {car['count']}\n" if car['count'] > 1 else ""
    return (
        f"{style.get('color', '')} <b>{car['car_name']}</b>\n\n"
        f"<b>Редкость:</b> {style.get('name', car['rarity'])}\n"
        f"<b>Цена:</b> 💵 {format_value(car['value'])}\n"
        f"{count_str}"
    )

def _format_car_list_text(cars_on_page: list) -> str:
    """Формирует текст для гаража в режиме списка."""
    car_lines = [
        f"{config.RARITY_STYLES.get(c['rarity'], {}).get('color', '')} {c['car_name']}"
        f"{f' x{c['count']}' if c['count'] > 1 else ''} ({format_value(c['value'])})"
        for c in cars_on_page
    ]
    return "<b>🏎️ Ваш гараж (список):</b>\n\n" + "\n".join(car_lines)

# === Вспомогательные функции для построения клавиатуры ===

def _build_navigation_row(page: int, total_pages: int) -> list[InlineKeyboardButton]:
    """Строит ряд кнопок для пагинации."""
    return [
        InlineKeyboardButton(text="⏮️", callback_data=f"garage:page:0"),
        InlineKeyboardButton(text="◀️", callback_data=f"garage:page:{max(0, page - 1)}"),
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="garage:noop"),
        InlineKeyboardButton(text="▶️", callback_data=f"garage:page:{min(total_pages - 1, page + 1)}"),
        InlineKeyboardButton(text="⏭️", callback_data=f"garage:page:{total_pages - 1}")
    ]

def _build_trade_selection_row(current_car: dict, offer: list, db: Database, user_id: int) -> list[InlineKeyboardButton]:
    """Строит ряд кнопок для добавления/удаления машин в обмене."""
    # Получаем все уникальные ID для данной модели машины у пользователя
    all_instances = db.get_all_user_cars_by_name(user_id, current_car['car_name'])
    all_instance_ids = {car['car_id'] for car in all_instances}
    
    # Считаем, сколько экземпляров этой модели уже в предложении
    count_in_offer = len([car_id for car_id in offer if car_id in all_instance_ids])
    total_owned = len(all_instance_ids)
    
    # ID, который будет в callback, не важен для логики, но нужен для идентификации машины
    representative_car_id = current_car['car_id'] 

    return [
        InlineKeyboardButton(text="➖", callback_data=f"trade:select_car:-:{representative_car_id}"),
        InlineKeyboardButton(text=f"{count_in_offer}/{total_owned}", callback_data="garage:noop"),
        InlineKeyboardButton(text="➕", callback_data=f"trade:select_car:+:{representative_car_id}")
    ]

async def build_garage_keyboard(state: FSMContext, all_cars: list, db: Database, user_id: int) -> InlineKeyboardMarkup:
    """Собирает и возвращает полную клавиатуру для интерфейса гаража."""
    data = await state.get_data()
    filters = data.get('filters', {})
    view_mode = data.get('view_mode', 'cards')
    page = data.get('page', 0)
    total_cars_in_view = len(all_cars)
    
    in_trade_mode = await state.get_state() == Form.trade_add_car
    trade_offer = data.get('trade_data', {}).get('offer', [])

    builder = InlineKeyboardBuilder()

    # Ряд навигации
    items_per_page = 1 if view_mode == 'cards' else 15
    if total_cars_in_view > items_per_page:
        total_pages = (total_cars_in_view + items_per_page - 1) // items_per_page
        if page >= total_pages: page = max(0, total_pages - 1)
        builder.row(*_build_navigation_row(page, total_pages))

    # Ряд для ВЫБОРА МАШИН В ОБМЕНЕ (только в режиме карточек)
    if in_trade_mode and view_mode == 'cards' and page < total_cars_in_view:
        builder.row(*_build_trade_selection_row(all_cars[page], trade_offer, db, user_id))

    # Ряды сортировки и фильтров
    sort_by = filters.get('sort_by')
    sort_symbols = {"_asc": "🔼", "_desc": "🔽"}
    def get_sort_text(key, text):
        if sort_by == f"{key}_asc": return f"{text} {sort_symbols['_asc']}"
        if sort_by == f"{key}_desc": return f"{text} {sort_symbols['_desc']}"
        return text

    builder.row(
        InlineKeyboardButton(text=get_sort_text("name", "A-Z"), callback_data="garage:sort:name"),
        InlineKeyboardButton(text=get_sort_text("value", "Цена"), callback_data="garage:sort:value"),
        InlineKeyboardButton(text=get_sort_text("rarity", "Редкость"), callback_data="garage:sort:rarity")
    )

    def get_filter_text(key, text):
        return f"{text} ✅" if filters.get(key) else text

    builder.row(
        InlineKeyboardButton(text=get_filter_text("brand", "Бренд"), callback_data="garage:filter:brand"),
        InlineKeyboardButton(text=get_filter_text("rarity", "Редкость"), callback_data="garage:filter:rarity"),
        InlineKeyboardButton(text=get_filter_text("season", "Сезон"), callback_data="garage:filter:season")
    )
    builder.row(
        InlineKeyboardButton(text="🔍 Поиск", callback_data="garage:search_start"),
        InlineKeyboardButton(text="Дубли ✅" if filters.get('duplicates') else "Дубли", callback_data="garage:toggle_duplicates"),
        InlineKeyboardButton(text="🗑️ Сброс", callback_data="garage:reset_filters")
    )

    # Завершающие кнопки
    if in_trade_mode:
        trade_id = data.get('trade_data', {}).get('trade_id')
        builder.row(InlineKeyboardButton(text=f"✅ Готово ({len(trade_offer)} машин)", callback_data=f"trade:back_to_session:{trade_id}"))
    else:
        builder.row(InlineKeyboardButton(text="↩️ В меню", callback_data="main_menu"))
    
    return builder.as_markup()


# === Основной обработчик отображения ===

async def display_garage(bot: Bot, user_id: int, chat_id: int, state: FSMContext, db: Database, message: Message = None):
    """
    Основная функция для отображения интерфейса гаража.
    Принимает объект Message для редактирования или удаления.
    """
    data = await state.get_data()
    filters = data.get('filters', {})
    view_mode = data.get('view_mode', 'cards')
    page = data.get('page', 0)

    all_cars_grouped = db.get_filtered_garage(user_id, filters)
    kb = await build_garage_keyboard(state, all_cars_grouped, db, user_id)
    
    if not all_cars_grouped:
        text = "Гараж пуст. Возможно, стоит сбросить фильтры?"
        # Унифицируем обработку пустого гаража
        if message and message.photo: await message.delete()
        await bot.send_message(chat_id, text, reply_markup=kb)
        return

    # Отображение в режиме карточек
    if view_mode == 'cards':
        total_pages = len(all_cars_grouped)
        page = min(page, total_pages - 1) if total_pages > 0 else 0

        current_car = all_cars_grouped[page]
        caption = _format_car_card_caption(current_car)
        photo_to_send = current_car.get("image_file_id") or FSInputFile("images/default_car.png")
        
        try:
            if message and message.photo:
                media = InputMediaPhoto(media=photo_to_send, caption=caption)
                await message.edit_media(media=media, reply_markup=kb)
            else:
                if message: await message.delete()
                await bot.send_photo(chat_id, photo=photo_to_send, caption=caption, reply_markup=kb)
        except TelegramBadRequest as e:
            if "media is identical" in str(e).lower() and message:
                await message.edit_caption(caption=caption, reply_markup=kb)
            elif "wrong file identifier" in str(e).lower() or "file_id_invalid" in str(e).lower():
                logging.warning(f"Invalid file_id in garage. Falling back.")
                if message: await message.delete()
                await bot.send_photo(chat_id, photo=FSInputFile("images/default_car.png"), caption=caption, reply_markup=kb)
            else:
                if message: await message.delete() # Удаляем старое сообщение при других ошибках
                await bot.send_message(chat_id, caption, reply_markup=kb)

    # Отображение в режиме списка
    else:
        items_per_page = 15
        total_pages = (len(all_cars_grouped) + items_per_page - 1) // items_per_page
        page = min(page, total_pages - 1) if total_pages > 0 else 0
        cars_on_page = all_cars_grouped[page * items_per_page : (page + 1) * items_per_page]
        text = _format_car_list_text(cars_on_page)
        
        if message and not message.photo:
            await safe_edit_text(call=CallbackQuery(id="dummy", from_user=message.from_user, chat_instance="dummy", message=message), text=text, reply_markup=kb)
        else:
            if message: await message.delete()
            await bot.send_message(chat_id, text, reply_markup=kb)


# === Обработчики CallbackQuery и Message ===

def initial_garage_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Показать списком", callback_data="garage:view:list")
    builder.button(text="🖼️ Показать страницами", callback_data="garage:view:cards")
    builder.row(InlineKeyboardButton(text="↩️ В меню", callback_data="main_menu"))
    builder.adjust(2, 1)
    return builder.as_markup()

@router.callback_query(F.data == "garage_menu")
async def cq_garage_initial_menu(call: CallbackQuery, bot: Bot):
    text = "Выберите режим просмотра гаража:"
    if call.message.chat.type != 'private':
        return await answer_in_private(call, bot, text, initial_garage_menu_kb())

    with suppress(TelegramBadRequest):
        if call.message.photo: await call.message.delete()
    await safe_edit_text(call, text, reply_markup=initial_garage_menu_kb())


@router.callback_query(F.data.startswith("garage:view:"))
async def cq_garage_start_view(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    view_mode = call.data.split(":")[2]
    await state.set_state(Form.garage_view)
    await state.update_data(view_mode=view_mode, page=0, filters={})
    await display_garage(bot, call.from_user.id, call.message.chat.id, state, db, call.message)


@router.callback_query(F.data.startswith("garage:"), Form.garage_view)
@router.callback_query(F.data.startswith("garage:"), Form.trade_add_car)
async def cq_garage_action_handler(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    await call.answer()
    action, *params = call.data.split(":")[1:]
    data = await state.get_data()
    filters = data.get('filters', {})

    if action == 'page':
        await state.update_data(page=int(params[0]))
    elif action == 'sort':
        sort_key = params[0]
        current_sort = filters.get('sort_by')
        if current_sort == f"{sort_key}_asc": filters['sort_by'] = f"{sort_key}_desc"
        elif current_sort == f"{sort_key}_desc": filters.pop('sort_by', None)
        else: filters['sort_by'] = f"{sort_key}_asc"
        await state.update_data(filters=filters, page=0)
    elif action == 'toggle_duplicates':
        filters['duplicates'] = not filters.get('duplicates', False)
        await state.update_data(filters=filters, page=0)
    elif action == 'reset_filters':
        await state.update_data(filters={}, page=0)
    elif action == 'filter':
        filter_type = params[0]
        options = db.get_user_distinct_values(call.from_user.id, filter_type)
        if not options: return await call.answer("Нет значений для этого фильтра.", show_alert=True)
        
        builder = InlineKeyboardBuilder()
        for opt in options:
            is_active = filters.get(filter_type) == opt
            builder.button(text=f"{opt} {'✅' if is_active else ''}", callback_data=f"garage:apply_filter:{filter_type}:{opt}")
        builder.adjust(2)
        builder.row(InlineKeyboardButton(text="↩️ Назад в гараж", callback_data="garage:back"))
        
        await call.message.delete()
        await call.message.answer(f"Выберите {filter_type}:", reply_markup=builder.as_markup())
        return
    elif action == 'apply_filter':
        f_type, f_value = params
        if filters.get(f_type) == f_value: filters.pop(f_type, None)
        else: filters[f_type] = f_value
        await state.update_data(filters=filters, page=0)
        await call.message.delete()
    elif action == 'search_start':
        await state.update_data(previous_state=await state.get_state())
        await state.set_state(Form.garage_search)
        await call.message.delete()
        await call.message.answer("Введите название машины для поиска:", reply_markup=InlineKeyboardBuilder().button(text="Отмена", callback_data="garage:back").as_markup())
        return
    elif action == 'noop':
        return

    await display_garage(bot, call.from_user.id, call.message.chat.id, state, db, call.message)


@router.callback_query(F.data == "garage:back", Form.garage_search)
@router.callback_query(F.data == "garage:back")
async def cq_garage_back(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    data = await state.get_data()
    previous_state = data.get('previous_state', Form.garage_view)
    await state.set_state(previous_state)
    await call.message.delete()
    await display_garage(bot, call.from_user.id, call.message.chat.id, state, db)


@router.message(Form.garage_search)
async def process_garage_search(message: Message, state: FSMContext, db: Database, bot: Bot):
    data = await state.get_data()
    filters = data.get('filters', {})
    previous_state = data.get('previous_state', Form.garage_view)
    filters['search_query'] = message.text
    
    await state.set_state(previous_state)
    await state.update_data(filters=filters, page=0)
    await message.delete()
    await display_garage(bot, message.from_user.id, message.chat.id, state, db)
