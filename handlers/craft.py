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
import random
import logging
from collections import Counter
from typing import Dict, List, Any
from contextlib import suppress
import time

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message, InputMediaPhoto, FSInputFile)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database
from logic import GameLogic
from utils.fsm import Form
from utils.helpers import format_value, answer_in_private, safe_edit_text

router = Router()

RARITY_ORDER = ["Common", "Rare", "Epic", "Mythic", "Legendary"]

# === Вспомогательные функции для клавиатур ===

def _build_navigation_row(page: int, total_pages: int, rarity: str) -> list[InlineKeyboardButton]:
    """Строит ряд кнопок для пагинации в крафте."""
    return [
        InlineKeyboardButton(text="⏮️", callback_data=f"craft:page:{rarity}:0"),
        InlineKeyboardButton(text="◀️", callback_data=f"craft:page:{rarity}:{max(0, page - 1)}"),
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="craft:noop"),
        InlineKeyboardButton(text="▶️", callback_data=f"craft:page:{rarity}:{min(total_pages - 1, page + 1)}"),
        InlineKeyboardButton(text="⏭️", callback_data=f"craft:page:{rarity}:{total_pages - 1}")
    ]

def _build_selection_row(current_car: dict, selection: dict, rarity: str) -> list[InlineKeyboardButton]:
    """Строит ряд кнопок для выбора количества машин."""
    car_name = current_car['car_name']
    selected_count = selection.get(car_name, 0)
    # Доступно для крафта = всего дублей (т.е. общее кол-во - 1)
    available_for_craft = current_car['count'] - 1
    return [
        InlineKeyboardButton(text="➖", callback_data=f"craft:select:{rarity}:{car_name}:-"),
        InlineKeyboardButton(text=f"{selected_count}/{available_for_craft}", callback_data="craft:noop"),
        InlineKeyboardButton(text="➕", callback_data=f"craft:select:{rarity}:{car_name}:+")
    ]

async def build_craft_keyboard(state: FSMContext, all_cars: list, rarity: str) -> InlineKeyboardMarkup:
    """Собирает и возвращает полную клавиатуру для интерфейса выбора машин для крафта."""
    data = await state.get_data()
    filters = data.get('filters', {})
    page = data.get('page', 0)
    selection = data.get('selection', {})
    total_cars = len(all_cars)
    
    builder = InlineKeyboardBuilder()

    # Ряд 1: Пагинация
    if total_cars > 0:
        total_pages = (total_cars + 1 - 1) // 1 # 1 car per page
        if page >= total_pages: page = max(0, total_pages - 1)
        builder.row(*_build_navigation_row(page, total_pages, rarity))

    # Ряд 2: Выбор количества
    if page < total_cars:
        builder.row(*_build_selection_row(all_cars[page], selection, rarity))

    # Ряд 3: Сортировка
    sort_by = filters.get('sort_by')
    sort_symbols = {"_asc": "🔼", "_desc": "🔽"}
    def get_sort_text(key, text):
        if sort_by == f"{key}_asc": return f"{text} {sort_symbols['_asc']}"
        if sort_by == f"{key}_desc": return f"{text} {sort_symbols['_desc']}"
        return text

    builder.row(
        InlineKeyboardButton(text=get_sort_text("name", "A-Z"), callback_data=f"craft:sort:{rarity}:name"),
        InlineKeyboardButton(text=get_sort_text("value", "Цена"), callback_data=f"craft:sort:{rarity}:value"),
        InlineKeyboardButton(text=get_sort_text("duplicates", "Дубли"), callback_data=f"craft:sort:{rarity}:duplicates")
    )

    # Ряд 4: Фильтры
    def get_filter_text(key, text):
        return f"{text} ✅" if filters.get(key) else text

    builder.row(
        InlineKeyboardButton(text=get_filter_text("brand", "Бренд"), callback_data=f"craft:filter:{rarity}:brand"),
        InlineKeyboardButton(text=get_filter_text("season", "Сезон"), callback_data=f"craft:filter:{rarity}:season"),
        InlineKeyboardButton(text="🔍 Поиск", callback_data=f"craft:search_start:{rarity}")
    )
    builder.row(InlineKeyboardButton(text="🗑️ Сброс фильтров", callback_data=f"craft:reset_filters:{rarity}"))

    # Ряд 5: Действия
    recipe = config.CRAFT_RECIPES.get(rarity)
    total_selected_count = sum(selection.values())
    action_buttons = []
    if recipe and total_selected_count == recipe['cost']:
        action_buttons.append(InlineKeyboardButton(text="✅ Скрафтить", callback_data=f"craft:do:{rarity}"))
    
    # Добавляем кнопку "Случайный крафт", если общее кол-во дублей достаточно
    total_duplicates_of_rarity = sum(c['count'] - 1 for c in all_cars)
    if recipe and total_duplicates_of_rarity >= recipe['cost']:
        action_buttons.append(InlineKeyboardButton(text="🎲 Случайный крафт", callback_data=f"craft:random:{rarity}"))
    
    if action_buttons:
        builder.row(*action_buttons)

    # Ряд 6: Управление
    builder.row(
        InlineKeyboardButton(text="🗑️ Сбросить выбор", callback_data=f"craft:reset_selection:{rarity}"),
        InlineKeyboardButton(text="↩️ К рецептам", callback_data="craft_menu")
    )
    
    return builder.as_markup()

# === Основные обработчики ===

@router.callback_query(F.data == "craft_menu")
async def cq_craft_menu(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    """Входная точка - показывает меню с рецептами крафта."""
    await state.clear()
    if call.message.chat.type != 'private':
        return await answer_in_private(call, bot, "Перехожу в раздел крафта...")

    all_duplicates = db.get_all_user_duplicates(call.from_user.id)
    if not all_duplicates:
        kb = InlineKeyboardBuilder().button(text="↩️ В меню", callback_data="main_menu").as_markup()
        await safe_edit_text(call, "У вас нет дубликатов для крафта.", reply_markup=kb)
        return

    # Подсчет дубликатов по каждой редкости
    car_name_counts = Counter(d['car_name'] for d in all_duplicates)
    duplicate_counts = {rarity: 0 for rarity in RARITY_ORDER}
    for car_name, count in car_name_counts.items():
        if count > 1:
            car_rarity = next((c['rarity'] for c in all_duplicates if c['car_name'] == car_name), None)
            if car_rarity:
                duplicate_counts[car_rarity] += count - 1

    text = "<b>🛠️ Меню крафта</b>\n\nВыберите доступный рецепт для обмена дубликатов на новую машину:\n\n"
    builder = InlineKeyboardBuilder()
    
    for rarity, recipe in config.CRAFT_RECIPES.items():
        style = config.RARITY_STYLES.get(rarity, {})
        result_style = config.RARITY_STYLES.get(recipe['result'], {})
        duplicates_available = duplicate_counts.get(rarity, 0)
        
        text += (f"{recipe['cost']}x {style.get('color', '')} {rarity} ({duplicates_available}) "
                 f"➡️ 1x {result_style.get('color', '')} {recipe['result']}\n")
        
        if duplicates_available >= recipe['cost']:
            builder.button(text=f"Выбрать {rarity}", callback_data=f"craft:start:{rarity}")

    builder.row(InlineKeyboardButton(text="↩️ В меню", callback_data="main_menu"))
    builder.adjust(1)
    
    await safe_edit_text(call, text, reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("craft:start:"))
async def cq_start_rarity_craft(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    """Запускает интерфейс выбора машин для конкретной редкости."""
    rarity = call.data.split(":")[2]
    await state.set_state(Form.crafting)
    await state.update_data(
        filters={'rarity': rarity, 'duplicates': True},
        page=0,
        selection={},
        view_mode='cards' # для совместимости с кодом гаража
    )
    await call.answer()
    await display_craft_view(bot, call.from_user.id, call.message.chat.id, state, db, call.message)


async def display_craft_view(bot: Bot, user_id: int, chat_id: int, state: FSMContext, db: Database, message: Message):
    """Основная функция для отображения интерфейса выбора машин для крафта."""
    data = await state.get_data()
    filters = data.get('filters', {})
    page = data.get('page', 0)
    selection = data.get('selection', {})
    rarity = filters.get('rarity')

    if not rarity: return # Should not happen

    all_cars_for_craft = db.get_filtered_garage(user_id, filters)
    kb = await build_craft_keyboard(state, all_cars_for_craft, rarity)

    if not all_cars_for_craft:
        # Возвращаемся в меню рецептов, если после фильтрации не осталось машин
        await cq_craft_menu(CallbackQuery(id="dummy", from_user=message.from_user, chat_instance="dummy", message=message, data="craft_menu"), state, db, bot)
        await bot.send_message(user_id, "Нет машин, соответствующих вашим фильтрам.")
        if message and message.photo: await message.delete()
        return

    page = min(page, len(all_cars_for_craft) - 1)
    current_car = all_cars_for_craft[page]
    
    recipe = config.CRAFT_RECIPES.get(rarity)
    total_selected_count = sum(selection.values())

    caption = "Выберите дубликаты для обмена.\n\n"
    if recipe:
        result_style = config.RARITY_STYLES.get(recipe['result'], {})
        caption += f"<b>Рецепт:</b> {recipe['cost']}x {rarity} ➡️ 1x {result_style.get('name', recipe['result'])}\n"
        caption += f"<b>Выбрано всего: {total_selected_count}/{recipe['cost']}</b>\n\n"

    style = config.RARITY_STYLES.get(current_car['rarity'], {})
    caption += (
        f"{style.get('color', '')} <b>{current_car['car_name']}</b>\n\n"
        f"<b>Дубликатов:</b> {current_car['count'] - 1}\n"
        f"<b>Цена:</b> 💵 {format_value(current_car['value'])}"
    )

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
        else:
            logging.error(f"Error in display_craft_view: {e}")
            if message: await message.delete()
            await bot.send_message(chat_id, caption, reply_markup=kb)


@router.callback_query(F.data.startswith("craft:"), Form.crafting)
async def cq_craft_actions(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot, logic: GameLogic):
    """Обрабатывает все действия в интерфейсе выбора машин для крафта."""
    action, *params = call.data.split(":")[1:]
    rarity = params[0]

    data = await state.get_data()
    filters = data.get('filters', {})
    selection = data.get('selection', {})

    if action == "page":
        await state.update_data(page=int(params[1]))
    elif action == "reset_selection":
        await state.update_data(selection={}, page=0)
    elif action == "reset_filters":
        # Сбрасываем все, кроме обязательных фильтров редкости и дублей
        await state.update_data(
            filters={'rarity': rarity, 'duplicates': True},
            page=0
        )
    elif action == 'sort':
        sort_key = params[1]
        current_sort = filters.get('sort_by')
        if current_sort == f"{sort_key}_asc": filters['sort_by'] = f"{sort_key}_desc"
        elif current_sort == f"{sort_key}_desc": filters.pop('sort_by', None)
        else: filters['sort_by'] = f"{sort_key}_asc"
        await state.update_data(filters=filters, page=0)
    elif action == 'filter':
        filter_type = params[1]
        options = db.get_user_distinct_values(call.from_user.id, filter_type, rarity=rarity)
        if not options:
            return await call.answer("Нет значений для этого фильтра.", show_alert=True)
        
        builder = InlineKeyboardBuilder()
        for opt in options:
            is_active = filters.get(filter_type) == opt
            builder.button(text=f"{opt} {'✅' if is_active else ''}", callback_data=f"craft:apply_filter:{rarity}:{filter_type}:{opt}")
        builder.adjust(2)
        builder.row(InlineKeyboardButton(text="↩️ Назад", callback_data=f"craft:back:{rarity}"))
        
        text = f"Выберите {filter_type}:"
        if call.message.photo: await call.message.delete()
        await call.message.answer(text, reply_markup=builder.as_markup())
        return
    elif action == 'apply_filter':
        _, f_type, f_value = params
        if filters.get(f_type) == f_value: filters.pop(f_type, None)
        else: filters[f_type] = f_value
        await state.update_data(filters=filters, page=0)
        await call.message.delete()
    elif action == 'search_start':
        await state.set_state(Form.garage_search) # Re-use garage search FSM
        await state.update_data(
            context_message_id=call.message.message_id, 
            previous_state=Form.crafting,
            craft_rarity=rarity # Pass rarity to restore context
        )
        kb = InlineKeyboardBuilder().button(text="Отмена", callback_data=f"craft:back:{rarity}").as_markup()
        if call.message.photo: await call.message.delete()
        await call.message.answer("Введите название машины для поиска:", reply_markup=kb)
        return
    elif action == 'back':
        await call.message.delete()

    elif action == "select":
        _, car_name, op = params
        # Ищем конкретную машину, чтобы узнать кол-во дублей
        car_info_list = db.get_filtered_garage(call.from_user.id, {'rarity': rarity, 'duplicates': True, 'search_query': car_name})
        if not car_info_list: return await call.answer("Машина не найдена.", show_alert=True)
        
        available_for_craft = car_info_list[0]['count'] - 1
        current_selection_count = selection.get(car_name, 0)

        if op == '+':
            if current_selection_count < available_for_craft:
                selection[car_name] = current_selection_count + 1
        elif op == '-':
            if current_selection_count > 0:
                selection[car_name] = current_selection_count - 1
                if selection[car_name] == 0:
                    del selection[car_name]

        await state.update_data(selection=selection)

    elif action == "do" or action == "random":
        recipe = config.CRAFT_RECIPES.get(rarity)
        if not recipe: return await call.answer("Ошибка: рецепт не найден.", show_alert=True)

        all_duplicates_raw = db.get_all_user_duplicates(call.from_user.id)
        
        ids_to_delete = []
        if action == "random":
            # Собираем ID только тех дубликатов, которые имеют нужную редкость
            candidate_ids = [d['car_id'] for d in all_duplicates_raw if d['rarity'] == rarity]
            if len(candidate_ids) >= recipe['cost']:
                ids_to_delete = random.sample(candidate_ids, recipe['cost'])
        else: # "do"
            if sum(selection.values()) != recipe['cost']:
                return await call.answer("Неверное количество машин для крафта.", show_alert=True)
            
            # Собираем ID для удаления на основе выбора
            selected_car_names = list(selection.keys())
            duplicates_of_selected_cars = [d for d in all_duplicates_raw if d['car_name'] in selected_car_names]
            
            for car_name, count_to_delete in selection.items():
                ids_for_this_car = [d['car_id'] for d in duplicates_of_selected_cars if d['car_name'] == car_name]
                # Берем `count_to_delete` ID из списка дубликатов этой машины
                ids_to_delete.extend(ids_for_this_car[:count_to_delete])

        if not ids_to_delete or len(ids_to_delete) != recipe['cost']:
            return await call.answer("Недостаточно машин для крафта!", show_alert=True)
        
        # --- Выполняем крафт ---
        db.delete_cars_by_ids(ids_to_delete)
        result = logic.craft_car(recipe['result'])
        if result['status'] != 'success':
             return await call.answer(f"Ошибка крафта: {result['message']}", show_alert=True)

        new_car = result['car']
        db.add_car(
            call.from_user.id, new_car['name'], new_car['rarity'], new_car['value'],
            new_car.get('brand'), new_car.get('season'), new_car.get('image_file_id')
        )
        
        style = config.RARITY_STYLES.get(new_car['rarity'], {})
        text = (f"🎉 <b>Крафт успешен!</b> 🎉\n\nВы получили новую машину:\n"
                f"{style.get('color', '')} <b>{new_car['name']}</b> ({new_car['rarity']})")

        photo_id = new_car.get("image_file_id")
        kb = InlineKeyboardBuilder()
        kb.button(text="Продолжить крафт", callback_data="craft_menu")
        kb.button(text="↩️ В меню", callback_data="main_menu")
        kb.adjust(1)
        
        await call.message.delete()
        try:
            await bot.send_photo(call.from_user.id, photo=photo_id or FSInputFile("images/default_car.png"), caption=text, reply_markup=kb.as_markup())
        except Exception:
            await bot.send_photo(call.from_user.id, photo=FSInputFile("images/default_car.png"), caption=text, reply_markup=kb.as_markup())
        
        await state.clear()
        return

    # Обновляем интерфейс после действия
    await display_craft_view(bot, call.from_user.id, call.message.chat.id, state, db, call.message)
    await call.answer()


@router.message(Form.garage_search)
async def process_craft_search(message: Message, state: FSMContext, db: Database, bot: Bot):
    """Обрабатывает ввод поиска из интерфейса крафта."""
    data = await state.get_data()
    # Убедимся, что мы вернулись из поиска в контексте крафта
    if data.get('previous_state') != Form.crafting:
        return

    filters = data.get('filters', {})
    context_message_id = data.get('context_message_id')
    rarity = data.get('craft_rarity') # Восстанавливаем редкость

    filters['search_query'] = message.text
    
    await state.set_state(Form.crafting)
    await state.update_data(filters=filters, page=0)
    
    await message.delete()
    
    # Пытаемся восстановить контекстное сообщение для редактирования
    context_message = None
    if context_message_id:
        try:
            # Создаем фейковый объект, достаточный для редактирования
            context_message = Message(message_id=context_message_id, chat=message.chat, date=int(time.time()), photo=()) # photo is not None to trigger media edit
        except Exception:
            pass # Если не вышло, просто отправим новое

    await display_craft_view(bot, message.from_user.id, message.chat.id, state, db, context_message)

