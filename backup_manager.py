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
import time
import subprocess
from datetime import datetime

# Импортируем конфигурацию напрямую, так как это отдельный скрипт
import config

def create_backup():
    """
    Создает резервную копию базы данных PostgreSQL с помощью pg_dump.
    Возвращает кортеж (успех: bool, сообщение_или_путь_к_файлу: str).
    """
    db_config = config.DB_CONFIG
    backup_dir = config.BACKUP_PATH

    # Убедимся, что директория для бэкапов существует
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    # Формируем имя файла с датой и временем
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = os.path.join(backup_dir, f"backup_{db_config['dbname']}_{timestamp}.sql")

    # Формируем команду для pg_dump
    # Устанавливаем переменную окружения с паролем, чтобы не вводить его в консоли
    pg_password = db_config.get("password")
    env = os.environ.copy()
    if pg_password:
        env["PGPASSWORD"] = pg_password

    command = [
        "pg_dump",
        "-h", db_config["host"],
        "-p", db_config["port"],
        "-U", db_config["user"],
        "-d", db_config["dbname"],
        "-f", backup_file,
        "--clean", # Добавляет команды DROP перед созданием объектов
        "--if-exists" # Не выдает ошибку, если объект уже существует
    ]

    try:
        # Запускаем процесс
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            return True, backup_file
        else:
            # Если pg_dump вернул ошибку, читаем stderr
            error_message = stderr.decode("utf-8").strip()
            return False, f"Ошибка при создании бэкапа: {error_message}"

    except FileNotFoundError:
        return False, "Ошибка: утилита 'pg_dump' не найдена. Убедитесь, что PostgreSQL установлен на сервере."
    except Exception as e:
        return False, f"Непредвиденная ошибка: {e}"

if __name__ == "__main__":
    # Этот блок позволяет запускать скрипт напрямую из консоли
    print("Запускаю создание резервной копии...")
    success, message = create_backup()
    if success:
        print(f"✅ Бэкап успешно создан: {message}")
    else:
        print(f"❌ {message}")
