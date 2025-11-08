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
import os
import json
from aiogram import Bot
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramBadRequest

# --- НАСТРОЙКИ ---
# Вставьте сюда токен вашего бота из config.py
BOT_TOKEN = "токен" 
# Вставьте сюда ID чата, куда бот будет загружать фото.
# Это может быть ID вашего личного чата с ботом или ID закрытого канала.
# Чтобы узнать свой ID, можно написать боту @userinfobot
TARGET_CHAT_ID = "айди" 
# Пути к файлам (должны совпадать с config.py)
CARS_DATA_PATH = "data/cars.json"
IMAGES_PATH = "images/"
# --- КОНЕЦ НАСТРОЕК ---


async def upload_images_and_get_file_ids():
    """
    Этот скрипт автоматизирует процесс загрузки изображений машин в Telegram,
    получения их file_id и сохранения этих ID в файл cars.json.
    """
    # Проверка базовых настроек
    if BOT_TOKEN == "ВАШ_ТОКЕН_СЮДА" or TARGET_CHAT_ID == 0:
        print("❌ Ошибка: Пожалуйста, укажите ваши BOT_TOKEN и TARGET_CHAT_ID в настройках скрипта.")
        return

    bot = Bot(token=BOT_TOKEN)
    print("Бот инициализирован.")

    try:
        with open(CARS_DATA_PATH, 'r', encoding='utf-8') as f:
            cases_data = json.load(f)
        print(f"Файл {CARS_DATA_PATH} успешно загружен.")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ Ошибка: Не удалось прочитать файл {CARS_DATA_PATH}. Убедитесь, что он существует и корректен. {e}")
        return

    all_cars = []
    for case_name, case_content in cases_data.items():
        if "cars" in case_content and isinstance(case_content["cars"], list):
            all_cars.extend(case_content["cars"])
    
    if not all_cars:
        print("⚠️ В файле cars.json не найдено ни одной машины для обработки. Завершение работы.")
        return
        
    print(f"Найдено всего {len(all_cars)} машин в {CARS_DATA_PATH}.")

    updated_count = 0
    skipped_existing_id = 0
    skipped_missing_file = 0

    for car in all_cars:
        car_name = car.get("name")
        if not car_name:
            continue

        if car.get("image_file_id"):
            skipped_existing_id += 1
            continue
            
        image_name = f"{car_name.lower().replace(' ', '_')}.jpg"
        image_path = os.path.join(IMAGES_PATH, image_name)

        if not os.path.exists(image_path):
            print(f"⚠️ Файл не найден: {image_path} для машины '{car_name}'. Пропускаем.")
            skipped_missing_file += 1
            continue

        try:
            print(f"⏳ Загружаем фото для '{car_name}'...")
            photo_to_send = FSInputFile(image_path)
            message = await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=photo_to_send)
            
            if message.photo:
                file_id = message.photo[-1].file_id
                car["image_file_id"] = file_id
                updated_count += 1
                print(f"✅ Успешно! '{car_name}' -> file_id: {file_id[:20]}...")
            else:
                print(f"❌ Не удалось получить photo object для '{car_name}'.")

            await asyncio.sleep(1)

        except TelegramBadRequest as e:
            print(f"❌ Ошибка Telegram при отправке фото для '{car_name}': {e}")
            print("   Возможные причины: неверный TARGET_CHAT_ID или бот не имеет прав на отправку фото в этот чат.")
        except Exception as e:
            print(f"❌ Непредвиденная ошибка при обработке '{car_name}': {e}")

    # Финальный отчет
    print("\n--- Отчет о работе скрипта ---")
    if updated_count > 0:
        try:
            with open(CARS_DATA_PATH, 'w', encoding='utf-8') as f:
                json.dump(cases_data, f, ensure_ascii=False, indent=4)
            print(f"🎉 Успешно обновлено: {updated_count} машин.")
            print(f"   Файл {CARS_DATA_PATH} сохранен.")
        except Exception as e:
            print(f"❌ Критическая ошибка: Не удалось сохранить обновленные данные в {CARS_DATA_PATH}. {e}")
    else:
        print("ℹ️ Новых file_id не было добавлено.")

    if skipped_existing_id > 0:
        print(f"   Пропущено (уже был file_id): {skipped_existing_id} машин.")
    if skipped_missing_file > 0:
        print(f"   Пропущено (не найден файл изображения): {skipped_missing_file} машин.")
    print("---------------------------------")


    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(upload_images_and_get_file_ids())

