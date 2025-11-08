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

from aiogram.fsm.state import State, StatesGroup

# --- FSM для состояний ---
class Form(StatesGroup):
    """
    Класс для хранения состояний FSM (Finite State Machine).
    Используется для управления многошаговыми диалогами с пользователем.
    """
    # Состояния поддержки
    writing_ticket = State()
    admin_reply_to_ticket = State()

    # Состояния профиля
    changing_nickname = State()

    # Состояния администрирования
    admin_context = State()

    # Состояния гаража
    garage_view = State()
    garage_search = State()

    # Состояния обмена
    trade_enter_nickname = State()
    trade_add_car = State()

    # Зарезервированное состояние для будущей механики
    crafting = State()
