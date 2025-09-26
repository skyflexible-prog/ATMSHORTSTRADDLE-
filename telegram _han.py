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
    
    # ... (other methods remain the same) ...
    
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
    
    async def view_positions_callback(self, query):
        """View positions callback with enhanced error handling"""
        try:
            await query.edit_message_text("📊 Fetching positions...")
            
            logger.info("Attempting to fetch positions via API")
            positions_response = self.delta_client.get_positions()
            
            logger.info(f"Positions API response: {positions_response}")
            
            if positions_response.get('success'):
                positions = positions_response.get('result', [])
                logger.info(f"Found {len(positions)} positions")
                
                # Handle different response formats
                if isinstance(positions, list):
                    # Filter active positions (size != 0)
                    active_positions = []
                    for pos in positions:
                        try:
                            size = float(pos.get('size', 0))
                            if size != 0:
                                active_positions.append(pos)
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Error processing position {pos}: {e}")
                            continue
                    
                    if active_positions:
                        positions_text = "📊 **Active Positions:**\n\n"
                        total_pnl = 0
                        
                        for i, position in enumerate(active_positions[:10], 1):
                            try:
                                size = float(position.get('size', 0))
                                entry_price = position.get('entry_price', 0)
                                mark_price = position.get('mark_price', 0)
                                pnl = position.get('unrealized_pnl', 0)
                                
                                # Convert to float safely
                                try:
                                    entry_price = float(entry_price) if entry_price else 0
                                    mark_price = float(mark_price) if mark_price else 0
                                    pnl = float(pnl) if pnl else 0
                                except (ValueError, TypeError):
                                    entry_price = mark_price = pnl = 0
                                
                                total_pnl += pnl
                                
                                pnl_emoji = "📈" if pnl >= 0 else "📉"
                                side_emoji = "📉" if size < 0 else "📈"
                                
                                product_symbol = position.get('product_symbol', 'Unknown')
                                
                                positions_text += (
                                    f"{side_emoji} **{i}.** {product_symbol}\n"
                                    f"   **Size:** {size}\n"
                                )
                                
                                if entry_price > 0:
                                    positions_text += f"   **Entry:** ${entry_price:,.2f}\n"
                                if mark_price > 0:
                                    positions_text += f"   **Mark:** ${mark_price:,.2f}\n"
                                if pnl != 0:
                                    positions_text += f"   {pnl_emoji} **PnL:** ${pnl:,.2f}\n"
                                
                                positions_text += "\n"
                                
                            except Exception as e:
                                logger.error(f"Error formatting position {i}: {e}")
                                positions_text += f"{i}. Error displaying position\n\n"
                        
                        total_emoji = "📈" if total_pnl >= 0 else "📉"
                        positions_text += f"{total_emoji} **Total PnL:** ${total_pnl:,.2f}"
                        
                    else:
                        positions_text = "📊 **No active positions found.**\n\nAll position sizes are zero."
                        
                elif isinstance(positions, dict):
                    # Handle single position format
                    positions_text = "📊 **Position Data:**\n\n"
                    for key, value in positions.items():
                        positions_text += f"**{key}:** {value}\n"
                else:
                    positions_text = f"📊 **Unexpected data format:**\n{str(positions)[:500]}..."
                    
            else:
                # API call failed
                error_msg = positions_response.get('error', 'Unknown error')
                positions_text = (
                    f"❌ **Failed to fetch positions**\n\n"
                    f"**Error:** {error_msg}\n\n"
                    f"**Possible causes:**\n"
                    f"• API credentials issue\n"
                    f"• Network connectivity problem\n"
                    f"• Delta Exchange API temporarily unavailable\n\n"
                    f"Try again in a few moments."
                )
                logger.error(f"Positions API failed: {error_msg}")
            
            await query.edit_message_text(positions_text, parse_mode='Markdown')
            
        except Exception as e:
            error_msg = f"❌ **Position Callback Error**\n\n**Details:** {str(e)}"
            logger.error(f"Exception in view_positions_callback: {e}")
            try:
                await query.edit_message_text(error_msg, parse_mode='Markdown')
            except:
                await query.edit_message_text("❌ Critical error occurred. Please try /positions command.")
    
    async def view_orders_callback(self, query):
        """View orders callback with enhanced error handling"""
        try:
            await query.edit_message_text("📋 Fetching orders...")
            
            logger.info("Attempting to fetch orders via API")
            orders_response = self.delta_client.get_open_orders()
            
            logger.info(f"Orders API response: {orders_response}")
            
            if orders_response.get('success'):
                orders = orders_response.get('result', [])
                logger.info(f"Found {len(orders)} orders")
                
                if orders and isinstance(orders, list):
                    orders_text = "📋 **Open Orders:**\n\n"
                    
                    for i, order in enumerate(orders[:10], 1):
                        try:
                            order_type_emoji = "🛑" if order.get('reduce_only') else "📊"
                            order_type = "Stop-Loss" if order.get('reduce_only') else "Regular"
                            side_emoji = "🟢" if order.get('side') == 'buy' else "🔴"
                            
                            orders_text += f"{order_type_emoji} **{i}. {order_type}**\n"
                            
                            # Safely get order details
                            order_id = order.get('id', 'N/A')
                            product_symbol = order.get('product_symbol', 'N/A')
                            side = order.get('side', 'N/A').upper()
                            size = order.get('size', 0)
                            state = order.get('state', 'Unknown')
                            
                            orders_text += (
                                f"   **ID:** {order_id}\n"
                                f"   **Product:** {product_symbol}\n"
                                f"   {side_emoji} **Side:** {side}\n"
                                f"   **Size:** {size}\n"
                            )
                            
                            # Add price information if available
                            limit_price = order.get('limit_price')
                            if limit_price:
                                try:
                                    orders_text += f"   **Price:** ${float(limit_price):,.2f}\n"
                                except (ValueError, TypeError):
                                    orders_text += f"   **Price:** {limit_price}\n"
                            
                            stop_price = order.get('stop_price')
                            if stop_price:
                                try:
                                    orders_text += f"   🛑 **Stop:** ${float(stop_price):,.2f}\n"
                                except (ValueError, TypeError):
                                    orders_text += f"   🛑 **Stop:** {stop_price}\n"
                            
                            orders_text += f"   **Status:** {state}\n\n"
                            
                        except Exception as e:
                            logger.error(f"Error formatting order {i}: {e}")
                            orders_text += f"{i}. Error displaying order\n\n"
                
                elif isinstance(orders, dict):
                    orders_text = "📋 **Order Data:**\n\n"
                    for key, value in orders.items():
                        orders_text += f"**{key}:** {value}\n"
                else:
                    orders_text = "📋 **No open orders found.**"
                    
            else:
                error_msg = orders_response.get('error', 'Unknown error')
                orders_text = (
                    f"❌ **Failed to fetch orders**\n\n"
                    f"**Error:** {error_msg}\n\n"
                    f"Try the /orders command instead."
                )
                logger.error(f"Orders API failed: {error_msg}")
            
            await query.edit_message_text(orders_text, parse_mode='Markdown')
            
        except Exception as e:
            error_msg = f"❌ **Orders Callback Error**\n\n**Details:** {str(e)}"
            logger.error(f"Exception in view_orders_callback: {e}")
            try:
                await query.edit_message_text(error_msg, parse_mode='Markdown')
            except:
                await query.edit_message_text("❌ Critical error occurred. Please try /orders command.")
    
    async def view_portfolio_callback(self, query):
        """View portfolio callback with enhanced error handling"""
        try:
            await query.edit_message_text("💼 Fetching portfolio...")
            
            logger.info("Attempting to fetch portfolio summary")
            portfolio_response = self.delta_client.get_portfolio_summary()
            
            logger.info(f"Portfolio API response success: {portfolio_response.get('success', False)}")
            
            if portfolio_response.get('success'):
                portfolio_text = "💼 **Portfolio Summary:**\n\n"
                
                # Quick stats
                positions = portfolio_response.get('positions', [])
                orders = portfolio_response.get('orders', [])
                wallet = portfolio_response.get('wallet', [])
                errors = portfolio_response.get('errors', [])
                
                # Filter active positions
                active_positions = []
                if isinstance(positions, list):
                    active_positions = [pos for pos in positions if float(pos.get('size', 0)) != 0]
                
                if active_positions:
                    total_pnl = 0
                    try:
                        total_pnl = sum(float(pos.get('unrealized_pnl', 0)) for pos in active_positions)
                    except (ValueError, TypeError):
                        total_pnl = 0
                    
                    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
                    portfolio_text += f"📊 **Positions:** {len(active_positions)}\n"
                    portfolio_text += f"{pnl_emoji} **Total PnL:** ${total_pnl:,.2f}\n\n"
                
                if orders:
                    stop_orders = len([o for o in orders if o.get('reduce_only')])
                    portfolio_text += f"📋 **Orders:** {len(orders)} ({stop_orders} stop orders)\n\n"
                
                if wallet:
                    portfolio_text += f"💰 **Assets:** {len(wallet)} currencies\n\n"
                
                if not active_positions and not orders:
                    portfolio_text += "📊 No active positions or orders.\n\n"
                
                if errors:
                    portfolio_text += "⚠️ **Warnings:**\n"
                    for error in errors[:3]:  # Show max 3 errors
                        portfolio_text += f"   {error}\n"
                    portfolio_text += "\n"
                
                portfolio_text += "Use buttons above for detailed views."
                
            else:
                error_msg = portfolio_response.get('error', 'Unknown error')
                portfolio_text = (
                    f"❌ **Portfolio unavailable**\n\n"
                    f"**Error:** {error_msg}\n\n"
                    f"Try individual commands:\n"
                    f"/positions - View positions\n"
                    f"/orders - View orders"
                )
                logger.error(f"Portfolio API failed: {error_msg}")
            
            await query.edit_message_text(portfolio_text, parse_mode='Markdown')
            
        except Exception as e:
            error_msg = f"❌ **Portfolio Callback Error**\n\n**Details:** {str(e)}"
            logger.error(f"Exception in view_portfolio_callback: {e}")
            try:
                await query.edit_message_text(error_msg, parse_mode='Markdown')
            except:
                await query.edit_message_text("❌ Critical error occurred. Please try /portfolio command.")
    
    # ... (include all other methods from the original code) ...
