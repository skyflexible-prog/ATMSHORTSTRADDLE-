import os
import asyncio
import logging
import json
import time
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import aiohttp
from aiohttp import web
from aiohttp.web import Request, Response, json_response
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OrderTracker:
    """Track and manage active orders and positions"""
    
    def __init__(self):
        self.active_positions: Dict[str, Dict] = {}  # Track active straddle positions
        self.stop_orders: Dict[str, Dict] = {}       # Track stop-loss orders
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}  # Monitoring tasks
        
    def add_position(self, position_id: str, call_data: Dict, put_data: Dict):
        """Add a new straddle position to track"""
        self.active_positions[position_id] = {
            'call': call_data,
            'put': put_data,
            'status': 'active',
            'created_at': datetime.now(),
            'stop_triggered': None
        }
        
    def get_position(self, position_id: str) -> Optional[Dict]:
        """Get position data"""
        return self.active_positions.get(position_id)
        
    def mark_stop_triggered(self, position_id: str, option_type: str):
        """Mark which stop-loss was triggered"""
        if position_id in self.active_positions:
            self.active_positions[position_id]['stop_triggered'] = option_type
            self.active_positions[position_id]['status'] = 'adjusting'

class DeltaExchangeClient:
    """Enhanced Delta Exchange India API Client with order monitoring"""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.india.delta.exchange"
        self.session = None
        
    async def _get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    def _generate_signature(self, method: str, timestamp: str, path: str, 
                          query_string: str = "", payload: str = "") -> str:
        """Generate signature for Delta Exchange API"""
        message = method + timestamp + path + query_string + payload
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    async def _make_request(self, method: str, endpoint: str, 
                          params: Dict = None, data: Dict = None) -> Dict:
        """Make authenticated request to Delta Exchange API"""
        session = await self._get_session()
        timestamp = str(int(time.time()))
        path = f"/v2{endpoint}"
        
        query_string = ""
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            if query_string:
                query_string = "?" + query_string
        
        payload = ""
        if data:
            payload = json.dumps(data)
        
        signature = self._generate_signature(method, timestamp, path, query_string, payload)
        
        headers = {
            'api-key': self.api_key,
            'timestamp': timestamp,
            'signature': signature,
            'User-Agent': 'python-rest-client',
            'Content-Type': 'application/json'
        }
        
        url = f"{self.base_url}{path}"
        if query_string:
            url += query_string
            
        try:
            if method.upper() == 'GET':
                async with session.get(url, headers=headers) as response:
                    return await response.json()
            elif method.upper() == 'POST':
                async with session.post(url, headers=headers, data=payload) as response:
                    return await response.json()
            elif method.upper() == 'DELETE':
                async with session.delete(url, headers=headers, data=payload) as response:
                    return await response.json()
            elif method.upper() == 'PUT':
                async with session.put(url, headers=headers, data=payload) as response:
                    return await response.json()
        except Exception as e:
            logger.error(f"API request failed: {e}")
            raise
    
    async def get_products(self, contract_type: str = None) -> Dict:
        """Get list of products"""
        params = {}
        if contract_type:
            params['contract_types'] = contract_type
        return await self._make_request('GET', '/products', params=params)
    
    async def get_ticker(self, symbol: str) -> Dict:
        """Get ticker data for a product"""
        return await self._make_request('GET', f'/tickers/{symbol}')
    
    async def get_order_status(self, order_id: str) -> Dict:
        """Get order status"""
        return await self._make_request('GET', f'/orders/{order_id}')
    
    async def get_position(self, product_id: int) -> Dict:
        """Get position for a product"""
        return await self._make_request('GET', f'/positions/margined/{product_id}')
    
    async def cancel_order(self, order_id: str, product_id: int = None) -> Dict:
        """Cancel an order"""
        data = {'id': order_id}
        if product_id:
            data['product_id'] = product_id
        return await self._make_request('DELETE', '/orders', data=data)
    
    async def modify_order(self, order_id: str, limit_price: str = None, 
                          stop_price: str = None, size: int = None) -> Dict:
        """Modify an existing order"""
        data = {'id': order_id}
        if limit_price:
            data['limit_price'] = limit_price
        if stop_price:
            data['stop_price'] = stop_price
        if size:
            data['size'] = size
        return await self._make_request('PUT', '/orders', data=data)
    
    async def get_spot_price(self) -> float:
        """Get BTC spot price"""
        try:
            ticker = await self.get_ticker('BTCUSD')
            if ticker.get('success'):
                return float(ticker['result']['mark_price'])
            return 0.0
        except Exception as e:
            logger.error(f"Failed to get spot price: {e}")
            return 0.0
    
    async def find_atm_options(self, spot_price: float) -> Dict[str, Optional[Dict]]:
        """Find ATM call and put options for same day expiry"""
        try:
            # Get today's date in DD-MM-YYYY format as per Delta Exchange API
            today = datetime.now().strftime("%d-%m-%Y")
            
            # Get option chain for today's expiry using proper API endpoint
            option_chain = await self._make_request('GET', '/tickers', {
                'contract_types': 'call_options,put_options',
                'underlying_asset_symbols': 'BTC',
                'expiry_date': today
            })
            
            if not option_chain.get('success'):
                logger.error(f"Failed to get option chain: {option_chain}")
                # Try D1 (expires within 24 hours) if today's date doesn't work
                products = await self._make_request('GET', '/products', {
                    'contract_types': 'call_options,put_options'
                })
                
                if not products.get('success'):
                    return {'call': None, 'put': None}
                
                return self._find_closest_expiry_options(products['result'], spot_price)
            
            return self._find_atm_from_chain(option_chain['result'], spot_price)
            
        except Exception as e:
            logger.error(f"Failed to find ATM options: {e}")
            return {'call': None, 'put': None}

    def _find_atm_from_chain(self, options_data: List[Dict], spot_price: float) -> Dict[str, Optional[Dict]]:
        """Find ATM options from option chain data"""
        call_option = None
        put_option = None
        min_call_diff = float('inf')
        min_put_diff = float('inf')
        
        for option in options_data:
            if not option.get('strike_price'):
                continue
                
            strike_price = float(option['strike_price'])
            diff = abs(strike_price - spot_price)
            
            # Find closest call option
            if option.get('contract_type') == 'call_options' and diff < min_call_diff:
                min_call_diff = diff
                call_option = {
                    'id': option['product_id'],
                    'symbol': option['symbol'],
                    'strike_price': strike_price,
                    'contract_type': 'call_options'
                }
            
            # Find closest put option  
            elif option.get('contract_type') == 'put_options' and diff < min_put_diff:
                min_put_diff = diff
                put_option = {
                    'id': option['product_id'],
                    'symbol': option['symbol'], 
                    'strike_price': strike_price,
                    'contract_type': 'put_options'
                }
        
        return {'call': call_option, 'put': put_option}

    def _find_closest_expiry_options(self, products_data: List[Dict], spot_price: float) -> Dict[str, Optional[Dict]]:
        """Find options with closest expiry (fallback method)"""
        call_option = None
        put_option = None
        min_call_diff = float('inf')
        min_put_diff = float('inf')
        today = datetime.now().date()
        
        for product in products_data:
            if product['underlying_asset']['symbol'] != 'BTC':
                continue
                
            # Check if it's a same-day or next-day expiry option
            settlement_time = product.get('settlement_time')
            if settlement_time:
                try:
                    # Parse settlement time and check if it's today or tomorrow
                    settlement_date = datetime.fromisoformat(settlement_time.replace('Z', '+00:00')).date()
                    days_diff = (settlement_date - today).days
                    
                    # Only consider options expiring today (0) or tomorrow (1) for same-day strategy
                    if days_diff > 1:
                        continue
                        
                except (ValueError, TypeError):
                    # If we can't parse the date, skip this option
                    continue
            
            strike_price = float(product.get('strike_price', 0))
            if strike_price == 0:
                continue
                
            diff = abs(strike_price - spot_price)
            
            # Find closest call option
            if product['contract_type'] == 'call_options' and diff < min_call_diff:
                min_call_diff = diff
                call_option = {
                    'id': product['id'],
                    'symbol': product['symbol'],
                    'strike_price': strike_price,
                    'contract_type': 'call_options'
                }
            
            # Find closest put option
            elif product['contract_type'] == 'put_options' and diff < min_put_diff:
                min_put_diff = diff
                put_option = {
                    'id': product['id'],
                    'symbol': product['symbol'],
                    'strike_price': strike_price,
                    'contract_type': = 'put_options'
                }
        
        return {'call': call_option, 'put': put_option}
    
    async def calculate_break_even_price(self, position_data: Dict, option_type: str) -> float:
        """Calculate break-even price for the remaining position"""
        try:
            if option_type == 'call':
                # For remaining put position: break-even = strike - premium_collected
                strike_price = float(position_data['put']['strike_price'])
                premium_collected = float(position_data['put'].get('premium_received', 0))
                return strike_price - premium_collected
            else:  # put
                # For remaining call position: break-even = strike + premium_collected  
                strike_price = float(position_data['call']['strike_price'])
                premium_collected = float(position_data['call'].get('premium_received', 0))
                return strike_price + premium_collected
        except Exception as e:
            logger.error(f"Failed to calculate break-even: {e}")
            return 0.0
    
    async def place_order(self, product_id: int, side: str, size: int, 
                         order_type: str = "market_order", limit_price: str = None) -> Dict:
        """Place an order"""
        data = {
            'product_id': product_id,
            'side': side,
            'size': size,
            'order_type': order_type
        }
        if limit_price:
            data['limit_price'] = limit_price
        return await self._make_request('POST', '/orders', data=data)
    
    async def place_stop_order(self, product_id: int, side: str, size: int,
                              stop_price: str, order_type: str = "stop_limit_order",
                              limit_price: str = None) -> Dict:
        """Place a stop-loss order"""
        data = {
            'product_id': product_id,
            'side': side,
            'size': size,
            'order_type': order_type,
            'stop_price': stop_price
        }
        if limit_price:
            data['limit_price'] = limit_price
            
        return await self._make_request('POST', '/orders', data=data)

class TelegramBot:
    """Enhanced Telegram Bot Handler with position monitoring"""
    
    def __init__(self, bot_token: str, delta_client: DeltaExchangeClient):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.delta_client = delta_client
        self.order_tracker = OrderTracker()
        
    async def send_message(self, chat_id: int, text: str, 
                          reply_markup: Dict = None) -> bool:
        """Send message to Telegram chat"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False
    
    async def monitor_stop_orders(self, position_id: str, chat_id: int):
        """Monitor stop-loss orders for triggers and adjust break-even"""
        try:
            position_data = self.order_tracker.get_position(position_id)
            if not position_data:
                return
                
            call_stop_id = position_data['call'].get('stop_order_id')
            put_stop_id = position_data['put'].get('stop_order_id')
            
            while position_data['status'] == 'active':
                await asyncio.sleep(30)  # Check every 30 seconds
                
                # Check call stop-loss status
                if call_stop_id:
                    call_stop_status = await self.delta_client.get_order_status(call_stop_id)
                    if call_stop_status.get('success') and call_stop_status['result'].get('state') == 'filled':
                        await self.handle_stop_triggered(position_id, 'call', chat_id)
                        break
                
                # Check put stop-loss status  
                if put_stop_id:
                    put_stop_status = await self.delta_client.get_order_status(put_stop_id)
                    if put_stop_status.get('success') and put_stop_status['result'].get('state') == 'filled':
                        await self.handle_stop_triggered(position_id, 'put', chat_id)
                        break
                        
        except Exception as e:
            logger.error(f"Error monitoring stop orders: {e}")
    
    async def handle_stop_triggered(self, position_id: str, triggered_option: str, chat_id: int):
        """Handle stop-loss trigger and adjust remaining position to break-even"""
        try:
            position_data = self.order_tracker.get_position(position_id)
            if not position_data:
                return
                
            self.order_tracker.mark_stop_triggered(position_id, triggered_option)
            
            await self.send_message(
                chat_id,
                f"🚨 <b>Stop-Loss Triggered!</b>\n\n"
                f"📍 {triggered_option.upper()} option stop-loss activated\n"
                f"🔄 Adjusting remaining position to break-even..."
            )
            
            # Determine remaining option
            remaining_option = 'put' if triggered_option == 'call' else 'call'
            remaining_data = position_data[remaining_option]
            
            # Cancel existing stop-loss for remaining option
            remaining_stop_id = remaining_data.get('stop_order_id')
            if remaining_stop_id:
                cancel_result = await self.delta_client.cancel_order(
                    remaining_stop_id, 
                    remaining_data['product_id']
                )
                
                if cancel_result.get('success'):
                    await self.send_message(chat_id, f"✅ Cancelled existing {remaining_option} stop-loss")
                else:
                    await self.send_message(chat_id, f"⚠️ Failed to cancel {remaining_option} stop-loss")
            
            # Calculate break-even price for remaining position
            break_even_price = await self.delta_client.calculate_break_even_price(
                position_data, triggered_option
            )
            
            if break_even_price > 0:
                # Place new stop-loss at break-even price
                new_stop_result = await self.delta_client.place_stop_order(
                    product_id=remaining_data['product_id'],
                    side='buy',  # Buy to close short position
                    size=1,
                    stop_price=str(break_even_price),
                    order_type='stop_limit_order',
                    limit_price=str(break_even_price * 1.01)  # 1% slippage for execution
                )
                
                if new_stop_result.get('success'):
                    # Update position data
                    position_data[remaining_option]['stop_order_id'] = new_stop_result['result']['id']
                    position_data[remaining_option]['break_even_stop'] = break_even_price
                    position_data['status'] = 'break_even_adjusted'
                    
                    await self.send_message(
                        chat_id,
                        f"✅ <b>Break-Even Adjustment Complete!</b>\n\n"
                        f"🎯 New {remaining_option.upper()} stop-loss set at: ${break_even_price:.2f}\n"
                        f"💡 Position now protected at break-even level\n"
                        f"📊 Risk minimized successfully!"
                    )
                else:
                    await self.send_message(
                        chat_id,
                        f"❌ Failed to set break-even stop: {new_stop_result.get('error', {}).get('message', 'Unknown error')}"
                    )
            else:
                await self.send_message(chat_id, "❌ Could not calculate break-even price")
                
        except Exception as e:
            logger.error(f"Error handling stop trigger: {e}")
            await self.send_message(chat_id, f"❌ Error adjusting position: {str(e)}")
    
    async def execute_short_straddle(self, chat_id: int) -> str:
        """Execute short straddle strategy with enhanced debugging"""
        try:
            position_id = f"straddle_{int(time.time())}"
            
            # Get BTC spot price
            spot_price = await self.delta_client.get_spot_price()
            if spot_price == 0:
                return "❌ Failed to get BTC spot price"
            
            await self.send_message(chat_id, f"📊 BTC Spot Price: ${spot_price:,.2f}")
            
            # Debug: Check available expiry dates
            today = datetime.now().strftime("%d-%m-%Y")
            await self.send_message(chat_id, f"🔍 Looking for options expiring on: {today}")
            
            # Find ATM options with enhanced error reporting
            atm_options = await self.delta_client.find_atm_options(spot_price)
            call_option = atm_options['call']
            put_option = atm_options['put']
            
            if not call_option and not put_option:
                # Try to get available expiry dates for debugging
                products = await self.delta_client._make_request('GET', '/products', {
                    'contract_types': 'call_options,put_options'
                })
                
                available_dates = set()
                if products.get('success'):
                    for product in products['result'][:10]:  # Check first 10 products
                        if product['underlying_asset']['symbol'] == 'BTC':
                            settlement_time = product.get('settlement_time')
                            if settlement_time:
                                try:
                                    settlement_date = datetime.fromisoformat(settlement_time.replace('Z', '+00:00'))
                                    available_dates.add(settlement_date.strftime("%d-%m-%Y"))
                                except:
                                    pass
                
                dates_str = ", ".join(list(available_dates)[:5]) if available_dates else "None found"
                return f"❌ No ATM options found for {today}\n\n📅 Available expiry dates: {dates_str}\n\n💡 Try using weekly (W1) or daily (D1) options instead"
            
            if not call_option:
                return f"❌ ATM call option not found for same day expiry\n📊 Spot: ${spot_price:,.2f}"
                
            if not put_option:
                return f"❌ ATM put option not found for same day expiry\n📊 Spot: ${spot_price:,.2f}"
            
            await self.send_message(chat_id, 
                f"🎯 Found ATM Options:\n"
                f"📞 Call: {call_option['symbol']} (Strike: ${call_option['strike_price']})\n"
                f"📞 Put: {put_option['symbol']} (Strike: ${put_option['strike_price']})"
            )
            
            # Execute short straddle (sell call and put)
            results = []
            call_data = {'product_id': call_option['id'], 'strike_price': call_option.get('strike_price', 0)}
            put_data = {'product_id': put_option['id'], 'strike_price': put_option.get('strike_price', 0)}
            
            # Sell Call Option (1 lot)
            call_result = await self.delta_client.place_order(
                product_id=call_option['id'],
                side='sell',
                size=1,
                order_type='market_order'
            )
            
            if call_result.get('success'):
                call_order = call_result['result']
                call_data.update({
                    'order_id': call_order['id'],
                    'premium_received': call_order.get('limit_price', 0)
                })
                results.append(f"✅ Call Option Sold: {call_option['symbol']}")
                
                # Calculate 25% premium increase for stop-loss
                call_price = float(call_order.get('limit_price', 0))
                call_stop_price = call_price * 1.25  # 25% increase
                
                # Place stop-loss for call
                stop_result = await self.delta_client.place_stop_order(
                    product_id=call_option['id'],
                    side='buy',  # Buy to close short position
                    size=1,
                    stop_price=str(call_stop_price),
                    order_type='stop_limit_order',
                    limit_price=str(call_stop_price * 1.02)  # 2% slippage
                )
                
                if stop_result.get('success'):
                    call_data['stop_order_id'] = stop_result['result']['id']
                    call_data['stop_price'] = call_stop_price
                    results.append(f"🛡️ Call Stop-Loss placed at ${call_stop_price:.2f}")
                else:
                    results.append(f"⚠️ Call Stop-Loss failed: {stop_result.get('error', {}).get('message', 'Unknown error')}")
            else:
                results.append(f"❌ Call Option failed: {call_result.get('error', {}).get('message', 'Unknown error')}")
            
            # Sell Put Option (1 lot)
            put_result = await self.delta_client.place_order(
                product_id=put_option['id'],
                side='sell',
                size=1,
                order_type='market_order'
            )
            
            if put_result.get('success'):
                put_order = put_result['result']
                put_data.update({
                    'order_id': put_order['id'],
                    'premium_received': put_order.get('limit_price', 0)
                })
                results.append(f"✅ Put Option Sold: {put_option['symbol']}")
                
                # Calculate 25% premium increase for stop-loss
                put_price = float(put_order.get('limit_price', 0))
                put_stop_price = put_price * 1.25  # 25% increase
                
                # Place stop-loss for put
                stop_result = await self.delta_client.place_stop_order(
                    product_id=put_option['id'],
                    side='buy',  # Buy to close short position
                    size=1,
                    stop_price=str(put_stop_price),
                    order_type='stop_limit_order',
                    limit_price=str(put_stop_price * 1.02)  # 2% slippage
                )
                
                if stop_result.get('success'):
                    put_data['stop_order_id'] = stop_result['result']['id']
                    put_data['stop_price'] = put_stop_price
                    results.append(f"🛡️ Put Stop-Loss placed at ${put_stop_price:.2f}")
                else:
                    results.append(f"⚠️ Put Stop-Loss failed: {stop_result.get('error', {}).get('message', 'Unknown error')}")
            else:
                results.append(f"❌ Put Option failed: {put_result.get('error', {}).get('message', 'Unknown error')}")
            
            # Track the position for monitoring
            self.order_tracker.add_position(position_id, call_data, put_data)
            
            # Start monitoring task
            monitoring_task = asyncio.create_task(
                self.monitor_stop_orders(position_id, chat_id)
            )
            self.order_tracker.monitoring_tasks[position_id] = monitoring_task
            
            results.append(f"\n🔍 <b>Monitoring Active</b>\n📋 Position ID: {position_id}")
            results.append("🤖 Auto break-even adjustment enabled")
            
            return "\n".join(results)
            
        except Exception as e:
            logger.error(f"Short straddle execution failed: {e}")
            return f"❌ Strategy execution failed: {str(e)}"

# Global instances
delta_client = None
telegram_bot = None

async def handle_webhook(request: Request) -> Response:
    """Handle Telegram webhook"""
    try:
        data = await request.json()
        logger.info(f"Received webhook: {data}")
        
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            
            if text == '/start':
                keyboard = {
                    'inline_keyboard': [[
                        {'text': '🚀 Execute Short Straddle', 'callback_data': 'execute_straddle'}
                    ], [
                        {'text': '📊 Check Positions', 'callback_data': 'check_positions'}
                    ]]
                }
                await telegram_bot.send_message(
                    chat_id,
                    "🤖 <b>Enhanced BTC Short Straddle Bot</b>\n\n"
                    "This bot executes a short straddle strategy with smart risk management:\n"
                    "• Sells 1 lot ATM Call & Put options\n"
                    "• Places 25% premium stop-loss orders\n"
                    "• <b>Auto break-even adjustment</b> when one stop triggers\n"
                    "• Continuous position monitoring\n\n"
                    "Click below to get started:",
                    keyboard
                )
            elif text == '/help':
                await telegram_bot.send_message(
                    chat_id,
                    "📋 <b>Enhanced Bot Commands:</b>\n\n"
                    "/start - Show main menu\n"
                    "/help - Show this help message\n"
                    "/status - Check bot status\n"
                    "/positions - View active positions\n\n"
                    "<b>Smart Features:</b>\n"
                    "🎯 Auto break-even adjustment\n"
                    "📊 Real-time position monitoring\n"
                    "🛡️ Advanced risk management\n"
                    "⚡ Instant stop-loss notifications"
                )
            elif text == '/status':
                spot_price = await delta_client.get_spot_price()
                active_count = len([p for p in telegram_bot.order_tracker.active_positions.values() 
                                 if p['status'] in ['active', 'adjusting', 'break_even_adjusted']])
                await telegram_bot.send_message(
                    chat_id,
                    f"✅ <b>Enhanced Bot Status: Active</b>\n\n"
                    f"🔗 Connected to Delta Exchange India\n"
                    f"📊 Current BTC Price: ${spot_price:,.2f}\n"
                    f"📈 Active Positions: {active_count}\n"
                    f"🤖 Monitoring Tasks Running\n"
                    f"⏰ Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )
            elif text == '/positions':
                positions_text = "📊 <b>Active Positions:</b>\n\n"
                if not telegram_bot.order_tracker.active_positions:
                    positions_text += "No active positions"
                else:
                    for pid, pos in telegram_bot.order_tracker.active_positions.items():
                        positions_text += f"🆔 {pid}\n"
                        positions_text += f"📍 Status: {pos['status']}\n"
                        positions_text += f"⏰ Created: {pos['created_at'].strftime('%H:%M:%S')}\n"
                        if pos.get('stop_triggered'):
                            positions_text += f"🚨 Stop Triggered: {pos['stop_triggered'].upper()}\n"
                        positions_text += "━━━━━━━━━━━━━━\n"
                        
                await telegram_bot.send_message(chat_id, positions_text)
        
        elif 'callback_query' in data:
            callback = data['callback_query']
            chat_id = callback['message']['chat']['id']
            callback_data = callback['data']
            
            if callback_data == 'execute_straddle':
                await telegram_bot.send_message(chat_id, "⚡ Executing Enhanced Short Straddle Strategy...")
                result = await telegram_bot.execute_short_straddle(chat_id)
                await telegram_bot.send_message(chat_id, result)
            elif callback_data == 'check_positions':
                positions_text = "📊 <b>Position Summary:</b>\n\n"
                if not telegram_bot.order_tracker.active_positions:
                    positions_text += "No active positions"
                else:
                    for pid, pos in telegram_bot.order_tracker.active_positions.items():
                        positions_text += f"🆔 {pid[:12]}...\n"
                        positions_text += f"📍 {pos['status']}\n━━━━━━━━━━━━━━\n"
                        
                await telegram_bot.send_message(chat_id, positions_text)
        
        return json_response({'status': 'ok'})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return json_response({'status': 'error', 'message': str(e)})

async def health_check(request: Request) -> Response:
    """Health check endpoint"""
    return json_response({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'enhanced-btc-straddle-bot',
        'features': ['break_even_adjustment', 'position_monitoring', 'smart_risk_management']
    })

async def init_app() -> web.Application:
    """Initialize the web application"""
    global delta_client, telegram_bot
    
    # Get environment variables
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    api_key = os.getenv('DELTA_API_KEY')
    api_secret = os.getenv('DELTA_API_SECRET')
    webhook_url = os.getenv('WEBHOOK_URL')
    
    if not all([bot_token, api_key, api_secret]):
        raise ValueError("Missing required environment variables")
    
    # Initialize clients
    delta_client = DeltaExchangeClient(api_key, api_secret)
    telegram_bot = TelegramBot(bot_token, delta_client)
    
    # Set webhook if URL provided
    if webhook_url:
        webhook_endpoint = f"{webhook_url}/webhook"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{bot_token}/setWebhook",
                json={'url': webhook_endpoint}
            ) as response:
                if response.status == 200:
                    logger.info(f"Webhook set successfully: {webhook_endpoint}")
                else:
                    logger.warning(f"Failed to set webhook: {response.status}")
    
    # Create web application
    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)  # Root endpoint for health checks
    
    return app

async def main():
    """Main function"""
    app = await init_app()
    
    # Get port from environment
    port = int(os.getenv('PORT', 10000))
    
    # Start the web server
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"🚀 Enhanced BTC Short Straddle Bot started on port {port}")
    logger.info("🤖 Smart risk management and break-even adjustment active!")
    
    # Keep the server running
    try:
        await asyncio.Future()  # Run forever
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await runner.cleanup()
        if delta_client and delta_client.session:
            await delta_client.session.close()

if __name__ == '__main__':
    asyncio.run(main())
