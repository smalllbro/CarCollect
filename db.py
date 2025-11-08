import psycopg2
from psycopg2.extras import DictCursor
import time
from typing import List, Dict, Any, Optional
import json

class Database:
    #=== Инициализация и настройка ===
    def __init__(self, db_params: Dict[str, Any]):
        try:
            self.conn = psycopg2.connect(**db_params)
            self.conn.autocommit = True
            print("Успешное подключение к PostgreSQL.")
            self.setup_database()
        except psycopg2.OperationalError as e:
            print(f"Ошибка подключения к PostgreSQL: {e}")
            raise

    def _execute(self, query: str, params: tuple = (), fetch: str = None) -> Any:
        with self.conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(query, params)
            if fetch == 'one':
                return cursor.fetchone()
            if fetch == 'all':
                return cursor.fetchall()
            if "RETURNING" in query.upper():
                return cursor.fetchone()
            return None

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        query = "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s"
        return self._execute(query, (table_name, column_name), fetch='one') is not None

    def setup_database(self):
        # Users Table
        self._execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            last_free_case BIGINT DEFAULT 0,
            last_dice_roll BIGINT DEFAULT 0, 
            last_coin_flip BIGINT DEFAULT 0,
            extra_attempts INTEGER DEFAULT 0, 
            tires INTEGER DEFAULT 0,
            is_banned BOOLEAN DEFAULT FALSE, 
            created_at BIGINT DEFAULT 0,
            nickname TEXT UNIQUE, 
            free_nick_changes INTEGER DEFAULT 3,
            referrer_id BIGINT, 
            referral_count INTEGER DEFAULT 0,
            collect_pass_active BOOLEAN DEFAULT FALSE,
            collect_pass_expires_at BIGINT DEFAULT 0,
            case_notification_sent BOOLEAN DEFAULT FALSE,
            last_case_notification BIGINT DEFAULT 0
        )
        ''')

        # Garage Table
        self._execute('''
        CREATE TABLE IF NOT EXISTS garage (
            car_id SERIAL PRIMARY KEY, 
            user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            car_name TEXT NOT NULL, 
            rarity TEXT NOT NULL, 
            value INTEGER NOT NULL,
            brand TEXT, 
            season TEXT, 
            image_file_id TEXT
        )
        ''')
        
        # Group Chats Table
        self._execute('''
        CREATE TABLE IF NOT EXISTS chats (
            chat_id BIGINT PRIMARY KEY,
            title TEXT,
            airdrops_enabled BOOLEAN DEFAULT FALSE,
            last_airdrop_time BIGINT DEFAULT 0,
            airdrop_cooldown_seconds INTEGER DEFAULT 14400
        )
        ''')

        # Airdrop Claims Table
        self._execute('''
        CREATE TABLE IF NOT EXISTS airdrop_claims (
            claim_id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL,
            claimed_by_user_id BIGINT,
            created_at BIGINT NOT NULL,
            UNIQUE(chat_id, message_id)
        )
        ''')

        # Chat Members Table (for leaderboards)
        self._execute('''
        CREATE TABLE IF NOT EXISTS chat_members (
            chat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            PRIMARY KEY (chat_id, user_id)
        )
        ''')

        # Other Tables (promo, transactions, etc.)
        self._execute('''
        CREATE TABLE IF NOT EXISTS promo_codes (
            code_id SERIAL PRIMARY KEY, 
            code_text TEXT UNIQUE NOT NULL, 
            reward_type TEXT NOT NULL,
            reward_value INTEGER, 
            reward_car_name TEXT, 
            max_activations INTEGER DEFAULT 1,
            current_activations INTEGER DEFAULT 0, 
            is_active BOOLEAN DEFAULT TRUE
        )
        ''')
        self._execute('''
        CREATE TABLE IF NOT EXISTS user_promo_activations (
            user_id BIGINT NOT NULL REFERENCES users(user_id), 
            code_id INTEGER NOT NULL REFERENCES promo_codes(code_id),
            PRIMARY KEY (user_id, code_id)
        )
        ''')
        self._execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY, 
            user_id BIGINT NOT NULL, 
            amount_stars INTEGER NOT NULL,
            currency TEXT NOT NULL, 
            payload TEXT NOT NULL, 
            created_at BIGINT NOT NULL,
            status TEXT DEFAULT 'completed'
        )
        ''')
        self._execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id SERIAL PRIMARY KEY, 
            user_id BIGINT NOT NULL REFERENCES users(user_id), 
            admin_id BIGINT,
            message_text TEXT NOT NULL, 
            status TEXT DEFAULT 'open', 
            created_at BIGINT NOT NULL,
            source TEXT DEFAULT 'general'
        )
        ''')
        self._execute('''
        CREATE TABLE IF NOT EXISTS tire_log (
            log_id SERIAL PRIMARY KEY, 
            user_id BIGINT NOT NULL REFERENCES users(user_id),
            change_amount INTEGER NOT NULL, 
            reason TEXT NOT NULL, 
            timestamp BIGINT NOT NULL
        )
        ''')
        self._execute('''
        CREATE TABLE IF NOT EXISTS trades (
            trade_id SERIAL PRIMARY KEY, 
            initiator_id BIGINT NOT NULL, 
            partner_id BIGINT NOT NULL,
            initiator_offer JSONB DEFAULT '[]'::jsonb, 
            partner_offer JSONB DEFAULT '[]'::jsonb,
            initiator_confirm BOOLEAN DEFAULT FALSE, 
            partner_confirm BOOLEAN DEFAULT FALSE,
            status TEXT DEFAULT 'pending', 
            created_at BIGINT NOT NULL,
            initiator_message_id BIGINT, 
            partner_message_id BIGINT
        )
        ''')
        
        # --- Проверка и обновление существующих таблиц ---
        if not self._column_exists('users', 'last_case_notification'):
            print("Обнаружено отсутствие колонки 'last_case_notification' в таблице 'users'. Добавляю...")
            self._execute("ALTER TABLE users ADD COLUMN last_case_notification BIGINT DEFAULT 0")
            print("Колонка 'last_case_notification' успешно добавлена.")
        
        if not self._column_exists('tickets', 'source'):
            self._execute("ALTER TABLE tickets ADD COLUMN source TEXT DEFAULT 'general'")

        if not self._column_exists('users', 'case_notification_sent'):
            self._execute("ALTER TABLE users ADD COLUMN case_notification_sent BOOLEAN DEFAULT FALSE")

        print("База данных PostgreSQL успешно настроена.")

    #=== Users ===
    def add_user(self, user_id: int, username: Optional[str], referrer_id: Optional[int] = None) -> bool:
        now = int(time.time())
        if self.get_user(user_id):
            return False
        default_nickname = str(user_id)
        if username and not self.get_user_by_nickname(username):
            default_nickname = username
        try:
            self._execute(
                "INSERT INTO users (user_id, created_at, nickname, referrer_id) VALUES (%s, %s, %s, %s)",
                (user_id, now, default_nickname, referrer_id)
            )
            if referrer_id and self.get_user(referrer_id):
                new_ref_count = self._execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = %s RETURNING referral_count", (referrer_id,))['referral_count']
                if new_ref_count > 0 and new_ref_count % 5 == 0:
                    self._execute("UPDATE users SET extra_attempts = extra_attempts + 5 WHERE user_id = %s", (referrer_id,))
            return True
        except psycopg2.errors.UniqueViolation:
            self._execute("INSERT INTO users (user_id, created_at, nickname, referrer_id) VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (user_id, now, str(user_id), referrer_id))
            return True
        except Exception as e:
            print(f"Ошибка при добавлении пользователя {user_id}: {e}")
            return False

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self._execute("SELECT * FROM users WHERE user_id = %s", (user_id,), fetch='one')
    
    def get_all_user_ids(self) -> List[int]:
        rows = self._execute("SELECT user_id FROM users WHERE is_banned = FALSE", fetch='all')
        return [row['user_id'] for row in rows]

    def set_ban_status(self, user_id: int, status: bool):
        self._execute("UPDATE users SET is_banned = %s WHERE user_id = %s", (status, user_id))

    def get_last_free_case_time(self, user_id: int) -> int:
        user = self.get_user(user_id)
        return user.get('last_free_case', 0) if user else 0

    def set_last_free_case_time(self, user_id: int):
        now = int(time.time())
        self._execute(
            "UPDATE users SET last_free_case = %s, case_notification_sent = FALSE, last_case_notification = 0 WHERE user_id = %s",
            (now, user_id)
        )
    
    def update_last_case_notification(self, user_id: int):
        """Обновляет время последнего уведомления о кейсе для пользователя."""
        now = int(time.time())
        self._execute(
            "UPDATE users SET last_case_notification = %s, case_notification_sent = TRUE WHERE user_id = %s",
            (now, user_id)
        )

    def is_nickname_taken(self, nickname: str) -> bool:
        return self._execute("SELECT 1 FROM users WHERE nickname = %s", (nickname,), fetch='one') is not None

    def change_nickname(self, user_id: int, new_nickname: str, is_free: bool):
        if is_free:
            self._execute(
                "UPDATE users SET nickname = %s, free_nick_changes = free_nick_changes - 1 WHERE user_id = %s",
                (new_nickname, user_id)
            )
        else:
            self._execute("UPDATE users SET nickname = %s WHERE user_id = %s", (new_nickname, user_id))

    def check_and_update_pass_status(self, user_id: int) -> bool:
        now = int(time.time())
        user = self.get_user(user_id)
        if not user: return False

        is_active = user.get('collect_pass_active', False)
        expires_at = user.get('collect_pass_expires_at', 0)

        if is_active and now > expires_at:
            self._execute("UPDATE users SET collect_pass_active = FALSE WHERE user_id = %s", (user_id,))
            return False
        return is_active

    def activate_collect_pass(self, user_id: int, duration_seconds: int):
        user = self.get_user(user_id)
        now = int(time.time())
        
        start_time = user['collect_pass_expires_at'] if user.get('collect_pass_active') and user.get('collect_pass_expires_at', 0) > now else now
        expires_at = start_time + duration_seconds
        
        self._execute(
            "UPDATE users SET collect_pass_active = TRUE, collect_pass_expires_at = %s WHERE user_id = %s",
            (expires_at, user_id)
        )

    def get_users_for_notification_check(self) -> List[Dict[str, Any]]:
        return self._execute(
            "SELECT user_id, last_free_case, collect_pass_active, collect_pass_expires_at, last_case_notification FROM users WHERE is_banned = FALSE",
            fetch='all'
        )

    def mark_case_notification_sent(self, user_id: int):
        self._execute("UPDATE users SET case_notification_sent = TRUE WHERE user_id = %s", (user_id,))

    #=== Minigames & Currency ===
    def add_extra_attempts(self, user_id: int, amount: int):
        self._execute(
            "UPDATE users SET extra_attempts = extra_attempts + %s WHERE user_id = %s",
            (amount, user_id)
        )

    def update_dice_roll(self, user_id: int, attempts_won: int):
        now = int(time.time())
        self._execute(
            "UPDATE users SET last_dice_roll = %s, extra_attempts = extra_attempts + %s WHERE user_id = %s",
            (now, attempts_won, user_id)
        )
    
    def set_last_coin_flip_time(self, user_id: int):
        now = int(time.time())
        self._execute("UPDATE users SET last_coin_flip = %s WHERE user_id = %s", (now, user_id))

    def change_tires(self, user_id: int, amount: int, reason: str):
        self._execute("UPDATE users SET tires = tires + %s WHERE user_id = %s", (amount, user_id))
        self._execute(
            "INSERT INTO tire_log (user_id, change_amount, reason, timestamp) VALUES (%s, %s, %s, %s)",
            (user_id, amount, reason, int(time.time()))
        )

    def use_extra_attempt(self, user_id: int):
        self._execute("UPDATE users SET extra_attempts = extra_attempts - 1 WHERE user_id = %s", (user_id,))

    def clear_extra_attempts(self, user_id: int):
        self._execute("UPDATE users SET extra_attempts = 0 WHERE user_id = %s", (user_id,))

    #=== Garage ===
    def add_car(self, user_id: int, name: str, rarity: str, value: int, brand: str, season: str, image_file_id: Optional[str] = None):
        self._execute(
            "INSERT INTO garage (user_id, car_name, rarity, value, brand, season, image_file_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, name, rarity, value, brand, season, image_file_id)
        )

    def get_filtered_garage(self, user_id: int, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        base_query = "SELECT car_name, rarity, value, brand, season, MAX(image_file_id) as image_file_id, COUNT(*) as count, MIN(car_id) as car_id FROM garage WHERE user_id = %s"
        params = [user_id]
        
        where_clauses = []
        if filters.get("rarity"):
            where_clauses.append("rarity = %s")
            params.append(filters["rarity"])
        if filters.get("brand"):
            where_clauses.append("brand = %s")
            params.append(filters["brand"])
        if filters.get("season"):
            where_clauses.append("season = %s")
            params.append(filters["season"])
        if filters.get("search_query"):
            where_clauses.append("car_name ILIKE %s")
            params.append(f"%{filters['search_query']}%")

        if where_clauses:
            base_query += " AND " + " AND ".join(where_clauses)

        base_query += " GROUP BY car_name, rarity, value, brand, season"

        if filters.get("duplicates"):
            base_query += " HAVING COUNT(*) > 1"

        rarity_order = "CASE rarity WHEN 'Common' THEN 1 WHEN 'Rare' THEN 2 WHEN 'Epic' THEN 3 WHEN 'Mythic' THEN 4 WHEN 'Legendary' THEN 5 ELSE 0 END"
        sort_map = {
            "name_asc": " ORDER BY car_name ASC", "name_desc": " ORDER BY car_name DESC",
            "value_asc": " ORDER BY value ASC, car_name ASC", "value_desc": " ORDER BY value DESC, car_name ASC",
            "rarity_asc": f" ORDER BY {rarity_order} ASC, car_name ASC",
            "rarity_desc": f" ORDER BY {rarity_order} DESC, car_name ASC"
        }
        order_clause = sort_map.get(filters.get("sort_by"), f" ORDER BY {rarity_order} DESC, car_name ASC")
        base_query += order_clause

        return self._execute(base_query, tuple(params), fetch='all')

    def get_user_distinct_values(self, user_id: int, column: str, **kwargs) -> List[str]:
        if column not in ["rarity", "brand", "season"]: return []
        query = f"SELECT DISTINCT {column} FROM garage WHERE user_id = %s AND {column} IS NOT NULL"
        params = [user_id]
        if kwargs.get('rarity'):
            query += " AND rarity = %s"
            params.append(kwargs['rarity'])
            
        query += f" ORDER BY {column}"
        rows = self._execute(query, tuple(params), fetch='all')
        return [row[column] for row in rows]

    def get_garage_count(self, user_id: int) -> int:
        result = self._execute("SELECT COUNT(*) as count FROM garage WHERE user_id = %s", (user_id,), fetch='one')
        return result['count'] if result else 0

    def get_collection_value(self, user_id: int) -> int:
        result = self._execute("SELECT SUM(value) as total_value FROM garage WHERE user_id = %s", (user_id,), fetch='one')
        return result['total_value'] if result and result['total_value'] is not None else 0
		
    def get_all_user_duplicates(self, user_id: int) -> List[Dict[str, Any]]:
        query = """
        SELECT car_id, car_name, rarity, value, brand, season, image_file_id
        FROM garage
        WHERE user_id = %s AND car_name IN (
            SELECT car_name FROM garage WHERE user_id = %s GROUP BY car_name HAVING COUNT(*) > 1
        )
        ORDER BY car_name
        """
        return self._execute(query, (user_id, user_id), fetch='all')

    def delete_cars_by_ids(self, car_ids: List[int]):
        if not car_ids:
            return
        safe_car_ids = [int(cid) for cid in car_ids]
        query = "DELETE FROM garage WHERE car_id = ANY(%s::int[])"
        self._execute(query, (safe_car_ids,))

    #=== Promo Codes ===
    def add_promo_code(self, code_text: str, reward_type: str, reward_value: Any, max_activations: int = 1) -> bool:
        code_text_upper = code_text.upper()
        try:
            params = (code_text_upper, reward_type, reward_value if reward_type == 'car' else int(reward_value), max_activations)
            query = f"""
            INSERT INTO promo_codes (code_text, reward_type, {'reward_car_name' if reward_type == 'car' else 'reward_value'}, max_activations, is_active) 
            VALUES (%s, %s, %s, %s, TRUE)
            """
            self._execute(query, params)
            return True
        except psycopg2.errors.UniqueViolation:
            return False
        except Exception as e:
            print(f"Error in add_promo_code: {e}")
            return False

    def edit_promo_code(self, code_text: str, reward_type: str, reward_value: Any, max_activations: int) -> bool:
        code_text_upper = code_text.upper()
        try:
            if reward_type == 'car':
                params = (reward_type, reward_value, max_activations, code_text_upper)
                query = "UPDATE promo_codes SET reward_type = %s, reward_car_name = %s, reward_value = NULL, max_activations = %s, current_activations = 0, is_active = TRUE WHERE code_text = %s"
            else:
                params = (reward_type, int(reward_value), max_activations, code_text_upper)
                query = "UPDATE promo_codes SET reward_type = %s, reward_value = %s, reward_car_name = NULL, max_activations = %s, current_activations = 0, is_active = TRUE WHERE code_text = %s"
            self._execute(query, params)
            return True
        except Exception as e:
            print(f"Error in edit_promo_code: {e}")
            return False

    def get_promo_by_text(self, code_text: str) -> Optional[Dict[str, Any]]:
        return self._execute("SELECT * FROM promo_codes WHERE code_text = %s", (code_text.upper(),), fetch='one')
    
    def get_all_promos(self) -> List[Dict[str, Any]]:
        return self._execute("SELECT * FROM promo_codes ORDER BY code_id DESC", fetch='all')

    def deactivate_promo(self, code_text: str) -> bool:
        self._execute("UPDATE promo_codes SET is_active = FALSE WHERE code_text = %s", (code_text.upper(),))
        return True

    def get_user_activation(self, user_id: int, code_id: int) -> Optional[Dict[str, Any]]:
        return self._execute("SELECT * FROM user_promo_activations WHERE user_id = %s AND code_id = %s", (user_id, code_id), fetch='one')

    def activate_promo_for_user(self, user_id: int, code_id: int):
        self._execute("INSERT INTO user_promo_activations (user_id, code_id) VALUES (%s, %s)", (user_id, code_id))
        self._execute("UPDATE promo_codes SET current_activations = current_activations + 1 WHERE code_id = %s", (code_id,))

    #=== Stats ===
    def get_total_users(self) -> int:
        return self._execute("SELECT COUNT(*) as count FROM users", fetch='one')['count']

    def get_new_users_count(self, hours: int = 24) -> int:
        timestamp = int(time.time()) - (hours * 3600)
        return self._execute("SELECT COUNT(*) as count FROM users WHERE created_at > %s", (timestamp,), fetch='one')['count']

    def get_total_cars_in_game(self) -> int:
        return self._execute("SELECT COUNT(*) as count FROM garage", fetch='one')['count']
    
    def get_total_tires(self) -> int:
        result = self._execute("SELECT SUM(tires) as total FROM users", fetch='one')
        return result['total'] if result and result['total'] is not None else 0

    def get_rarity_distribution(self) -> List[Dict[str, Any]]:
        query = "SELECT rarity, COUNT(*) as count FROM garage GROUP BY rarity"
        return self._execute(query, fetch='all')

    #=== Transactions, Tickets & Logs ===
    def log_transaction(self, t_id: str, user_id: int, amount: int, currency: str, payload: str):
        self._execute("INSERT INTO transactions (transaction_id, user_id, amount_stars, currency, payload, created_at, status) VALUES (%s, %s, %s, %s, %s, %s, %s)", (t_id, user_id, amount, currency, payload, int(time.time()), 'completed'))

    def get_transaction(self, t_id: str) -> Optional[Dict[str, Any]]:
        return self._execute("SELECT * FROM transactions WHERE transaction_id = %s", (t_id,), fetch='one')

    def update_transaction_status(self, t_id: str, status: str):
        self._execute("UPDATE transactions SET status = %s WHERE transaction_id = %s", (status, t_id))

    def create_ticket(self, user_id: int, text: str, source: str = 'general') -> int:
        return self._execute("INSERT INTO tickets (user_id, message_text, created_at, source) VALUES (%s, %s, %s, %s) RETURNING ticket_id", (user_id, text, int(time.time()), source))['ticket_id']

    def get_open_tickets(self) -> List[Dict[str, Any]]:
        return self._execute("SELECT * FROM tickets WHERE status = 'open' ORDER BY created_at ASC", fetch='all')

    def get_ticket(self, ticket_id: int) -> Optional[Dict[str, Any]]:
        return self._execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,), fetch='one')

    def update_ticket_status(self, ticket_id: int, status: str):
        self._execute("UPDATE tickets SET status = %s WHERE ticket_id = %s", (status, ticket_id))

    def request_ticket_close(self, ticket_id: int, admin_id: int):
        self._execute("UPDATE tickets SET status = 'pending_close', admin_id = %s WHERE ticket_id = %s", (admin_id, ticket_id))

    def get_tire_log_page(self, user_id: int, page: int = 0, limit: int = 5) -> List[Dict[str, Any]]:
        offset = page * limit
        return self._execute("SELECT * FROM tire_log WHERE user_id = %s ORDER BY timestamp DESC LIMIT %s OFFSET %s", (user_id, limit, offset), fetch='all')

    def get_tire_log_count(self, user_id: int) -> int:
        return self._execute("SELECT COUNT(*) as count FROM tire_log WHERE user_id = %s", (user_id,), fetch='one')['count']

    def get_user_transactions_page(self, user_id: int, page: int = 0, limit: int = 1) -> List[Dict[str, Any]]:
        offset = page * limit
        return self._execute("SELECT * FROM transactions WHERE user_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s", (user_id, limit, offset), fetch='all')

    def get_user_transactions_count(self, user_id: int) -> int:
        return self._execute("SELECT COUNT(*) as count FROM transactions WHERE user_id = %s", (user_id,), fetch='one')['count']

    #=== Trades ===
    def get_user_by_nickname(self, nickname: str) -> Optional[Dict[str, Any]]:
        return self._execute("SELECT * FROM users WHERE nickname = %s", (nickname,), fetch='one')

    def create_trade(self, initiator_id: int, partner_id: int) -> int:
        now = int(time.time())
        return self._execute("INSERT INTO trades (initiator_id, partner_id, created_at) VALUES (%s, %s, %s) RETURNING trade_id", (initiator_id, partner_id, now))['trade_id']

    def get_trade(self, trade_id: int) -> Optional[Dict[str, Any]]:
        return self._execute("SELECT * FROM trades WHERE trade_id = %s", (trade_id,), fetch='one')

    def update_trade_status(self, trade_id: int, status: str):
        self._execute("UPDATE trades SET status = %s WHERE trade_id = %s", (status, trade_id))

    def update_trade_message_id(self, trade_id: int, user_id: int, message_id: int):
        trade = self.get_trade(trade_id)
        if not trade: return
        user_role = "initiator" if trade['initiator_id'] == user_id else "partner"
        self._execute(f"UPDATE trades SET {user_role}_message_id = %s WHERE trade_id = %s", (message_id, trade_id))

    def update_trade_offer(self, trade_id: int, user_id: int, new_offer: List[int]):
        trade = self.get_trade(trade_id)
        if not trade: return
        user_role = "initiator" if trade['initiator_id'] == user_id else "partner"
        offer_json = json.dumps(new_offer)
        self._execute(f"UPDATE trades SET {user_role}_offer = %s, initiator_confirm = FALSE, partner_confirm = FALSE WHERE trade_id = %s", (offer_json, trade_id))

    def confirm_trade(self, trade_id: int, user_id: int):
        trade = self.get_trade(trade_id)
        if not trade: return
        user_role = "initiator" if trade['initiator_id'] == user_id else "partner"
        self._execute(f"UPDATE trades SET {user_role}_confirm = TRUE WHERE trade_id = %s", (trade_id,))

    def get_car_by_id(self, car_id: int) -> Optional[Dict[str, Any]]:
        return self._execute("SELECT * FROM garage WHERE car_id = %s", (car_id,), fetch='one')

    def get_car_name_by_id(self, car_id: int) -> Optional[str]:
        result = self._execute("SELECT car_name FROM garage WHERE car_id = %s", (car_id,), fetch='one')
        return result['car_name'] if result else None

    def get_all_user_cars_by_name(self, user_id: int, car_name: str) -> List[Dict[str, Any]]:
        return self._execute(
            "SELECT car_id FROM garage WHERE user_id = %s AND car_name = %s ORDER BY car_id",
            (user_id, car_name),
            fetch='all'
        )

    def get_cars_by_ids(self, car_ids: List[int]) -> List[Dict[str, Any]]:
        if not car_ids: return []
        query = "SELECT car_id, car_name, rarity, value FROM garage WHERE car_id = ANY(%s)"
        return self._execute(query, (car_ids,), fetch='all')

    def _lock_and_get_cars_for_trade(self, cursor, car_ids: List[int]) -> List[Dict[str, Any]]:
        if not car_ids: return []
        query = "SELECT car_id, user_id FROM garage WHERE car_id = ANY(%s) FOR UPDATE"
        cursor.execute(query, (car_ids,))
        locked_cars = cursor.fetchall()
        if len(locked_cars) != len(set(car_ids)):
            raise Exception("Одна или несколько машин в предложении не найдены.")
        return locked_cars

    def execute_trade(self, trade_id: int) -> bool:
        trade = self.get_trade(trade_id)
        if not trade: return False
        
        with self.conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                cursor.execute("BEGIN;")

                initiator_id, partner_id = trade['initiator_id'], trade['partner_id']
                initiator_offer, partner_offer = trade['initiator_offer'], trade['partner_offer']
                all_car_ids = initiator_offer + partner_offer

                if not all_car_ids:
                    raise Exception("Нельзя провести пустой обмен.")

                locked_cars = self._lock_and_get_cars_for_trade(cursor, all_car_ids)
                
                for car in locked_cars:
                    car_id, owner_id = car['car_id'], car['user_id']
                    if car_id in initiator_offer and owner_id != initiator_id:
                        raise Exception(f"Инициатор {initiator_id} не владеет машиной {car_id}.")
                    if car_id in partner_offer and owner_id != partner_id:
                        raise Exception(f"Партнер {partner_id} не владеет машиной {car_id}.")

                if initiator_offer:
                    cursor.execute("UPDATE garage SET user_id = %s WHERE car_id = ANY(%s)", (partner_id, initiator_offer))
                if partner_offer:
                    cursor.execute("UPDATE garage SET user_id = %s WHERE car_id = ANY(%s)", (initiator_id, partner_offer))
                
                cursor.execute("UPDATE trades SET status = 'completed' WHERE trade_id = %s", (trade_id,))
                
                self.conn.commit()
                return True
            except Exception as e:
                self.conn.rollback()
                print(f"ОШИБКА ОБМЕНА #{trade_id}: {e}")
                self.update_trade_status(trade_id, 'failed')
                return False

    #=== Group Chats & Airdrops ===
    def add_or_update_chat(self, chat_id: int, title: str):
        self._execute(
            "INSERT INTO chats (chat_id, title) VALUES (%s, %s) ON CONFLICT (chat_id) DO UPDATE SET title = %s",
            (chat_id, title, title)
        )

    def add_chat_member(self, chat_id: int, user_id: int):
        self._execute("INSERT INTO chat_members (chat_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (chat_id, user_id))

    def get_group_leaderboard(self, chat_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        query = """
        SELECT u.nickname, SUM(g.value) as total_value
        FROM garage g
        JOIN users u ON g.user_id = u.user_id
        WHERE g.user_id IN (SELECT user_id FROM chat_members WHERE chat_id = %s)
        GROUP BY u.nickname
        ORDER BY total_value DESC
        LIMIT %s
        """
        return self._execute(query, (chat_id, limit), fetch='all')

    def update_airdrop_settings(self, chat_id: int, enabled: bool, cooldown_seconds: Optional[int] = None):
        if cooldown_seconds is not None:
            self._execute("UPDATE chats SET airdrops_enabled = %s, airdrop_cooldown_seconds = %s WHERE chat_id = %s", (enabled, cooldown_seconds, chat_id))
        else:
            self._execute("UPDATE chats SET airdrops_enabled = %s WHERE chat_id = %s", (enabled, chat_id))

    def get_chats_for_airdrop(self) -> List[Dict[str, Any]]:
        return self._execute("SELECT * FROM chats WHERE airdrops_enabled = TRUE", fetch='all')

    def create_airdrop(self, chat_id: int, message_id: int) -> int:
        now = int(time.time())
        self._execute("UPDATE chats SET last_airdrop_time = %s WHERE chat_id = %s", (now, chat_id))
        result = self._execute("INSERT INTO airdrop_claims (chat_id, message_id, created_at) VALUES (%s, %s, %s) RETURNING claim_id", (chat_id, message_id, now))
        return result['claim_id']

    def claim_airdrop(self, claim_id: int, user_id: int) -> bool:
        query = """
        UPDATE airdrop_claims
        SET claimed_by_user_id = %s
        WHERE claim_id = %s AND claimed_by_user_id IS NULL
        RETURNING claim_id
        """
        result = self._execute(query, (user_id, claim_id), fetch='one')
        return result is not None
