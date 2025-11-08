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
import logging
import os
import time
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database
from logic import GameLogic
from middlewares.main_middlewares import SubscriptionMiddleware, BanMiddleware, GroupMemberMiddleware, TestModeMiddleware
from handlers import (admin, common, garage, group, minigames, profile, shop, support, trade, craft)

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация основных компонентов
bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
db_instance = Database(config.DB_CONFIG)
logic_instance = GameLogic(db_instance)

# === Фоновые задачи ===

async def case_notifier():
    """
    Периодически проверяет, готов ли у пользователей бесплатный кейс,
    и отправляет уведомления, включая повторные напоминания.
    """
    while True:
        await asyncio.sleep(config.CASE_NOTIFIER_INTERVAL)
        logging.info("Проверка пользователей для уведомлений о кейсах...")
        
        users_to_check = db_instance.get_users_for_notification_check()
        now = int(time.time())

        for user_data in users_to_check:
            user_id = user_data['user_id']
            
            # 1. Определяем актуальный кулдаун для пользователя
            db_instance.check_and_update_pass_status(user_id)
            # Пере-получаем данные, так как check_and_update_pass_status мог их изменить
            refreshed_user_data = db_instance.get_user(user_id) 
            if not refreshed_user_data: continue

            last_free_case_time = refreshed_user_data['last_free_case']
            has_pass = refreshed_user_data['collect_pass_active']
            
            # Проверяем, был ли CollectPass активен в момент ПОСЛЕДНЕГО открытия кейса
            is_pass_active_for_cooldown = has_pass and last_free_case_time >= (refreshed_user_data['collect_pass_expires_at'] - config.COLLECT_PASS_DURATION)
            cooldown = config.FREE_CASE_COOLDOWN_PASS if is_pass_active_for_cooldown else config.FREE_CASE_COOLDOWN
            
            case_ready_time = last_free_case_time + cooldown
            
            # 2. Проверяем, готов ли кейс
            if now < case_ready_time:
                continue # Кейс еще не готов, переходим к следующему пользователю

            # 3. Кейс готов, решаем, нужно ли отправлять уведомление
            last_notification_time = refreshed_user_data.get('last_case_notification', 0)
            
            should_notify = False
            # Случай 1: Первое уведомление. Отправляем, если не было уведомлений после открытия кейса (метка 0)
            if last_notification_time == 0:
                should_notify = True
            # Случай 2: Повторное уведомление. Отправляем, если прошло достаточно времени с последнего напоминания.
            elif now >= last_notification_time + config.CASE_REMINDER_INTERVAL:
                should_notify = True

            if should_notify:
                try:
                    builder = InlineKeyboardBuilder().button(text="🎉 Открыть кейс", callback_data="confirm_open_case")
                    await bot.send_message(user_id, "🎁 Ваш бесплатный кейс готов!", reply_markup=builder.as_markup())
                    db_instance.update_last_case_notification(user_id)
                    logging.info(f"Отправлено уведомление о кейсе пользователю {user_id}")
                except Exception as e:
                    logging.warning(f"Не удалось отправить уведомление {user_id}: {e}")
                    # Обновляем таймер даже при ошибке, чтобы не спамить
                    db_instance.update_last_case_notification(user_id) 
                await asyncio.sleep(0.2)


async def airdrop_notifier():
    """Periodically checks chats and sends airdrops if it's time."""
    logging.info("Airdrop background task started. Initial delay of 10 seconds...")
    await asyncio.sleep(10)  # Initial delay
    
    known_chat_ids = set()
    initial_chats = db_instance.get_chats_for_airdrop()
    if initial_chats:
        known_chat_ids = {chat['chat_id'] for chat in initial_chats}
    logging.info(f"Initial check found {len(known_chat_ids)} chats with airdrops enabled.")

    while True:
        try:
            current_chats = db_instance.get_chats_for_airdrop()
            current_chat_ids = {chat['chat_id'] for chat in current_chats}

            # Log only if the set of chats has changed
            if current_chat_ids != known_chat_ids:
                logging.info(f"Airdrop chat list updated. Now tracking {len(current_chat_ids)} chats.")
                known_chat_ids = current_chat_ids

            if not current_chats:
                await asyncio.sleep(config.AIRDROP_NOTIFIER_INTERVAL)
                continue

            now = int(time.time())

            for chat in current_chats:
                chat_id = chat['chat_id']
                if now >= chat['last_airdrop_time'] + chat['airdrop_cooldown_seconds']:
                    logging.info(f"Airdrop conditions met for chat {chat_id}. Attempting to send...")
                    try:
                        # Send a placeholder button first
                        kb = InlineKeyboardBuilder().button(text="🎉 Забрать!", callback_data="claim_airdrop:0").as_markup()
                        msg = await bot.send_message(chat_id, "🎁 <b>Внимание, дроп!</b>", reply_markup=kb)

                        # Create the airdrop record in the DB to get a unique ID
                        claim_id = db_instance.create_airdrop(chat_id, msg.message_id)

                        # Update the message with the correct button including the claim ID
                        updated_kb = InlineKeyboardBuilder().button(text="🎉 Забрать!", callback_data=f"claim_airdrop:{claim_id}").as_markup()
                        await msg.edit_reply_markup(reply_markup=updated_kb)

                        logging.info(f"Airdrop successfully sent to chat {chat_id}, claim_id: {claim_id}")
                    except Exception as e:
                        logging.error(f"Failed to send airdrop to chat {chat_id}: {e}")

                    await asyncio.sleep(1)  # Small delay between sending to different chats
        except Exception as e:
            # Global error handler for the entire loop iteration to prevent the task from crashing silently
            logging.error(f"Critical error in airdrop_notifier loop: {e}")

        await asyncio.sleep(config.AIRDROP_NOTIFIER_INTERVAL)


# === Запуск бота ===
async def main():
    # Запуск фоновых задач
    airdrop_task = asyncio.create_task(airdrop_notifier())
    notifier_task = asyncio.create_task(case_notifier())

    if config.TEST_MODE:
        dp.update.outer_middleware(TestModeMiddleware())
        logging.warning("️⚙️Бот находится на технических работах.")

    # Регистрация middleware
    dp.update.outer_middleware(SubscriptionMiddleware())
    dp.update.outer_middleware(BanMiddleware())
    dp.message.middleware(GroupMemberMiddleware())
    dp.callback_query.middleware(GroupMemberMiddleware())

    # Передача зависимостей (db, logic) в хендлеры
    dp["db"] = db_instance
    dp["logic"] = logic_instance
    
    # Подключение роутеров
    routers_to_include = [
        admin.router, common.router, garage.router, group.router, 
        minigames.router, profile.router, shop.router, support.router, 
        trade.router, craft.router
    ]
    for r in routers_to_include:
        dp.include_router(r)

    # Удаление вебхука и запуск поллинга
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        # Корректное завершение фоновых задач
        airdrop_task.cancel()
        notifier_task.cancel()
        with suppress(asyncio.CancelledError):
            await airdrop_task
            await notifier_task
        await bot.session.close()


if __name__ == "__main__":
    # Проверка наличия необходимых директорий и файлов
    if not os.path.exists(config.IMAGES_PATH):
        os.makedirs(config.IMAGES_PATH)
    if not os.path.exists("images/default_car.png"):
        logging.warning("Файл-заглушка 'images/default_car.png' не найден.")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную.")
