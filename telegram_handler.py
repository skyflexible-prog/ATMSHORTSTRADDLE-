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
        self.application.add_handler(CommandHandler("orders", self.show_orders))
        self.application.add_handler(CommandHandler("portfolio", self.show_portfolio))
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
                [InlineKeyboardButton("📊 View Portfolio", callback_data='view_portfolio')],
                [InlineKeyboardButton("📈 View Positions", callback_data='view_positions')],
                [InlineKeyboardButton("📋 View Orders", callback_data='view_orders')],
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
                "🛡️ **Automatic reduce-only stop orders** with 25% stop-loss\n"
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
            
            positions_response = self.delta_client.get_positions()
            
            if positions_response.get('success'):
                positions = positions_response.get('result', [])
                
                # Filter out positions with zero size
                active_positions = [pos for pos in positions if float(pos.get('size', 0)) != 0]
                
                if active_positions:
                    positions_text = "📊 **Active Positions:**\n\n"
                    total_pnl = 0
                    
                    for i, position in enumerate(active_positions[:10], 1):
                        size = float(position.get('size', 0))
                        entry_price = float(position.get('entry_price', 0))
                        mark_price = float(position.get('mark_price', 0))
                        pnl = float(position.get('unrealized_pnl', 0))
                        total_pnl += pnl
                        
                        pnl_emoji = "📈" if pnl >= 0 else "📉"
                        side_emoji = "📉" if size < 0 else "📈"
                        
                        positions_text += (
                            f"{side_emoji} **{i}.** {position.get('product_symbol', 'N/A')}\n"
                            f"   **Size:** {size}\n"
                            f"   **Entry:** ${entry_price:,.2f}\n"
                            f"   **Mark:** ${mark_price:,.2f}\n"
                            f"   {pnl_emoji} **PnL:** ${pnl:,.2f}\n\n"
                        )
                    
                    total_emoji = "📈" if total_pnl >= 0 else "📉"
                    positions_text += f"{total_emoji} **Total PnL:** ${total_pnl:,.2f}"
                else:
                    positions_text = "📊 No active positions found."
            else:
                error_msg = positions_response.get('error', 'Unknown error')
                positions_text = f"❌ Failed to fetch positions: {error_msg}"
                logger.error(f"Positions API error: {error_msg}")
                
            await update.message.reply_text(positions_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in show_positions handler: {e}")
            await update.message.reply_text("❌ Error fetching positions. Please try again.")
    
    async def show_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show open orders including stop orders"""
        try:
            user = update.effective_user
            logger.info(f"Orders command from user {user.id}")
            
            orders_response = self.delta_client.get_open_orders()
            
            if orders_response.get('success'):
                orders = orders_response.get('result', [])
                
                if orders:
                    orders_text = "📋 **Open Orders:**\n\n"
                    
                    for i, order in enumerate(orders[:10], 1):
                        order_type_emoji = "🛑" if order.get('reduce_only') else "📊"
                        order_type = "Stop-Loss" if order.get('reduce_only') else "Regular"
                        side_emoji = "🟢" if order.get('side') == 'buy' else "🔴"
                        
                        orders_text += (
                            f"{order_type_emoji} **{i}. {order_type} Order**\n"
                            f"   **ID:** {order.get('id', 'N/A')}\n"
                            f"   **Product:** {order.get('product_symbol', 'N/A')}\n"
                            f"   {side_emoji} **Side:** {order.get('side', 'N/A').upper()}\n"
                            f"   **Size:** {order.get('size', 0)}\n"
                        )
                        
                        if order.get('limit_price'):
                            orders_text += f"   **Price:** ${float(order['limit_price']):,.2f}\n"
                        
                        if order.get('stop_price'):
                            orders_text += f"   🛑 **Stop:** ${float(order['stop_price']):,.2f}\n"
                        
                        orders_text += f"   **Status:** {order.get('state', 'Unknown')}\n\n"
                else:
                    orders_text = "📋 No open orders found."
            else:
                error_msg = orders_response.get('error', 'Unknown error')
                orders_text = f"❌ Failed to fetch orders: {error_msg}"
                logger.error(f"Orders API error: {error_msg}")
                
            await update.message.reply_text(orders_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in show_orders handler: {e}")
            await update.message.reply_text("❌ Error fetching orders. Please try again.")
    
    async def show_portfolio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show comprehensive portfolio summary"""
        try:
            user = update.effective_user
            logger.info(f"Portfolio command from user {user.id}")
            
            portfolio_response = self.delta_client.get_portfolio_summary()
            
            if portfolio_response.get('success'):
                portfolio_text = "💼 **Portfolio Summary:**\n\n"
                
                # Wallet balances
                wallet = portfolio_response.get('wallet', [])
                if wallet:
                    portfolio_text += "💰 **Balances:**\n"
                    for balance in wallet[:5]:  # Show top 5 assets
                        asset = balance.get('asset_symbol', 'N/A')
                        available = float(balance.get('available_balance', 0))
                        if available > 0:
                            portfolio_text += f"   {asset}: {available:,.4f}\n"
                    portfolio_text += "\n"
                
                # Active positions summary
                positions = portfolio_response.get('positions', [])
                active_positions = [pos for pos in positions if float(pos.get('size', 0)) != 0]
                
                if active_positions:
                    portfolio_text += f"📊 **Active Positions:** {len(active_positions)}\n"
                    total_pnl = sum(float(pos.get('unrealized_pnl', 0)) for pos in active_positions)
                    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
                    portfolio_text += f"{pnl_emoji} **Total PnL:** ${total_pnl:,.2f}\n\n"
                
                # Open orders summary
                orders = portfolio_response.get('open_orders', [])
                if orders:
                    stop_orders = [order for order in orders if order.get('reduce_only')]
                    regular_orders = [order for order in orders if not order.get('reduce_only')]
                    
                    portfolio_text += f"📋 **Open Orders:** {len(orders)}\n"
                    portfolio_text += f"   Regular: {len(regular_orders)}\n"
                    portfolio_text += f"   🛑 Stop Orders: {len(stop_orders)}\n\n"
                
                # Any errors
                errors = portfolio_response.get('errors', [])
                if errors:
                    portfolio_text += "⚠️ **Warnings:**\n"
                    for error in errors:
                        portfolio_text += f"   {error}\n"
                
            else:
                error_msg = portfolio_response.get('error', 'Unknown error')
                portfolio_text = f"❌ Failed to fetch portfolio: {error_msg}"
                logger.error(f"Portfolio API error: {error_msg}")
                
            await update.message.reply_text(portfolio_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in show_portfolio handler: {e}")
            await update.message.reply_text("❌ Error fetching portfolio. Please try again.")
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
    
    # ... (include all other methods from previous code) ...
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        user = update.effective_user
        
        try:
            await query.answer()  # Acknowledge the callback
            logger.info(f"Button callback '{query.data}' from user {user.id}")
            
            if query.data == 'execute_market_straddle':
                await self.execute_market_straddle_callback(query)
            elif query.data == 'view_portfolio':
                await self.view_portfolio_callback(query)
            elif query.data == 'view_positions':
                await self.view_positions_callback(query)
            elif query.data == 'view_orders':
                await self.view_orders_callback(query)
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
    
    async def view_portfolio_callback(self, query):
        """View portfolio callback"""
        try:
            portfolio_response = self.delta_client.get_portfolio_summary()
            
            if portfolio_response.get('success'):
                portfolio_text = "💼 **Portfolio Summary:**\n\n"
                
                # Quick stats
                positions = portfolio_response.get('positions', [])
                active_positions = [pos for pos in positions if float(pos.get('size', 0)) != 0]
                orders = portfolio_response.get('open_orders', [])
                
                if active_positions:
                    total_pnl = sum(float(pos.get('unrealized_pnl', 0)) for pos in active_positions)
                    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
                    portfolio_text += f"📊 **Positions:** {len(active_positions)}\n"
                    portfolio_text += f"{pnl_emoji} **Total PnL:** ${total_pnl:,.2f}\n\n"
                
                if orders:
                    stop_orders = len([o for o in orders if o.get('reduce_only')])
                    portfolio_text += f"📋 **Orders:** {len(orders)} ({stop_orders} stop orders)\n\n"
                
                if not active_positions and not orders:
                    portfolio_text += "📊 No active positions or orders.\n\n"
                
                portfolio_text += "Use /positions, /orders for detailed views."
            else:
                portfolio_text = f"❌ Portfolio unavailable: {portfolio_response.get('error', 'Unknown error')}"
                
            await query.edit_message_text(portfolio_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in view_portfolio_callback: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def view_positions_callback(self, query):
        """View positions callback"""
        try:
            positions_response = self.delta_client.get_positions()
            
            if positions_response.get('success'):
                positions = positions_response.get('result', [])
                active_positions = [pos for pos in positions if float(pos.get('size', 0)) != 0]
                
                if active_positions:
                    positions_text = "📊 **Active Positions:**\n\n"
                    for i, position in enumerate(active_positions[:5], 1):
                        size = float(position.get('size', 0))
                        pnl = float(position.get('unrealized_pnl', 0))
                        pnl_emoji = "📈" if pnl >= 0 else "📉"
                        side_emoji = "📉" if size < 0 else "📈"
                        
                        positions_text += (
                            f"{side_emoji} **{i}.** {position.get('product_symbol', 'N/A')}\n"
                            f"   Size: {size}, {pnl_emoji} PnL: ${pnl:,.2f}\n\n"
                        )
                else:
                    positions_text = "📊 No active positions found."
            else:
                positions_text = f"❌ Failed to fetch positions: {positions_response.get('error', 'Unknown error')}"
                
            await query.edit_message_text(positions_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in view_positions_callback: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def view_orders_callback(self, query):
        """View orders callback"""
        try:
            orders_response = self.delta_client.get_open_orders()
            
            if orders_response.get('success'):
                orders = orders_response.get('result', [])
                
                if orders:
                    orders_text = "📋 **Open Orders:**\n\n"
                    for i, order in enumerate(orders[:5], 1):
                        order_type_emoji = "🛑" if order.get('reduce_only') else "📊"
                        order_type = "Stop" if order.get('reduce_only') else "Regular"
                        
                        orders_text += (
                            f"{order_type_emoji} **{i}. {order_type}**\n"
                            f"   {order.get('product_symbol', 'N/A')}\n"
                            f"   {order.get('side', 'N/A').upper()} {order.get('size', 0)}\n\n"
                        )
                else:
                    orders_text = "📋 No open orders found."
            else:
                orders_text = f"❌ Failed to fetch orders: {orders_response.get('error', 'Unknown error')}"
                
            await query.edit_message_text(orders_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in view_orders_callback: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")

    # ... (include all remaining methods from the previous code) ...
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
            
            success_text += "\n**🛡️ Reduce-Only Stop Orders (25% Stop-Loss):**\n"
            for stop in result['stop_orders']:
                if stop['status'] == 'active':
                    if stop['type'] == 'call_stop_loss':
                        success_text += f"🛑 **Call Stop-Loss:** ID {stop['order_id']} @ ${stop['stop_price']:,.2f} ✅\n"
                    elif stop['type'] == 'put_stop_loss':
                        success_text += f"🛑 **Put Stop-Loss:** ID {stop['order_id']} @ ${stop['stop_price']:,.2f} ✅\n"
                else:
                    success_text += f"⚠️ **{stop['type']}:** {stop.get('error', 'Failed to place')}\n"
            
            success_text += "\n🎯 **Strategy Status:** Active with reduce-only stop protection!"
            
            await query.edit_message_text(success_text, parse_mode='Markdown')
        else:
            error_text = f"❌ **Market Execution Failed**\n\n{result.get('error', 'Unknown error')}"
            await query.edit_message_text(error_text, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Error in confirm_market_execute_callback: {e}")
        await query.edit_message_text(f"❌ **Error:** {str(e)}")
async def show_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show open orders including stop orders"""
    try:
        user = update.effective_user
        logger.info(f"Orders command from user {user.id}")
        
        orders_response = self.delta_client.get_open_orders()
        if orders_response.get('success') and orders_response.get('result'):
            orders = orders_response['result']
            if orders:
                orders_text = "📋 **Open Orders:**\n\n"
                for i, order in enumerate(orders[:10], 1):
                    order_type_emoji = "🛑" if order.get('reduce_only') else "📊"
                    order_type = "Stop-Loss" if order.get('reduce_only') else "Regular"
                    orders_text += (
                        f"{order_type_emoji} **{i}. {order_type}**\n"
                        f"   ID: {order['id']}\n"
                        f"   Side: {order['side'].upper()}\n"
                        f"   Size: {order['size']}\n"
                        f"   Price: ${float(order.get('limit_price', 0)):,.2f}\n"
                    )
                    if order.get('stop_price'):
                        orders_text += f"   Stop: ${float(order['stop_price']):,.2f}\n"
                    orders_text += "\n"
            else:
                orders_text = "📋 No open orders found."
        else:
            orders_text = "❌ Failed to fetch orders from Delta Exchange."
            
        await update.message.reply_text(orders_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in show_orders handler: {e}")
        await update.message.reply_text("❌ Error fetching orders. Please try again.")

async def strategy_info_callback(self, query):
    """Show strategy information"""
    info_text = (
        "⚡ **Market Order Short Straddle Strategy**\n\n"
        "**Execution Method:**\n"
        "• **Market Orders** for instant execution\n"
        "• **No slippage protection** - executes at current prices\n"
        "• **Immediate fills** at best available prices\n\n"
        "**Risk Management:**\n"
        "🛡️ **Reduce-Only Stop Orders** with 25% stop-loss\n"
        "🎯 **ATM strikes** closest to BTC spot\n"
        "📅 **Same-day expiry** for maximum theta decay\n\n"
        "**New Feature - Reduce-Only Orders:**\n"
        "• Replaces deprecated bracket orders\n"
        "• Only reduces/closes positions (no new positions)\n"
        "• Better risk control and flexibility\n\n"
        "**Strategy Details:**\n"
        "• Sells 1 lot ATM Call + 1 lot ATM Put\n"
        "• Profits from time decay and low volatility\n"
        "• **Unlimited risk** - use stop-loss protection\n\n"
        "⚠️ **Best suited for:** Low volatility environments"
    )
    await query.edit_message_text(info_text, parse_mode='Markdown')

    
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
