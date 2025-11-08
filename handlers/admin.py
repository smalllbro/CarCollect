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
from datetime import datetime
from contextlib import suppress

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError

import config
from db import Database
from logic import GameLogic
from middlewares.main_middlewares import IsAdmin
from utils.fsm import Form
from utils.helpers import safe_edit_text, format_value
from backup_manager import create_backup

router = Router()


# === Вспомогательная функция для поиска машины ===

def find_car_in_logic(car_name: str, logic: GameLogic) -> dict | None:
    """Ищет машину по названию во всех кейсах в logic."""
    for case_data in logic.cases.values():
        for car in case_data.get("cars", []):
            if car['name'].lower() == car_name.lower():
                return car
    return None

# === Обработчики команд ===

@router.message(Command("backup"), IsAdmin())
async def cmd_backup(message: Message):
    """
    Создает резервную копию базы данных по команде администратора.
    """
    await message.answer("⏳ Начинаю процесс создания резервной копии...")
    success, result_message = create_backup()
    if success:
        await message.answer(f"✅ Резервная копия успешно создана!\nПуть к файлу: <code>{result_message}</code>")
    else:
        await message.answer(f"❌ <b>Произошла ошибка при создании бэкапа:</b>\n\n<code>{result_message}</code>")


@router.message(Command("addpromo", "editpromo"), IsAdmin())
async def cmd_add_or_edit_promo(message: Message, db: Database, logic: GameLogic):
    """Обрабатывает создание и редактирование промокодов."""
    is_editing = message.text.startswith("/editpromo")
    command_name = "/editpromo" if is_editing else "/addpromo"
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            f"<b>Неверный формат.</b>\n"
            f"<code>{command_name} CODE type value [max_uses]</code>\n"
            f"<code>{command_name} CODE car \"Car Name\" [max_uses]</code>"
        )
        return

    args_str = parts[1]
    
    match = re.match(r'(\S+)\s+car\s+"([^"]+)"\s*(\d*)', args_str)
    
    if match:
        code, car_name, max_uses_str = match.groups()
        r_type = 'car'
        r_value_or_name = car_name
        max_uses = int(max_uses_str) if max_uses_str else 1
        
        found_car = find_car_in_logic(car_name, logic)
        if not found_car:
            return await message.answer(f"Машина с названием «{car_name}» не найдена в `cars.json`.")
    else:
        args = args_str.split()
        if len(args) < 3:
            return await message.answer(f"Неверный формат для награды типа `tires` или `extra_attempts`.")
        
        code, r_type, r_value_str, max_uses_str = args[0], args[1], args[2], args[3] if len(args) > 3 else "1"
        if r_type not in ['tires', 'extra_attempts']:
            return await message.answer("Неверный тип награды. Доступно: `tires`, `extra_attempts`, `car`.")
        if not r_value_str.isdigit() or not max_uses_str.isdigit():
            return await message.answer("Значение и лимит активаций должны быть числами.")
        
        r_value_or_name = int(r_value_str)
        max_uses = int(max_uses_str)

    promo_exists = db.get_promo_by_text(code)
    
    if is_editing:
        if not promo_exists:
            return await message.answer(f"❌ Промокод <code>{code.upper()}</code> не найден. Для создания используйте /addpromo.")
        
        if db.edit_promo_code(code, r_type, r_value_or_name, max_uses):
            await message.answer(f"✅ Промокод <code>{code.upper()}</code> успешно изменен!")
        else:
            await message.answer("❌ Не удалось изменить промокод.")
    else:
        if promo_exists:
            return await message.answer(f"❌ Промокод <code>{code.upper()}</code> уже существует. Для изменения используйте /editpromo.")

        if db.add_promo_code(code, r_type, r_value_or_name, max_uses):
            await message.answer(f"✅ Промокод <code>{code.upper()}</code> успешно создан!")
        else:
            await message.answer("❌ Произошла ошибка при создании промокода.")


@router.message(Command("give"), IsAdmin())
async def cmd_give(message: Message, db: Database, bot: Bot, logic: GameLogic):
    """
    Выдает ресурсы или машину пользователю.
    Синтаксис:
    /give [user_id] tires [amount]
    /give [user_id] extra_attempts [amount]
    /give [user_id] car "Название машины" [amount]
    """
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("<b>Неверный формат.</b>\nПримеры:\n<code>/give 12345 tires 100</code>\n<code>/give 12345 car \"Ford Focus\" 5</code>")
    
    args_str = parts[1]
    
    user_id_match = re.match(r'(\d+)\s+(.*)', args_str)
    if not user_id_match:
        return await message.answer("Не указан или неверно указан ID пользователя.")
    
    target_id_str, rest_args = user_id_match.groups()
    target_id = int(target_id_str)

    if not db.get_user(target_id):
        return await message.answer(f"Пользователь с ID {target_id} не найден.")

    # Обрабатываем выдачу машины (с возможностью указания количества)
    car_match = re.match(r'car\s+"([^"]+)"(?:\s+(\d+))?', rest_args)
    if car_match:
        car_name, quantity_str = car_match.groups()
        quantity = int(quantity_str) if quantity_str else 1
        
        found_car = find_car_in_logic(car_name, logic)
        
        if not found_car:
            return await message.answer(f"Машина «{car_name}» не найдена в `cars.json`.")
        
        for _ in range(quantity):
            db.add_car(
                target_id, found_car['name'], found_car['rarity'], found_car['value'],
                found_car.get('brand', 'N/A'), found_car.get('season', 'N/A'),
                image_file_id=found_car.get("image_file_id")
            )
        
        quantity_text = f" в количестве {quantity} шт." if quantity > 1 else ""
        await message.answer(f"✅ Машина «{found_car['name']}»{quantity_text} выдана пользователю {target_id}.")
        
        with suppress(TelegramForbiddenError):
            notification_text = f"🎉 Администратор выдал вам машину: <b>{found_car['name']}</b>"
            if quantity > 1:
                notification_text += f" (x{quantity})"
            await bot.send_message(target_id, notification_text)
        return

    # Обрабатываем выдачу ресурсов
    resource_args = rest_args.split()
    if len(resource_args) == 2 and resource_args[1].isdigit():
        r_type, amount = resource_args[0], int(resource_args[1])
        
        if r_type == 'tires':
            db.change_tires(target_id, amount, f"Админ-команда от {message.from_user.id}")
            await message.answer(f"✅ Пользователю {target_id} начислено {amount} 🛞.")
            with suppress(TelegramForbiddenError):
                await bot.send_message(target_id, f"🎉 Администратор начислил вам <b>{amount} 🛞</b>!")
        elif r_type == 'extra_attempts':
            db.add_extra_attempts(target_id, amount)
            await message.answer(f"✅ Пользователю {target_id} начислено {amount} доп. попыток.")
            with suppress(TelegramForbiddenError):
                await bot.send_message(target_id, f"🎉 Администратор начислил вам <b>{amount}</b> доп. попыток!")
        else:
            await message.answer("Неверный тип ресурса. Доступно: `tires`, `extra_attempts`, `car`")
    else:
        await message.answer("Неверный формат команды. Проверьте синтаксис.")


def check_menu_kb(user_id: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="История платежей", callback_data=f"check_paymod:{user_id}:0")
    builder.button(text="История покрышек", callback_data=f"check_tiremod:{user_id}:0")
    return builder.as_markup()

@router.message(Command("tickets"), IsAdmin())
async def cmd_tickets(message: Message, db: Database):
    tickets = db.get_open_tickets()
    if not tickets:
        await message.answer("Открытых тикетов нет.")
        return

    response = "<b>Открытые тикеты:</b>\n\n"
    for t in tickets:
        pay_mark = " [pay]" if t.get('source') == 'pay' else ""
        response += f"<b>ID:</b> <code>{t['ticket_id']}</code>{pay_mark} от <b>User ID:</b> <code>{t['user_id']}</code>\n"
        response += f"<i>{t['message_text'][:30]}...</i>\n\n"
    response += "\nДля просмотра полного текста используйте <code>/ticket [id]</code>"
    await message.answer(response)

@router.message(Command("ticket"), IsAdmin())
async def cmd_view_ticket(message: Message, db: Database):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Используйте: <code>/ticket [id]</code>")
        return
    
    ticket_id = int(parts[1])
    ticket = db.get_ticket(ticket_id)

    if not ticket:
        await message.answer("Тикет с таким ID не найден.")
        return
    
    date = datetime.fromtimestamp(ticket['created_at']).strftime('%Y-%m-%d %H:%M:%S')
    response = (
        f"<b>Тикет #{ticket['ticket_id']}</b>\n\n"
        f"<b>User ID:</b> <code>{ticket['user_id']}</code>\n"
        f"<b>Статус:</b> {ticket['status']}\n"
        f"<b>Источник:</b> {ticket.get('source', 'general')}\n"
        f"<b>Дата:</b> {date}\n\n"
        f"<b>Сообщение:</b>\n{ticket['message_text']}"
    )
    await message.answer(response)

@router.message(Command("closeticket"), IsAdmin())
async def cmd_closeticket(message: Message, state: FSMContext, db: Database):
    parts = message.text.split(maxsplit=1)
    args_str = parts[1] if len(parts) > 1 else ""
    args = args_str.split()

    if len(args) < 1 or not args[0].isdigit():
        await message.answer("Используйте: <code>/closeticket [ticket_id]</code>")
        return

    ticket_id = int(args[0])
    ticket = db.get_ticket(ticket_id)
    if not ticket or ticket['status'] != 'open':
        await message.answer("Тикет не найден или уже закрыт.")
        return

    await state.update_data(ticket_id_to_close=ticket_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="Отправить с сообщением", callback_data=f"close_ticket_prompt:with_message:{ticket_id}")
    builder.button(text="Отправить без сообщения", callback_data=f"close_ticket_prompt:without_message:{ticket_id}")
    builder.button(text="Принудительно закрыть", callback_data=f"close_ticket_prompt:force_close:{ticket_id}")
    builder.button(text="Отмена", callback_data="close_ticket_prompt:cancel")
    builder.adjust(2)

    await message.answer(f"Как закрыть тикет #{ticket_id}?", reply_markup=builder.as_markup())


@router.message(Command("check"), IsAdmin())
async def cmd_check(message: Message, state: FSMContext, db: Database):
    await state.clear()
    parts = message.text.split(maxsplit=1)
    args_str = parts[1] if len(parts) > 1 else ""
    args = args_str.split()

    if not args or not args[0].isdigit():
        await message.answer("Используйте: <code>/check [user_id]</code>")
        return

    target_id = int(args[0])
    user = db.get_user(target_id)
    if not user:
        await message.answer("Пользователь не найден.")
        return

    collection_value = db.get_collection_value(target_id)
    car_count = db.get_garage_count(target_id)
    collection_value_formatted = format_value(collection_value)

    profile_text = (
        f"<b>Профиль игрока {user.get('nickname', target_id)} ({target_id})</b>\n\n"
        f"Машин в гараже: <b>{car_count}</b>\n"
        f"Стоимость коллекции: <b>{collection_value_formatted}</b>\n"
        f"Покрышек: <b>{user.get('tires', 0)}</b>\n"
        f"Доп. попыток: <b>{user.get('extra_attempts', 0)}</b>\n"
        f"Забанен: <b>{'Да' if user.get('is_banned') else 'Нет'}</b>"
    )
    await message.answer(profile_text, reply_markup=check_menu_kb(target_id))


@router.message(Command("ban", "unban"), IsAdmin())
async def cmd_ban_unban(message: Message, db: Database):
    is_banning = message.text.startswith("/ban")
    parts = message.text.split(maxsplit=1)
    args_str = parts[1] if len(parts) > 1 else ""
    args = args_str.split()

    if not args or not args[0].isdigit():
        await message.answer(f"Используйте: <code>/{'ban' if is_banning else 'unban'} [user_id]</code>")
        return

    target_id = int(args[0])
    if not db.get_user(target_id):
        await message.answer("Пользователь не найден.")
        return

    db.set_ban_status(target_id, is_banning)
    await message.answer(f"✅ Пользователь {target_id} был успешно {'забанен' if is_banning else 'разбанен'}.")


@router.message(Command("broadcast"), IsAdmin())
async def cmd_broadcast(message: Message, bot: Bot, db: Database):
    parts = message.text.split(maxsplit=1)
    text = parts[1] if len(parts) > 1 else None

    if not text:
        await message.answer("Введите текст для рассылки после команды.")
        return

    user_ids = db.get_all_user_ids()
    sent_count, failed_count = 0, 0
    await message.answer(f"Начинаю рассылку для {len(user_ids)} пользователей...")
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text)
            sent_count += 1
            await asyncio.sleep(0.1)
        except Exception:
            failed_count += 1
    await message.answer(f"✅ Рассылка завершена!\n\nОтправлено: {sent_count}\nНе удалось отправить: {failed_count}")


@router.message(Command("stats"), IsAdmin())
async def cmd_stats(message: Message, db: Database):
    total_cars = db.get_total_cars_in_game()
    stats_text = (
        "<b>📊 Статистика бота</b>\n\n"
        f"Всего пользователей: <b>{db.get_total_users()}</b>\n"
        f"Новых за 24ч: <b>{db.get_new_users_count(24)}</b>\n"
        f"Всего машин в игре: <b>{total_cars}</b>\n"
        f"Всего покрышек в экономике: <b>{db.get_total_tires()} 🛞</b>"
    )

    if total_cars > 0:
        rarity_dist = db.get_rarity_distribution()
        if rarity_dist:
            stats_text += "\n\n<b>Распределение по редкости:</b>\n"
            sorted_dist = sorted(
                rarity_dist,
                key=lambda item: list(config.RARITY_STYLES.keys()).index(item['rarity'])
            )
            for item in sorted_dist:
                rarity = item['rarity']
                count = item['count']
                percentage = (count / total_cars) * 100
                style = config.RARITY_STYLES.get(rarity, {})
                stats_text += (
                    f"{style.get('color', '')} {rarity}: "
                    f"<b>{count}</b> шт. ({percentage:.2f}%)\n"
                )

    await message.answer(stats_text)


@router.message(Command("promolist"), IsAdmin())
async def cmd_promolist(message: Message, db: Database):
    promos = db.get_all_promos()
    if not promos:
        await message.answer("Промокодов пока нет.")
        return
    promo_list_text = "<b>📜 Список промокодов:</b>\n\n"
    for p in promos:
        status = "🟢 Активен" if p['is_active'] else "🔴 Неактивен"
        limit = "∞" if p['max_activations'] == 0 else p['max_activations']
        promo_list_text += f"<code>{p['code_text']}</code> ({p['current_activations']}/{limit}) - {status}\n"
    await message.answer(promo_list_text)


@router.message(Command("deactivatepromo"), IsAdmin())
async def cmd_deactivatepromo(message: Message, db: Database):
    parts = message.text.split(maxsplit=1)
    code = parts[1] if len(parts) > 1 else None

    if not code:
        await message.answer("Введите промокод для деактивации.")
        return

    if db.deactivate_promo(code):
        await message.answer(f"✅ Промокод <code>{code.upper()}</code> деактивирован.")
    else:
        await message.answer("Промокод не найден.")


@router.message(Command("refund"), IsAdmin())
async def cmd_refund(message: Message, bot: Bot, db: Database):
    parts = message.text.split(maxsplit=1)
    args_str = parts[1] if len(parts) > 1 else ""
    args = args_str.split()

    if len(args) != 2 or not args[0].isdigit():
        await message.answer("Используйте: <code>/refund [user_id] [transaction_id]</code>")
        return

    target_id, t_id = int(args[0]), args[1]
    transaction = db.get_transaction(t_id)
    if not transaction:
        await message.answer("Транзакция с таким ID не найдена.")
        return
    if transaction['status'] == 'refunded':
        await message.answer("Эта транзакция уже была возвращена.")
        return

    try:
        success = await bot.refund_star_payment(user_id=target_id, telegram_payment_charge_id=t_id)
        if success:
            payload = transaction['payload']
            if payload.startswith("buy_tires:"):
                pack_id = payload.split(":")[1]
                pack = config.TIRE_PACKS.get(pack_id)
                if pack:
                    db.change_tires(target_id, -pack['tires'], f"Возврат по транзакции {t_id}")
            db.update_transaction_status(t_id, 'refunded')
            await message.answer(f"✅ Успешно! Платеж {t_id} для пользователя {target_id} возвращен.")
            await bot.send_message(
                target_id,
                "Вам был оформлен возврат средств за покупку в нашем боте. "
                "Telegram Stars будут возвращены на ваш счет."
            )
        else:
            await message.answer("Telegram отклонил запрос на возврат.")
    except Exception as e:
        await message.answer(f"Произошла ошибка при возврате: {e}")


# === Админ-панель (/check) ===

@router.callback_query(F.data.startswith("check_paymod:"), IsAdmin())
async def cq_check_paymod(call: CallbackQuery, state: FSMContext, db: Database):
    try:
        _, user_id_str, page_str = call.data.split(":")
        user_id, page = int(user_id_str), int(page_str)
    except ValueError:
        return await call.answer("Ошибка данных.", show_alert=True)

    total_transactions = db.get_user_transactions_count(user_id)
    if total_transactions == 0:
        return await call.answer("У этого пользователя нет платежей.", show_alert=True)

    page = max(0, min(page, total_transactions - 1))
    transaction = db.get_user_transactions_page(user_id, page, limit=1)[0]
    date = datetime.fromtimestamp(transaction['created_at']).strftime('%Y-%m-%d %H:%M:%S')

    text = (
        f"<b>История платежей (Платеж {page + 1}/{total_transactions})</b>\n\n"
        f"<b>User ID:</b> <code>{transaction['user_id']}</code>\n"
        f"<b>Transaction ID:</b> <code>{transaction['transaction_id']}</code>\n"
        f"<b>Сумма:</b> {transaction['amount_stars']} ⭐\n"
        f"<b>Товар:</b> {transaction['payload']}\n"
        f"<b>Дата:</b> {date}\n"
        f"<b>Статус:</b> {transaction.get('status', 'completed')}"
    )

    builder = InlineKeyboardBuilder()
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"check_paymod:{user_id}:{page - 1}"))
    if page < total_transactions - 1: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"check_paymod:{user_id}:{page + 1}"))
    if nav_row: builder.row(*nav_row)
    if transaction.get('status', 'completed') == 'completed': builder.button(text="Вернуть деньги", callback_data=f"admin_refund_confirm")
    builder.button(text="↩️ Назад к профилю", callback_data=f"back_to_check:{user_id}")
    builder.adjust(1)
    
    await state.set_state(Form.admin_context)
    await state.update_data(current_transaction=transaction)

    await safe_edit_text(call, text, reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("check_tiremod:"), IsAdmin())
async def cq_check_tiremod(call: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    try:
        _, user_id_str, page_str = call.data.split(":")
        user_id, page = int(user_id_str), int(page_str)
    except ValueError:
        return await call.answer("Ошибка данных.", show_alert=True)

    limit = 5
    total_logs = db.get_tire_log_count(user_id)
    if total_logs == 0:
        return await call.answer("Нет истории операций с покрышками.", show_alert=True)
    
    total_pages = (total_logs - 1) // limit
    page = max(0, min(page, total_pages))
    logs = db.get_tire_log_page(user_id, page, limit=limit)

    text = f"<b>История покрышек (Стр. {page + 1}/{total_pages + 1})</b>\n\n"
    for log in logs:
        date = datetime.fromtimestamp(log['timestamp']).strftime('%Y-%m-%d %H:%M')
        sign = "+" if log['change_amount'] > 0 else ""
        text += f"<code>{date}</code> | <b>{sign}{log['change_amount']} 🛞</b> | {log['reason']}\n"

    builder = InlineKeyboardBuilder()
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"check_tiremod:{user_id}:{page - 1}"))
    if page < total_pages: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"check_tiremod:{user_id}:{page + 1}"))
    if nav_row: builder.row(*nav_row)
    builder.button(text="↩️ Назад к профилю", callback_data=f"back_to_check:{user_id}")
    builder.adjust(1)
    
    await safe_edit_text(call, text, reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data == "admin_refund_confirm", Form.admin_context, IsAdmin())
async def cq_admin_refund_confirm(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    transaction = data.get('current_transaction')
    if not transaction:
        return await call.answer("Контекст утерян, попробуйте снова.", show_alert=True)

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, вернуть", callback_data="admin_refund_do")
    builder.button(text="❌ Нет, отмена", callback_data=f"check_paymod:{transaction['user_id']}:0")
    
    await safe_edit_text(call, f"Вы уверены, что хотите вернуть платеж <code>{transaction['transaction_id']}</code>?", reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin_refund_do", Form.admin_context, IsAdmin())
async def cq_admin_refund_do(call: CallbackQuery, state: FSMContext, bot: Bot, db: Database):
    data = await state.get_data()
    transaction = data.get('current_transaction')
    if not transaction:
        return await call.answer("Контекст утерян, попробуйте снова.", show_alert=True)

    target_id, t_id = transaction['user_id'], transaction['transaction_id']

    try:
        success = await bot.refund_star_payment(user_id=target_id, telegram_payment_charge_id=t_id)
        if success:
            payload = transaction['payload']
            if payload.startswith("buy_tires:"):
                pack_id = payload.split(":")[1]
                pack = config.TIRE_PACKS.get(pack_id)
                if pack:
                    db.change_tires(target_id, -pack['tires'], f"Возврат по транзакции {t_id}")

            db.update_transaction_status(t_id, 'refunded')
            await call.answer(f"Платеж {t_id} возвращен!", show_alert=True)
            await bot.send_message(target_id, "Вам был оформлен возврат средств за покупку в нашем боте.")
            
            await state.clear()
            call.data = f"back_to_check:{target_id}"
            await cq_back_to_check(call, state, db)
        else:
            await call.answer("Telegram отклонил запрос на возврат.", show_alert=True)
    except Exception as e:
        await call.answer(f"Ошибка: {e}", show_alert=True)


@router.callback_query(F.data.startswith("back_to_check:"), IsAdmin())
async def cq_back_to_check(call: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    target_id = int(call.data.split(":")[1])
    user = db.get_user(target_id)
    if not user:
        return await safe_edit_text(call, "Пользователь не найден.")

    collection_value = db.get_collection_value(target_id)
    car_count = db.get_garage_count(target_id)
    profile_text = (
        f"<b>Профиль игрока {user.get('nickname', target_id)} ({target_id})</b>\n\n"
        f"Машин в гараже: <b>{car_count}</b>\n"
        f"Стоимость коллекции: <b>{format_value(collection_value)}</b>\n"
        f"Покрышек: <b>{user.get('tires', 0)}</b>\n"
        f"Доп. попыток: <b>{user.get('extra_attempts', 0)}</b>\n"
        f"Забанен: <b>{'Да' if user.get('is_banned') else 'Нет'}</b>"
    )
    await safe_edit_text(call, profile_text, reply_markup=check_menu_kb(target_id))
    await call.answer()

