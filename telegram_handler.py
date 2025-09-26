import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import TelegramError
from delta_client import DeltaExchangeClient
from config import BOT_TOKEN, DEFAULT_LOT_SIZE

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by Updates."""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Try to notify user about the error if possible
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ An error occurred while processing your request. Please try again."
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")

class TelegramBot:
    def __init__(self):
        self.delta_client = DeltaExchangeClient()
        
        # Build application for webhook mode (without updater)
        self.application = (
            Application.builder()
            .token(BOT_TOKEN)
            .updater(None)  # Disable updater for webhook mode
            .read_timeout(7)
            .write_timeout(7)
            .get_updates_read_timeout(42)
            .build()
        )
        
        self.setup_handlers()
        logger.info("TelegramBot initialized successfully")
    
    def setup_handlers(self):
        """Setup command and callback handlers"""
        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("positions", self.show_positions))
        self.application.add_handler(CommandHandler("brackets", self.show_bracket_orders))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Add callback query handler
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Add error handler
        self.application.add_error_handler(error_handler)
        
        logger.info("All handlers registered successfully")
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        try:
            user = update.effective_user
            logger.info(f"Start command from user {user.id} ({user.username})")
            
            keyboard = [
                [InlineKeyboardButton("⚡ Execute Short Straddle (Market)", callback_data='execute_market_straddle')],
                [InlineKeyboardButton("📊 View Open Positions", callback_data='view_positions')],
                [InlineKeyboardButton("🛡️ View Bracket Orders", callback_data='view_brackets')],
                [InlineKeyboardButton("💹 Check BTC Price", callback_data='btc_price')],
                [InlineKeyboardButton("ℹ️ Strategy Info", callback_data='strategy_info')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            welcome_text = (
                f"🤖 **Welcome {user.first_name}!**\n\n"
                "**Delta Exchange Short Straddle Bot**\n\n"
                "This bot executes short straddle strategies with **market orders** for immediate execution.\n\n"
                "**Features:**\n"
                "⚡ **Market order execution** for instant fills\n"
                "🛡️ **Automatic bracket orders** with 25% stop-loss\n"
                "🎯 **ATM strike selection** near BTC spot price\n"
                "📅 **Same-day expiry** options only\n"
                "📈 **1 lot size** per option (CE & PE)\n\n"
                "Click the buttons below to get started:"
            )
            
            await update.message.reply_text(
                welcome_text, 
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in start handler: {e}")
            await update.message.reply_text("❌ Error occurred. Please try /start again.")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command handler"""
        help_text = (
            "🤖 **Bot Commands:**\n\n"
            "/start - Start the bot and show main menu\n"
            "/status - Check system status and BTC price\n"
            "/positions - View your open positions\n"
            "/brackets - View active bracket orders\n"
            "/help - Show this help message\n\n"
            "**Trading Features:**\n"
            "⚡ **Market Orders**: Instant execution at best prices\n"
            "🛡️ **Bracket Orders**: Automatic 25% stop-loss protection\n"
            "🎯 **ATM Selection**: Closest strikes to BTC spot price\n\n"
            "Use the inline buttons for quick access to bot features."
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check system status"""
        try:
            user = update.effective_user
            logger.info(f"Status command from user {user.id}")
            
            spot_price = self.delta_client.get_btc_spot_price()
            status_text = (
                f"🟢 **System Status: Active**\n\n"
                f"📈 **BTC Spot Price:** ${spot_price:,.2f}\n"
                f"🔗 **Connected:** Delta Exchange India API\n"
                f"⚡ **Mode:** Webhook + Market Orders\n"
                f"🛡️ **Stop-Loss:** 25% Bracket Orders\n"
                f"🎯 **Strategy:** Short Straddle ATM"
            )
            await update.message.reply_text(status_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in status handler: {e}")
            await update.message.reply_text(f"❌ System Error: Unable to fetch status")
    
    async def show_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show open positions"""
        try:
            user = update.effective_user
            logger.info(f"Positions command from user {user.id}")
            
            positions_response = self.delta_client.get_open_positions()
            if positions_response.get('success') and positions_response.get('result'):
                positions = positions_response['result']
                if positions:
                    positions_text = "📊 **Open Positions:**\n\n"
                    for i, position in enumerate(positions[:10], 1):
                        pnl = float(position.get('unrealized_pnl', 0))
                        pnl_emoji = "📈" if pnl >= 0 else "📉"
                        positions_text += (
                            f"**{i}.** {position.get('product_symbol', 'N/A')}\n"
                            f"   Size: {position.get('size', 0)}\n"
                            f"   Entry: ${float(position.get('entry_price', 0)):,.2f}\n"
                            f"   {pnl_emoji} PnL: ${pnl:,.2f}\n\n"
                        )
                else:
                    positions_text = "📊 No open positions found."
            else:
                positions_text = "❌ Failed to fetch positions from Delta Exchange."
                
            await update.message.reply_text(positions_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in show_positions handler: {e}")
            await update.message.reply_text("❌ Error fetching positions. Please try again.")
    
    async def show_bracket_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bracket orders"""
        try:
            user = update.effective_user
            logger.info(f"Bracket orders command from user {user.id}")
            
            brackets_response = self.delta_client.get_bracket_orders()
            if brackets_response.get('success') and brackets_response.get('result'):
                brackets = brackets_response['result']
                if brackets:
                    brackets_text = "🛡️ **Active Bracket Orders:**\n\n"
                    for i, bracket in enumerate(brackets[:5], 1):
                        brackets_text += (
                            f"**{i}.** {bracket.get('product_symbol', 'N/A')}\n"
                            f"   Stop Loss: ${float(bracket.get('stop_loss_price', 0)):,.2f}\n"
                            f"   Status: {bracket.get('status', 'Unknown')}\n\n"
                        )
                else:
                    brackets_text = "🛡️ No active bracket orders found."
            else:
                brackets_text = "❌ Failed to fetch bracket orders."
                
            await update.message.reply_text(brackets_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in show_bracket_orders handler: {e}")
            await update.message.reply_text("❌ Error fetching bracket orders. Please try again.")
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        user = update.effective_user
        
        try:
            await query.answer()  # Acknowledge the callback
            logger.info(f"Button callback '{query.data}' from user {user.id}")
            
            if query.data == 'execute_market_straddle':
                await self.execute_market_straddle_callback(query)
            elif query.data == 'view_positions':
                await self.view_positions_callback(query)
            elif query.data == 'view_brackets':
                await self.view_brackets_callback(query)
            elif query.data == 'btc_price':
                await self.btc_price_callback(query)
            elif query.data == 'strategy_info':
                await self.strategy_info_callback(query)
            elif query.data == 'confirm_market_execute':
                await self.confirm_market_execute_callback(query)
            elif query.data == 'cancel':
                await query.edit_message_text("❌ Operation cancelled.")
            else:
                await query.edit_message_text("❌ Unknown action. Please try again.")
                
        except Exception as e:
            logger.error(f"Error in button callback '{query.data}': {e}")
            try:
                await query.edit_message_text("❌ Error occurred. Please try again.")
            except:
                pass  # Ignore if message can't be edited
    
    async def execute_market_straddle_callback(self, query):
        """Handle execute market straddle button"""
        try:
            keyboard = [
                [InlineKeyboardButton("⚡ Confirm Market Execution", callback_data='confirm_market_execute')],
                [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            confirmation_text = (
                "⚡ **Confirm Market Order Execution**\n\n"
                "This will **immediately execute**:\n"
                "📈 **Sell 1 lot** ATM BTC Call Option (Market Order)\n"
                "📉 **Sell 1 lot** ATM BTC Put Option (Market Order)\n"
                "🛡️ **Auto-place** 25% bracket stop-loss orders\n"
                "📅 **Same-day expiry** options only\n\n"
                "⚠️ **Warning:**\n"
                "• Market orders execute instantly at current prices\n"
                "• No price protection - immediate execution\n"
                "• Options trading involves significant risk!\n\n"
                "**Ready for instant execution?**"
            )
            
            await query.edit_message_text(
                confirmation_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error in execute_market_straddle_callback: {e}")
            await query.edit_message_text("❌ Error occurred. Please try again.")
    
    async def confirm_market_execute_callback(self, query):
        """Execute the short straddle strategy with market orders"""
        await query.edit_message_text("⚡ **Executing market orders...** Please wait...")
        
        try:
            result = self.delta_client.execute_short_straddle_market(DEFAULT_LOT_SIZE)
            
            if result.get('success'):
                success_text = (
                    f"✅ **Short Straddle Executed Successfully!**\n\n"
                    f"📈 **BTC Spot Price:** ${result['spot_price']:,.2f}\n"
                    f"🎯 **Strike Price:** ${result['strike_price']:,.2f}\n\n"
                    f"**Market Orders Executed:**\n"
                )
                
                for order in result['orders']:
                    if order['type'] == 'short_call_market':
                        success_text += f"📈 **Call Option:** ID {order['order_id']} @ ${order['price']:,.2f} ✅\n"
                    elif order['type'] == 'short_put_market':
                        success_text += f"📉 **Put Option:** ID {order['order_id']} @ ${order['price']:,.2f} ✅\n"
                
                success_text += "\n**🛡️ Bracket Orders (25% Stop-Loss):**\n"
                for bracket in result['bracket_orders']:
                    if bracket['status'] == 'active':
                        if bracket['type'] == 'call_bracket':
                            success_text += f"🛑 **Call Stop-Loss:** @ ${bracket['stop_price']:,.2f} ✅\n"
                        elif bracket['type'] == 'put_bracket':
                            success_text += f"🛑 **Put Stop-Loss:** @ ${bracket['stop_price']:,.2f} ✅\n"
                    else:
                        success_text += f"⚠️ **{bracket['type']}:** {bracket.get('error', 'Failed')}\n"
                
                success_text += "\n🎯 **Strategy Status:** Active with automatic stop-loss protection!"
                
                await query.edit_message_text(success_text, parse_mode='Markdown')
            else:
                error_text = f"❌ **Market Execution Failed**\n\n{result.get('error', 'Unknown error')}"
                await query.edit_message_text(error_text, parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Error in confirm_market_execute_callback: {e}")
            await query.edit_message_text(f"❌ **Error:** {str(e)}")
    
    async def view_positions_callback(self, query):
        """View open positions callback"""
        try:
            positions_response = self.delta_client.get_open_positions()
            if positions_response.get('success') and positions_response.get('result'):
                positions = positions_response['result']
                if positions:
                    positions_text = "📊 **Open Positions:**\n\n"
                    for i, position in enumerate(positions[:5], 1):
                        pnl = float(position.get('unrealized_pnl', 0))
                        pnl_emoji = "📈" if pnl >= 0 else "📉"
                        positions_text += (
                            f"**{i}.** {position.get('product_symbol', 'N/A')}\n"
                            f"   Size: {position.get('size', 0)}\n"
                            f"   Entry: ${float(position.get('entry_price', 0)):,.2f}\n"
                            f"   {pnl_emoji} PnL: ${pnl:,.2f}\n\n"
                        )
                else:
                    positions_text = "📊 No open positions found."
            else:
                positions_text = "❌ Failed to fetch positions."
                
            await query.edit_message_text(positions_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in view_positions_callback: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def view_brackets_callback(self, query):
        """View bracket orders callback"""
        try:
            brackets_response = self.delta_client.get_bracket_orders()
            if brackets_response.get('success') and brackets_response.get('result'):
                brackets = brackets_response['result']
                if brackets:
                    brackets_text = "🛡️ **Active Bracket Orders:**\n\n"
                    for i, bracket in enumerate(brackets[:5], 1):
                        brackets_text += (
                            f"**{i}.** {bracket.get('product_symbol', 'N/A')}\n"
                            f"   Stop Loss: ${float(bracket.get('stop_loss_price', 0)):,.2f}\n"
                            f"   Status: {bracket.get('status', 'Unknown')}\n\n"
                        )
                else:
                    brackets_text = "🛡️ No active bracket orders found."
            else:
                brackets_text = "❌ Failed to fetch bracket orders."
                
            await query.edit_message_text(brackets_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in view_brackets_callback: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def btc_price_callback(self, query):
        """Check BTC price callback"""
        try:
            spot_price = self.delta_client.get_btc_spot_price()
            price_text = (
                f"💰 **BTC Spot Price**\n\n"
                f"${spot_price:,.2f}\n\n"
                f"Ready for market order execution!"
            )
            await query.edit_message_text(price_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in btc_price_callback: {e}")
            await query.edit_message_text(f"❌ Error fetching price: {str(e)}")
    
    async def strategy_info_callback(self, query):
        """Show strategy information"""
        info_text = (
            "⚡ **Market Order Short Straddle Strategy**\n\n"
            "**Execution Method:**\n"
            "• **Market Orders** for instant execution\n"
            "• **No slippage protection** - executes at current prices\n"
            "• **Immediate fills** at best available prices\n\n"
            "**Risk Management:**\n"
            "🛡️ **Bracket Orders** with 25% stop-loss\n"
            "🎯 **ATM strikes** closest to BTC spot\n"
            "📅 **Same-day expiry** for maximum theta decay\n\n"
            "**Strategy Details:**\n"
            "• Sells 1 lot ATM Call + 1 lot ATM Put\n"
            "• Profits from time decay and low volatility\n"
            "• **Unlimited risk** - use stop-loss protection\n\n"
            "⚠️ **Best suited for:** Low volatility environments"
        )
        await query.edit_message_text(info_text, parse_mode='Markdown')
