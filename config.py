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

import os
from dotenv import load_dotenv

load_dotenv()

#=== Основные настройки ===
BOT_TOKEN = os.getenv("token")
if not BOT_TOKEN:
    raise ValueError("Токен не найден! Убедитесь, что вы создали .env файл и указали в нем 'token=\"ВАШ_ТОКЕН\"'")
    
ADMIN_IDS = []
TESTER_IDS = []
DEVELOPER_USERNAME = "ник разраба"
CHANNEL_ID = "@carcollect_channel"
# --- РЕЖИМ ТЕСТИРОВАНИЯ ---
# Если True, ботом смогут пользоваться только админы из списка ADMIN_IDS и TESTER_IDS
# Не забудьте поставить False перед запуском для всех!
TEST_MODE = False

#=== Настройки базы данных PostgreSQL ===
DB_CONFIG = {
    "host": "localhost",
    "port": "5432",
    "user": os.getenv("serverusername"),
    "password": os.getenv("serverpassword"),
    "dbname": "carbot_db"
}

#=== Пути к файлам ===
DB_NAME = "carbot.db" 
CARS_DATA_PATH = "data/cars.json"
IMAGES_PATH = "images/"
BACKUP_PATH = "backups/" 

#=== Настройки игровых механик ===
FREE_CASE_COOLDOWN = 10800
DICE_COOLDOWN = 604800
COIN_FLIP_COOLDOWN = 72000
CASE_NOTIFIER_INTERVAL = 300
CASE_REMINDER_INTERVAL = 21600  # 6 часов
DEFAULT_AIRDROP_COOLDOWN = 14400
AIRDROP_NOTIFIER_INTERVAL = 60
AIRDROP_CASE_NAME = "free"

#=== Магазин ===
ATTEMPT_PACKS = {
    "attempts_1":   {"attempts": 1,   "cost": 4},
    "attempts_5":   {"attempts": 5,   "cost": 18},
    "attempts_10":  {"attempts": 10,  "cost": 34},
    "attempts_25":  {"attempts": 25,  "cost": 80},
    "attempts_50":  {"attempts": 50,  "cost": 150},
    "attempts_100": {"attempts": 100, "cost": 280}
}

TIRE_PACKS = {
    "tires_5": {"title": "Пара покрышек", "stars": 5, "tires": 7},
    "tires_10": {"title": "Горстка покрышек", "stars": 10, "tires": 15},
    "tires_25": {"title": "Небольшой запас", "stars": 25, "tires": 40},
    "tires_50": {"title": "Мешок покрышек", "stars": 50, "tires": 85},
    "tires_100": {"title": "Гора покрышек", "stars": 100, "tires": 200},
    "tires_250": {"title": "Контейнер покрышек", "stars": 250, "tires": 550},
    "tires_500": {"title": "Склад покрышек", "stars": 500, "tires": 1250}
}

#=== Стили редкости ===
RARITY_STYLES = {
    "Common":    {"color": "🔵", "name": "Common"},
    "Rare":      {"color": "🟢", "name": "Rare"},
    "Epic":      {"color": "🟣", "name": "Epic"},
    "Mythic":    {"color": "🔴", "name": "Mythic"},
    "Legendary": {"color": "🟡", "name": "Legendary"}
}

#=== Рецепты крафта ===
CRAFT_RECIPES = {
    "Common":    {"cost": 11, "result": "Rare"},
    "Rare":      {"cost": 9,  "result": "Epic"},
    "Epic":      {"cost": 7,  "result": "Mythic"},
    "Mythic":    {"cost": 6,  "result": "Legendary"}
}

#=== Collect Pass ===
COLLECT_PASS_COST = 100
COLLECT_PASS_DURATION = 30 * 86400 
NICK_CHANGE_COST = 3
COLLECT_PASS_NICK_CHANGE_COST = 1
ATTEMPTS_DISCOUNT_PERCENT = 10 
DEFAULT_TRADE_LIMIT = 5
COLLECT_PASS_TRADE_LIMIT = 10

#--- Кулдауны с активной подпиской CollectPass ---
FREE_CASE_COOLDOWN_PASS = 7200
DICE_COOLDOWN_PASS = DICE_COOLDOWN // 2              # 3.5 дня
COIN_FLIP_COOLDOWN_PASS = COIN_FLIP_COOLDOWN // 2    # 10 часов

