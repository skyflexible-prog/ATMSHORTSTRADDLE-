import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from delta_client import DeltaExchangeClient
from config import BOT_TOKEN, DEFAULT_LOT_SIZE

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.delta_client = DeltaExchangeClient()
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup command and callback handlers"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("orders", self.show_orders))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        keyboard = [
            [InlineKeyboardButton("📊 Execute Short Straddle", callback_data='execute_straddle')],
            [InlineKeyboardButton("📋 View Open Orders", callback_data='view_orders')],
            [InlineKeyboardButton("💹 Check BTC Price", callback_data='btc_price')],
            [InlineKeyboardButton("ℹ️ Strategy Info", callback_data='strategy_info')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = (
            "🤖 **Delta Exchange Short Straddle Bot**\n\n"
            "This bot executes short straddle strategies on BTC same-day expiry options.\n\n"
            "**Features:**\n"
            "✅ Automatic ATM strike selection\n"
            "✅ Same-day expiry options\n"
            "✅ 25% premium stop-loss orders\n"
            "✅ 1 lot size per option\n\n"
            "Click the buttons below to get started:"
        )
        
        await update.message.reply_text(
            welcome_text, 
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check system status"""
        try:
            spot_price = self.delta_client.get_btc_spot_price()
            status_text = f"🟢 **System Status: Active**\n\n📈 BTC Spot Price: ${spot_price:,.2f}"
            await update.message.reply_text(status_text, parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ System Error: {str(e)}")
    
    async def show_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show open orders"""
        try:
            orders_response = self.delta_client.get_open_orders()
            if orders_response.get('success') and orders_response.get('result'):
                orders = orders_response['result']
                if orders:
                    orders_text = "📋 **Open Orders:**\n\n"
                    for order in orders[:10]:  # Show max 10 orders
                        orders_text += (
                            f"🔸 **ID:** {order['id']}\n"
                            f"   **Side:** {order['side'].upper()}\n"
                            f"   **Size:** {order['size']}\n"
                            f"   **Price:** ${float(order.get('limit_price', 0)):,.2f}\n\n"
                        )
                else:
                    orders_text = "📋 No open orders found."
            else:
                orders_text = "❌ Failed to fetch orders."
                
            await update.message.reply_text(orders_text, parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ Error fetching orders: {str(e)}")
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        if query.data == 'execute_straddle':
            await self.execute_straddle_callback(query)
        elif query.data == 'view_orders':
            await self.view_orders_callback(query)
        elif query.data == 'btc_price':
            await self.btc_price_callback(query)
        elif query.data == 'strategy_info':
            await self.strategy_info_callback(query)
        elif query.data == 'confirm_execute':
            await self.confirm_execute_callback(query)
    
    async def execute_straddle_callback(self, query):
        """Handle execute straddle button"""
        keyboard = [
            [InlineKeyboardButton("✅ Confirm Execute", callback_data='confirm_execute')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        confirmation_text = (
            "⚠️ **Confirm Short Straddle Execution**\n\n"
            "This will:\n"
            "• Sell 1 lot ATM BTC Call Option\n"
            "• Sell 1 lot ATM BTC Put Option\n"
            "• Place 25% premium stop-loss orders\n"
            "• Use same-day expiry options\n\n"
            "**Warning:** Options trading involves significant risk!"
        )
        
        await query.edit_message_text(
            confirmation_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def confirm_execute_callback(self, query):
        """Execute the short straddle strategy"""
        await query.edit_message_text("🔄 Executing short straddle strategy...")
        
        try:
            result = self.delta_client.execute_short_straddle(DEFAULT_LOT_SIZE)
            
            if result.get('success'):
                success_text = (
                    f"✅ **Short Straddle Executed Successfully!**\n\n"
                    f"📈 **BTC Spot Price:** ${result['spot_price']:,.2f}\n"
                    f"🎯 **Strike Price:** ${result['strike_price']:,.2f}\n\n"
                    f"**Orders Placed:**\n"
                )
                
                for order in result['orders']:
                    if order['type'] == 'short_call':
                        success_text += f"🔸 Short Call: ID {order['order_id']} @ ${order['price']:,.2f}\n"
                    elif order['type'] == 'short_put':
                        success_text += f"🔸 Short Put: ID {order['order_id']} @ ${order['price']:,.2f}\n"
                    elif order['type'] == 'call_stop_loss':
                        success_text += f"🛑 Call Stop-Loss: ID {order['order_id']} @ ${order['stop_price']:,.2f}\n"
                    elif order['type'] == 'put_stop_loss':
                        success_text += f"🛑 Put Stop-Loss: ID {order['order_id']} @ ${order['stop_price']:,.2f}\n"
                
                await query.edit_message_text(success_text, parse_mode='Markdown')
            else:
                error_text = f"❌ **Execution Failed**\n\n{result.get('error', 'Unknown error')}"
                await query.edit_message_text(error_text, parse_mode='Markdown')
                
        except Exception as e:
            await query.edit_message_text(f"❌ **Error:** {str(e)}")
    
    async def view_orders_callback(self, query):
        """View open orders callback"""
        try:
            orders_response = self.delta_client.get_open_orders()
            if orders_response.get('success') and orders_response.get('result'):
                orders = orders_response['result']
                if orders:
                    orders_text = "📋 **Open Orders:**\n\n"
                    for order in orders[:5]:  # Show max 5 orders
                        orders_text += (
                            f"🔸 **ID:** {order['id']}\n"
                            f"   **Side:** {order['side'].upper()}\n"
                            f"   **Size:** {order['size']}\n"
                            f"   **Price:** ${float(order.get('limit_price', 0)):,.2f}\n\n"
                        )
                else:
                    orders_text = "📋 No open orders found."
            else:
                orders_text = "❌ Failed to fetch orders."
                
            await query.edit_message_text(orders_text, parse_mode='Markdown')
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def btc_price_callback(self, query):
        """Check BTC price callback"""
        try:
            spot_price = self.delta_client.get_btc_spot_price()
            price_text = f"💰 **BTC Spot Price**\n\n${spot_price:,.2f}"
            await query.edit_message_text(price_text, parse_mode='Markdown')
        except Exception as e:
            await query.edit_message_text(f"❌ Error fetching price: {str(e)}")
    
    async def strategy_info_callback(self, query):
        """Show strategy information"""
        info_text = (
            "📊 **Short Straddle Strategy**\n\n"
            "**What it does:**\n"
            "• Sells ATM Call and Put options\n"
            "• Profits from time decay and low volatility\n"
            "• Uses same-day expiry for maximum theta\n\n"
            "**Risk Management:**\n"
            "• Automatic 25% premium stop-loss\n"
            "• Limited profit, unlimited risk\n"
            "• Best in low volatility environments\n\n"
            "**Parameters:**\n"
            "• 1 lot each for CE and PE\n"
            "• ATM strikes near spot price\n"
            "• Same-day expiry options only"
        )
        await query.edit_message_text(info_text, parse_mode='Markdown')
