
# CarCollect

CarCollect is a multiplayer Telegram bot for collecting virtual car cards. The bot is implemented in Python using the aiogram 3.x framework and PostgreSQL as a database. The project includes mechanics for obtaining cars from 'cases', a developed economy, player-to-player trading, a crafting system, mini-games, and an advanced admin panel.

**_Note:_** _The bot doesn't work very well in groups, but airdrops and a shared database (between private messages and groups) are available and work properly._

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes. See deployment for notes on how to deploy the project on a live system.

### Prerequisites

You will need:

 - Python 3.10+
 - PostgreSQL Server
 - Git
 - Python packages: `aiogram`, `psycopg2-binary`, `python-dotenv`

To install the Python packages, please run:
```
pip install aiogram psycopg2-binary python-dotenv
```
### Installing

A step by step series of examples that tell you how to get a development env running.

1. Clone the repository

```
git clone [https://github.com/smalllbro/CarCollect.git](https://github.com/smalllbro/CarCollect.git)
cd CarCollect
```

2. Create and activate a virtual environment
```
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies

(See Prerequisites section above)

4. Set up the PostgreSQL database

Log into psql (e.g., sudo -u postgres psql) and create a dedicated user and database:
```
CREATE USER car_user WITH PASSWORD 'your_strong_password';
CREATE DATABASE carbot_db;
ALTER DATABASE carbot_db OWNER TO car_user;
\q
```

5. Create the .env configuration file

Create a .env file in the root directory and add your credentials:
```
# Token from @BotFather
token="123456:ABC-DEF1234567890"

# Credentials from step 4
serverusername="car_user"
serverpassword="your_strong_password"
```

6. Configure `config.py`

- Set your Telegram ID in ADMIN_IDS.

- Set your channel ID in CHANNEL_ID.

- Ensure DB_CONFIG matches your settings (it's configured to read from .env).

7. Run the bot

The bot will automatically create all necessary tables on its first run.
```
python3 main.py
```


## Deployment

For a stable deployment, it is recommended to run the bot in the background using nohup (or its equivalents, for example Start-Process on Windows)

```
# Be sure to use the full path to the python interpreter from your virtual environment
nohup /path/to/project/CarCollect/venv/bin/python3 main.py &
```


## Documentation

### Image file_id Pre-population
**_This is a mandatory step for the bot to display images correctly._**

The bot uses Telegram's file_id to send car images, which is much faster than uploading the file every time. The get-file_id.py script automates this process.

1. Add all your car images (e.g., `ford_focus.jpg`) to the `images/` directory.

2. Ensure all car entries are correctly listed in `data/cars.json` with their names matching the image file names.

3. Open `get-file_id.py` and set your `BOT_TOKEN` and a `TARGET_CHAT_ID` (this can be your personal chat ID with the bot or a private channel ID).

4. Run the script:
```
python3 get-file_id.py
```
5. The script will upload every new image from images/ to your TARGET_CHAT_ID, retrieve its file_id, and automatically update the data/cars.json file.

### Key Commands

#### 🔐 Admin Commands

`/give [USER_ID] [type] [amount]` — Grant a resource (types: tires, extra_attempts).

`/give [USER_ID] car "Car Name" [amount]` — Grant one or more cars.

`/addpromo [CODE] [type] [value]` — Create a promo code.

`/check [USER_ID]` — Check a player's profile, balance, and history.

`/stats` — View global bot statistics.

`/tickets` — Show a list of open support tickets.

`/backup` — Create a backup of the database.

`/broadcast [TEXT]` — Send a message to all users.

`/ban [USER_ID]` / `unban [USER_ID]` — Manage user bans.

`/refund [USER_ID] [transaction_id]` — Refund a Telegram Stars purchase.

#### 👥 Group Chat Commands

`/enable_airdrops [hours]` — Enable Airdrops in the chat. (for bot admins)

`/disable_airdrops` — Disable Airdrops. (for bot admins)
## Built with
- [aiogram 3.x](https://github.com/aiogram/aiogram) - The asynchronous framework for the Telegram Bot API

- [PostgreSQL](https://www.postgresql.org/) - Database

- [psycopg2](https://www.psycopg.org/docs/) - PostgreSQL driver for Python

- [python-dotenv](https://github.com/theskumar/python-dotenv) - Environment variable management

## Authors

- [@smalllbro](https://www.github.com/smallbro)


## License

This project is licensed under the GNU General Public License v3.0 (GPL-3.0) - see the [LICENSE](https://github.com/smalllbro/CarCollect/blob/main/LICENSE) file for details.

