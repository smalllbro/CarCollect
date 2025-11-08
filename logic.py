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

import json
import json
import random
import time
from typing import Dict, Any

from db import Database
import config

class GameLogic:
    #=== Игровая логика ===
    def __init__(self, db: Database):
        self.db = db
        self.cases = self._load_cases_data()

    def _load_cases_data(self) -> Dict[str, Any]:
        try:
            with open(config.CARS_DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Ошибка при загрузке {config.CARS_DATA_PATH}: {e}")
            return {}

    def open_case(self, user_id: int, case_name: str, use_cooldown: bool = True) -> Dict[str, Any]:
        if case_name not in self.cases:
            return {"status": "error", "message": "Кейс не найден."}

        if case_name == "free" and use_cooldown:
            self.db.check_and_update_pass_status(user_id)
            user = self.db.get_user(user_id)
            if not user:
                return {"status": "error", "message": "Пользователь не найден."}

            last_time = user.get('last_free_case', 0)
            now = int(time.time())
            
            has_pass = user.get('collect_pass_active', False)
            pass_activation_time = user.get('collect_pass_expires_at', 0) - config.COLLECT_PASS_DURATION
            
            is_pass_active_for_this_cooldown = has_pass and last_time >= pass_activation_time
            
            cooldown = config.FREE_CASE_COOLDOWN_PASS if is_pass_active_for_this_cooldown else config.FREE_CASE_COOLDOWN
            
            if now - last_time < cooldown:
                remaining_time = cooldown - (now - last_time)
                return {"status": "cooldown", "remaining": remaining_time}
            
            self.db.set_last_free_case_time(user_id)

        case_data = self.cases[case_name]
        
        rarity_chances = case_data.get("rarity_chances", {})
        if not rarity_chances or sum(rarity_chances.values()) != 100:
            return {"status": "error", "message": "Ошибка конфигурации кейса."}

        rarities = list(rarity_chances.keys())
        chances = list(rarity_chances.values())
        
        valid_rarities = [r for i, r in enumerate(rarities) if chances[i] > 0]
        valid_chances = [c for c in chances if c > 0]

        if not valid_rarities:
             return {"status": "error", "message": "В этом кейсе нет доступных редкостей."}

        chosen_rarity = random.choices(valid_rarities, weights=valid_chances, k=1)[0]
        
        cars_of_rarity = [car for car in case_data["cars"] if car["rarity"] == chosen_rarity]
        
        if not cars_of_rarity:
            return {"status": "error", "message": "Ошибка конфигурации: не найдены машины выпавшей редкости."}
        
        if len(cars_of_rarity) == 1:
            won_car = cars_of_rarity[0]
        else:
            total_value = sum(car['value'] for car in cars_of_rarity)
            weights = [total_value - car['value'] for car in cars_of_rarity]
            
            if all(w == 0 for w in weights):
                won_car = random.choice(cars_of_rarity)
            else:
                won_car = random.choices(cars_of_rarity, weights=weights, k=1)[0]
        
        self.db.add_car(
            user_id=user_id,
            name=won_car["name"],
            rarity=won_car["rarity"],
            value=won_car["value"],
            brand=won_car.get("brand", "Неизвестно"),
            season=won_car.get("season", "Неизвестно"),
            image_file_id=won_car.get("image_file_id")
        )
        
        return {"status": "success", "car": won_car}

    def craft_car(self, target_rarity: str) -> Dict[str, Any]:
        """Создает случайную машину указанной редкости."""
        # Мы предполагаем, что все машины всех редкостей есть в кейсе "free"
        case_data = self.cases.get("free", {})
        if not case_data:
            return {"status": "error", "message": "Конфигурация кейсов не найдена."}

        cars_of_rarity = [car for car in case_data.get("cars", []) if car.get("rarity") == target_rarity]
        
        if not cars_of_rarity:
            return {"status": "error", "message": f"Не найдены машины редкости {target_rarity} для крафта."}
        
        if len(cars_of_rarity) == 1:
            won_car = cars_of_rarity[0]
        else:
            # Используем ту же логику взвешенного шанса, что и при открытии кейса
            total_value = sum(car['value'] for car in cars_of_rarity)
            weights = [total_value - car['value'] for car in cars_of_rarity]
            
            if all(w == 0 for w in weights):
                won_car = random.choice(cars_of_rarity)
            else:
                won_car = random.choices(cars_of_rarity, weights=weights, k=1)[0]
        
        return {"status": "success", "car": won_car}
