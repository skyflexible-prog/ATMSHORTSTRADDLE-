import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Delta Exchange Configuration
DELTA_API_KEY = os.getenv('DELTA_API_KEY')
DELTA_API_SECRET = os.getenv('DELTA_API_SECRET')
DELTA_BASE_URL = 'https://api.india.delta.exchange'

# Server Configuration
HOST = '0.0.0.0'
PORT = int(os.getenv('PORT', 10000))
WEBHOOK_URL = os.getenv('WEBHOOK_URL', f'https://your-app-name.onrender.com')

# Trading Configuration
DEFAULT_LOT_SIZE = 1
STOP_LOSS_PREMIUM_PERCENTAGE = 25  # 25% premium increase for stop-loss
