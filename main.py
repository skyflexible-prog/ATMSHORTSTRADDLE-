import os
import asyncio
import logging
import json
import time
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
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

class DeltaExchangeClient:
    """Delta Exchange India API Client"""
    
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
        """Find ATM call and put options for same day expiry (D1)"""
    try:
        # Get today's date in DD-MM-YYYY format for API filtering
        today = datetime.now().strftime("%d-%m-%Y")
        
        # Get BTC options for today's expiry
        products = await self._make_request('GET', '/products', {
            'contract_types': 'call_options,put_options',
            'underlying_asset_symbols': 'BTC',
            'expiry_date': today  # Filter by today's date
        })
        
        if not products.get('success') or not products.get('result'):
            logger.warning("No products found for today's expiry")
            return {'call': None, 'put': None}
        
        call_options = []
        put_options = []
        
        # Separate call and put options
        for product in products['result']:
            if product['underlying_asset']['symbol'] == 'BTC':
                strike_price = float(product.get('strike_price', 0))
                if product['contract_type'] == 'call_options':
                    call_options.append((product, strike_price))
                elif product['contract_type'] == 'put_options':
                    put_options.append((product, strike_price))
        
        # Find ATM call option (closest strike to spot price)
        call_option = None
        if call_options:
            call_option = min(call_options, key=lambda x: abs(x[1] - spot_price))[0]
        
        # Find ATM put option (closest strike to spot price)
        put_option = None
        if put_options:
            put_option = min(put_options, key=lambda x: abs(x[1] - spot_price))[0]
        
        logger.info(f"Found ATM options - Call: {call_option['symbol'] if call_option else 'None'}, Put: {put_option['symbol'] if put_option else 'None'}")
        
        return {'call': call_option, 'put': put_option}
        
    except Exception as e:
        logger.error(f"Failed to find ATM options: {e}")
        return {'call': None, 'put': None}

            
    
    async def place_order(self, product_id: int, side: str, size: int, 
                         order_type: str = "market_order") -> Dict:
        """Place an order"""
        data = {
            'product_id': product_id,
            'side': side,
            'size': size,
            'order_type': order_type
        }
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
    """Telegram Bot Handler"""
    
    def __init__(self, bot_token: str, delta_client: DeltaExchangeClient):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.delta_client = delta_client
        
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
    
    async def execute_short_straddle(self, chat_id: int) -> str:
        """Execute short straddle strategy"""
        try:
            # Get BTC spot price
            spot_price = await self.delta_client.get_spot_price()
            if spot_price == 0:
                return "❌ Failed to get BTC spot price"
            
            await self.send_message(chat_id, f"📊 BTC Spot Price: ${spot_price:,.2f}")
            
            # Find ATM options
            atm_options = await self.delta_client.find_atm_options(spot_price)
            call_option = atm_options['call']
            put_option = atm_options['put']
            
            if not call_option or not put_option:
                return "❌ ATM options not found for same day expiry"
            
            await self.send_message(chat_id, 
                f"🎯 Found ATM Options:\n"
                f"📞 Call: {call_option['symbol']} (Strike: ${call_option.get('strike_price', 'N/A')})\n"
                f"📞 Put: {put_option['symbol']} (Strike: ${put_option.get('strike_price', 'N/A')})"
            )
            
            # Execute short straddle (sell call and put)
            results = []
            
            # Sell Call Option (1 lot)
            call_result = await self.delta_client.place_order(
                product_id=call_option['id'],
                side='sell',
                size=1,
                order_type='market_order'
            )
            
            if call_result.get('success'):
                call_order = call_result['result']
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
                    results.append(f"🛡️ Put Stop-Loss placed at ${put_stop_price:.2f}")
                else:
                    results.append(f"⚠️ Put Stop-Loss failed: {stop_result.get('error', {}).get('message', 'Unknown error')}")
            else:
                results.append(f"❌ Put Option failed: {put_result.get('error', {}).get('message', 'Unknown error')}")
            
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
                    ]]
                }
                await telegram_bot.send_message(
                    chat_id,
                    "🤖 <b>BTC Short Straddle Bot</b>\n\n"
                    "This bot executes a short straddle strategy on BTC options:\n"
                    "• Sells 1 lot ATM Call option\n"
                    "• Sells 1 lot ATM Put option\n"
                    "• Places 25% premium stop-loss orders\n\n"
                    "Click the button below to execute the strategy:",
                    keyboard
                )
            elif text == '/help':
                await telegram_bot.send_message(
                    chat_id,
                    "📋 <b>Bot Commands:</b>\n\n"
                    "/start - Show main menu\n"
                    "/help - Show this help message\n"
                    "/status - Check bot status\n\n"
                    "<b>Strategy Details:</b>\n"
                    "• Short Straddle on BTC same-day expiry ATM options\n"
                    "• 1 lot each for Call and Put\n"
                    "• Automatic 25% premium stop-loss orders"
                )
            elif text == '/status':
                spot_price = await delta_client.get_spot_price()
                await telegram_bot.send_message(
                    chat_id,
                    f"✅ <b>Bot Status: Active</b>\n\n"
                    f"🔗 Connected to Delta Exchange India\n"
                    f"📊 Current BTC Price: ${spot_price:,.2f}\n"
                    f"⏰ Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )
        
        elif 'callback_query' in data:
            callback = data['callback_query']
            chat_id = callback['message']['chat']['id']
            callback_data = callback['data']
            
            if callback_data == 'execute_straddle':
                await telegram_bot.send_message(chat_id, "⚡ Executing Short Straddle Strategy...")
                result = await telegram_bot.execute_short_straddle(chat_id)
                await telegram_bot.send_message(chat_id, result)
        
        return json_response({'status': 'ok'})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return json_response({'status': 'error', 'message': str(e)})

async def health_check(request: Request) -> Response:
    """Health check endpoint"""
    return json_response({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'btc-straddle-bot'
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
    
    logger.info(f"🚀 BTC Short Straddle Bot started on port {port}")
    logger.info("Bot is ready to receive webhooks!")
    
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
