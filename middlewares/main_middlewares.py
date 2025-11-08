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
import logging
from typing import Callable, Dict, Any, Awaitable, Union
from contextlib import suppress

from aiogram import BaseMiddleware, Bot
from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database

class UserCheckMiddleware(BaseMiddleware):
    """
    Проверяет, зарегистрирован ли пользователь в системе.
    Если нет, и команда не /start, прерывает выполнение и просит
    пользователя зарегистрироваться.
    """
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        user = data.get('event_from_user')

        # Если не можем определить пользователя, ничего не делаем
        if not user:
            return await handler(event, data)

        db: Database = data['db']

        # Пропускаем, если пользователь уже существует в БД
        if db.get_user(user.id):
            return await handler(event, data)

        # --- Пользователя нет в БД ---

        # Если это сообщение и оно начинается с /start, пропускаем его,
        # чтобы хендлер /start мог зарегистрировать пользователя.
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        # Во всех остальных случаях блокируем и просим зарегистрироваться
        text = "Вы не зарегистрированы в боте. Пожалуйста, используйте команду /start для начала работы."
        try:
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                # Для колбэков лучше отправлять новое сообщение, а не редактировать
                await event.message.answer(text)
                await event.answer() # Закрываем "часики" на кнопке
        except (TelegramBadRequest, TelegramForbiddenError):
            pass # Игнорируем ошибки, если не можем отправить сообщение

        return # Прерываем дальнейшую обработку этого события

class TestModeMiddleware(BaseMiddleware):
    """
    Middleware для активации режима "технических работ".
    Пропускает только администраторов и тестеров из config.
    """
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        user = data.get('event_from_user')
        
        # Собираем всех, у кого есть доступ
        allowed_users = config.ADMIN_IDS + config.TESTER_IDS

        # Если не удалось определить пользователя или он в списке доступа, пропускаем
        if not user or user.id in allowed_users:
            return await handler(event, data)

        # Для всех остальных пользователей блокируем доступ
        logging.info(f"TestMode: Заблокирован доступ для user_id: {user.id}")
        text = "⚙️ Бот находится на технических работах. Пожалуйста, зайдите позже."
        
        try:
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logging.warning(f"TestMode: Не удалось отправить сообщение user_id: {user.id}. Ошибка: {e}")
            
        return # Останавливаем обработку


class IsAdmin(Filter):
    """
    Фильтр для проверки, является ли пользователь администратором бота.
    """
    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        return event.from_user.id in config.ADMIN_IDS


class SubscriptionMiddleware(BaseMiddleware):
    """
    Middleware для проверки подписки пользователя на обязательный канал.
    """
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        user = data.get('event_from_user')
        bot: Bot = data.get('bot')

        # Пропускаем, если нет пользователя или это админ
        if not user or user.id in config.ADMIN_IDS:
            return await handler(event, data)

        try:
            member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user.id)
            # Пропускаем, если пользователь подписан
            if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                return await handler(event, data)
        except TelegramBadRequest as e:
            if "user not found" in e.message:
                pass  # Пользователь не в канале, продолжаем для отправки сообщения о подписке
            else:
                logging.error(f"Ошибка проверки подписки для {user.id} в {config.CHANNEL_ID}: {e}")
                return await handler(event, data) # Пропускаем, чтобы не блокировать пользователя из-за ошибки
        except Exception as e:
            logging.error(f"Непредвиденная ошибка проверки подписки для {user.id}: {e}")
            return await handler(event, data) # Пропускаем при других ошибках

        logging.info(f"User {user.id} is not subscribed. Handling event.")

        # --- ОБНОВЛЕННАЯ ЛОГИКА ОТПРАВКИ СООБЩЕНИЯ ---

        # Для групп: просто показываем всплывающее уведомление
        if isinstance(event, CallbackQuery) and event.message and event.message.chat.type in ('group', 'supergroup'):
            await event.answer(
                "Вы не подписаны на канал. Подпишитесь и попробуйте снова!",
                show_alert=True
            )
            return  # Останавливаем обработку

        # Для личных чатов: отправляем новое сообщение с кнопками
        channel_link = f"https://t.me/{config.CHANNEL_ID.replace('@', '')}"
        text = (
            "❗️ Для доступа к боту необходимо подписаться на наш канал.\n\n"
            "Подпишитесь и нажмите кнопку ниже, чтобы продолжить."
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="➡️ Перейти к каналу", url=channel_link)
        builder.button(text="✅ Я подписался", callback_data="check_subscription")
        builder.adjust(1)
        
        try:
            # Если это было нажатие на кнопку, убираем "часики" и пытаемся удалить старое сообщение
            if isinstance(event, CallbackQuery):
                await event.answer()
                if event.message:
                    with suppress(TelegramBadRequest):
                        await event.message.delete()

            # Отправляем сообщение о подписке напрямую пользователю
            await bot.send_message(
                chat_id=user.id,
                text=text,
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True
            )
            logging.info(f"SubscriptionMiddleware: Sent subscription message to {user.id}")
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logging.error(f"SubscriptionMiddleware: FAILED to send message to {user.id}. Error: {e}")
        except Exception as e:
            logging.error(f"SubscriptionMiddleware: An unexpected error occurred while sending message to {user.id}: {e}")

        # Останавливаем дальнейшую обработку этого апдейта
        return


class BanMiddleware(BaseMiddleware):
    """
    Middleware для проверки, забанен ли пользователь.
    """
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        user = data.get('event_from_user')
        if not user:
            return await handler(event, data)

        db: Database = data['db']
        db_user = db.get_user(user.id)
        if db_user and db_user.get('is_banned'):
            logging.info(f"Banned user {user.id} tried to access.")
            text = (
                "🚫 <b>Вы были забанены.</b>\n\n"
                "Если вы считаете, что это ошибка, свяжитесь с разработчиком: "
                f"@{config.DEVELOPER_USERNAME}"
            )
            with suppress(TelegramBadRequest):
                if isinstance(event, Message):
                    await event.answer(text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
            return

        return await handler(event, data)


class GroupMemberMiddleware(BaseMiddleware):
    """
    Middleware для отслеживания пользователей в группах.
    """
    async def __call__(
            self,
            handler: Callable[[Union[Message, CallbackQuery], Dict[str, Any]], Awaitable[Any]],
            event: Union[Message, CallbackQuery],
            data: Dict[str, Any]
    ) -> Any:
        chat = None
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery):
            chat = event.message.chat if event.message else None

        if not chat or chat.type not in ('group', 'supergroup'):
            return await handler(event, data)

        user = data.get('event_from_user')
        if not user:
            return await handler(event, data)

        db: Database = data['db']
        db.add_or_update_chat(chat.id, chat.title)
        db.add_chat_member(chat.id, user.id)

        return await handler(event, data)

