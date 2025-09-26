import os
import logging
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP

import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from delta_rest_client import DeltaRestClient, OrderType
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask app for Render.com deployment
app = Flask(__name__)

@app.route('/')
def health_check():
    return {"status": "Bot is running", "timestamp": datetime.now().isoformat()}

class DeltaStraddleBot:
    def __init__(self):
        # Environment variables
        self.TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
        self.DELTA_API_KEY = os.getenv('DELTA_API_KEY')
        self.DELTA_API_SECRET = os.getenv('DELTA_API_SECRET')
        self.AUTHORIZED_USERS = os.getenv('AUTHORIZED_USERS', '').split(',')
        
        # Delta Exchange client
        self.delta_client = DeltaRestClient(
            base_url='https://api.india.delta.exchange',
            api_key=self.DELTA_API_KEY,
            api_secret=self.DELTA_API_SECRET
        )
        
        # Bot application
        self.application = Application.builder().token(self.TELEGRAM_TOKEN).build()
        self.setup_handlers()
        
        # Trading parameters
        self.lot_size = 1
        self.stop_loss_percentage = 25.0  # 25% premium increase
        
    def setup_handlers(self):
        """Setup command and callback handlers"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("btc_price", self.btc_price_command))
        self.application.add_handler(CommandHandler("straddle", self.straddle_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
    def is_authorized(self, user_id: str) -> bool:
        """Check if user is authorized"""
        return str(user_id) in self.AUTHORIZED_USERS
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        
        if not self.is_authorized(user_id):
            await update.message.reply_text("❌ Unauthorized access!")
            return
            
        welcome_message = """
🚀 **Delta Exchange BTC Short Straddle Bot**

Available commands:
/btc_price - Get current BTC spot price
/straddle - Execute short straddle strategy

⚠️ **Risk Warning**: Short straddle involves unlimited risk. Use with caution!
        """
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    
    async def btc_price_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get current BTC spot price"""
        user_id = update.effective_user.id
        
        if not self.is_authorized(user_id):
            await update.message.reply_text("❌ Unauthorized access!")
            return
            
        try:
            btc_ticker = self.delta_client.get_ticker('BTCUSD')
            spot_price = float(btc_ticker['mark_price'])
            
            message = f"""
💰 **BTC Spot Price**
Current Price: ${spot_price:,.2f}
Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error fetching BTC price: {e}")
            await update.message.reply_text("❌ Error fetching BTC price. Please try again.")
    
    def get_atm_strike(self, spot_price: float) -> int:
        """Calculate ATM strike price closest to spot"""
        # Round to nearest 500 for BTC options
        strike_interval = 500
        atm_strike = int(strike_interval * round(spot_price / strike_interval))
        return atm_strike
    
    def get_same_day_expiry_options(self, atm_strike: int) -> Tuple[Optional[str], Optional[str]]:
        """Get same day expiry call and put option symbols"""
        today = datetime.now()
        expiry_date = today.strftime('%d%m%y')
        
        ce_symbol = f'C-BTC-{atm_strike}-{expiry_date}'
        pe_symbol = f'P-BTC-{atm_strike}-{expiry_date}'
        
        # Verify options exist
        try:
            ce_ticker = self.delta_client.get_ticker(ce_symbol)
            pe_ticker = self.delta_client.get_ticker(pe_symbol)
            
            if ce_ticker and pe_ticker:
                return ce_symbol, pe_symbol
        except:
            pass
            
        return None, None
    
    def calculate_premium_and_stop_loss(self, ce_symbol: str, pe_symbol: str) -> Dict:
        """Calculate current premiums and stop-loss levels"""
        try:
            ce_ticker = self.delta_client.get_ticker(ce_symbol)
            pe_ticker = self.delta_client.get_ticker(pe_symbol)
            
            ce_premium = float(ce_ticker['mark_price'])
            pe_premium = float(pe_ticker['mark_price'])
            
            total_premium_received = ce_premium + pe_premium
            
            # Calculate 25% increase for stop-loss
            ce_stop_loss = ce_premium * (1 + self.stop_loss_percentage / 100)
            pe_stop_loss = pe_premium * (1 + self.stop_loss_percentage / 100)
            
            return {
                'ce_premium': ce_premium,
                'pe_premium': pe_premium,
                'total_premium': total_premium_received,
                'ce_stop_loss': ce_stop_loss,
                'pe_stop_loss': pe_stop_loss,
                'ce_product_id': ce_ticker['product_id'],
                'pe_product_id': pe_ticker['product_id']
            }
            
        except Exception as e:
            logger.error(f"Error calculating premiums: {e}")
            return None
    
    async def straddle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display straddle strategy options"""
        user_id = update.effective_user.id
        
        if not self.is_authorized(user_id):
            await update.message.reply_text("❌ Unauthorized access!")
            return
            
        try:
            # Get BTC spot price
            btc_ticker = self.delta_client.get_ticker('BTCUSD')
            spot_price = float(btc_ticker['mark_price'])
            
            # Calculate ATM strike
            atm_strike = self.get_atm_strike(spot_price)
            
            # Get option symbols
            ce_symbol, pe_symbol = self.get_same_day_expiry_options(atm_strike)
            
            if not ce_symbol or not pe_symbol:
                await update.message.reply_text("❌ No same-day expiry options available for current strike.")
                return
            
            # Calculate premiums
            premium_data = self.calculate_premium_and_stop_loss(ce_symbol, pe_symbol)
            
            if not premium_data:
                await update.message.reply_text("❌ Error calculating option premiums.")
                return
            
            # Create strategy details message
            strategy_message = f"""
🎯 **BTC Short Straddle Strategy**

**Market Data:**
BTC Spot: ${spot_price:,.2f}
ATM Strike: ${atm_strike:,}

**Options:**
Call (CE): {ce_symbol}
Put (PE): {pe_symbol}

**Premiums:**
CE Premium: ${premium_data['ce_premium']:.2f}
PE Premium: ${premium_data['pe_premium']:.2f}
**Total Premium: ${premium_data['total_premium']:.2f}**

**Stop Loss (25% increase):**
CE Stop: ${premium_data['ce_stop_loss']:.2f}
PE Stop: ${premium_data['pe_stop_loss']:.2f}

**Position Size:** {self.lot_size} lot each

⚠️ **Risk:** Unlimited beyond premium received
            """
            
            keyboard = [
                [InlineKeyboardButton("🚀 Execute Straddle", callback_data=f"execute_straddle:{atm_strike}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                strategy_message, 
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in straddle command: {e}")
            await update.message.reply_text("❌ Error setting up straddle strategy. Please try again.")
    
    async def execute_straddle_strategy(self, atm_strike: int, chat_id: int):
        """Execute the short straddle strategy with stop-loss orders"""
        try:
            # Get option symbols
            ce_symbol, pe_symbol = self.get_same_day_expiry_options(atm_strike)
            
            if not ce_symbol or not pe_symbol:
                return "❌ Options not available."
            
            # Calculate premiums and stop-loss levels
            premium_data = self.calculate_premium_and_stop_loss(ce_symbol, pe_symbol)
            
            if not premium_data:
                return "❌ Error calculating premiums."
                
            executed_orders = []
            
            # Execute CE sell order
            try:
                ce_order = self.delta_client.place_order(
                    product_id=premium_data['ce_product_id'],
                    side='sell',
                    size=self.lot_size,
                    limit_price=str(premium_data['ce_premium']),
                    order_type=OrderType.LIMIT
                )
                executed_orders.append(('CE_SELL', ce_order))
                logger.info(f"CE sell order placed: {ce_order}")
                
            except Exception as e:
                logger.error(f"Error placing CE sell order: {e}")
                return f"❌ Error placing CE sell order: {str(e)}"
            
            # Execute PE sell order
            try:
                pe_order = self.delta_client.place_order(
                    product_id=premium_data['pe_product_id'],
                    side='sell',
                    size=self.lot_size,
                    limit_price=str(premium_data['pe_premium']),
                    order_type=OrderType.LIMIT
                )
                executed_orders.append(('PE_SELL', pe_order))
                logger.info(f"PE sell order placed: {pe_order}")
                
            except Exception as e:
                logger.error(f"Error placing PE sell order: {e}")
                return f"❌ Error placing PE sell order: {str(e)}"
            
            # Wait a moment for orders to fill
            await asyncio.sleep(2)
            
            # Place stop-loss orders
            stop_loss_orders = []
            
            # CE stop-loss (buy back at higher price)
            try:
                ce_stop_order = self.delta_client.place_stop_order(
                    product_id=premium_data['ce_product_id'],
                    side='buy',
                    size=self.lot_size,
                    limit_price=str(premium_data['ce_stop_loss']),
                    order_type=OrderType.LIMIT,
                    stop_price=str(premium_data['ce_stop_loss'] * 0.99)  # Trigger slightly below limit
                )
                stop_loss_orders.append(('CE_STOP', ce_stop_order))
                logger.info(f"CE stop-loss placed: {ce_stop_order}")
                
            except Exception as e:
                logger.error(f"Error placing CE stop-loss: {e}")
            
            # PE stop-loss (buy back at higher price)
            try:
                pe_stop_order = self.delta_client.place_stop_order(
                    product_id=premium_data['pe_product_id'],
                    side='buy',
                    size=self.lot_size,
                    limit_price=str(premium_data['pe_stop_loss']),
                    order_type=OrderType.LIMIT,
                    stop_price=str(premium_data['pe_stop_loss'] * 0.99)  # Trigger slightly below limit
                )
                stop_loss_orders.append(('PE_STOP', pe_stop_order))
                logger.info(f"PE stop-loss placed: {pe_stop_order}")
                
            except Exception as e:
                logger.error(f"Error placing PE stop-loss: {e}")
            
            # Prepare success message
            success_message = f"""
✅ **Short Straddle Executed Successfully!**

**Sell Orders:**
CE Sell: Order ID {executed_orders[0][1].get('id', 'N/A')}
PE Sell: Order ID {executed_orders[1][1].get('id', 'N/A')}

**Stop-Loss Orders:**
CE Stop: {len([x for x in stop_loss_orders if x[0] == 'CE_STOP'])} placed
PE Stop: {len([x for x in stop_loss_orders if x[0] == 'PE_STOP'])} placed

**Premium Collected:** ${premium_data['total_premium']:.2f}
**ATM Strike:** ${atm_strike:,}

⚠️ Monitor positions closely!
            """
            
            return success_message
            
        except Exception as e:
            logger.error(f"Error executing straddle strategy: {e}")
            return f"❌ Error executing strategy: {str(e)}"
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if not self.is_authorized(user_id):
            await query.edit_message_text("❌ Unauthorized access!")
            return
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Operation cancelled.")
            return
        
        if query.data.startswith("execute_straddle:"):
            atm_strike = int(query.data.split(":")[1])
            
            await query.edit_message_text("⏳ Executing short straddle strategy...")
            
            result = await self.execute_straddle_strategy(atm_strike, query.message.chat_id)
            
            await query.edit_message_text(result, parse_mode='Markdown')
    
    async def start_bot(self):
        """Start the Telegram bot"""
        await self.application.initialize()
        await self.application.start()
        
        # Set webhook for production deployment
        webhook_url = os.getenv('WEBHOOK_URL')
        if webhook_url:
            await self.application.bot.set_webhook(webhook_url)
            logger.info(f"Webhook set to: {webhook_url}")
        else:
            # For local development, use polling
            await self.application.updater.start_polling()
            logger.info("Bot started with polling")

# Initialize bot
straddle_bot = DeltaStraddleBot()

# Flask route for webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle webhook updates"""
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), straddle_bot.application.bot)
        asyncio.run(straddle_bot.application.process_update(update))
    return "OK"

async def main():
    """Main function to run the bot"""
    try:
        await straddle_bot.start_bot()
        
        # Keep the bot running
        if not os.getenv('WEBHOOK_URL'):
            # Local development
            await straddle_bot.application.updater.idle()
        else:
            # Production deployment
            app.run(host='0.0.0.0', port=10000)
            
    except Exception as e:
        logger.error(f"Error starting bot: {e}")

if __name__ == "__main__":
    # For Render.com deployment
    if os.getenv('RENDER'):
        app.run(host='0.0.0.0', port=10000)
    else:
        # Local development
        asyncio.run(main())
