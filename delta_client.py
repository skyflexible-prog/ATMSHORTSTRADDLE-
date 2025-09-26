import hashlib
import hmac
import time
import json
import requests
from typing import Dict, List, Optional, Tuple
from config import DELTA_API_KEY, DELTA_API_SECRET, DELTA_BASE_URL

class DeltaExchangeClient:
    def __init__(self):
        self.base_url = DELTA_BASE_URL
        self.api_key = DELTA_API_KEY
        self.api_secret = DELTA_API_SECRET
    
    def generate_signature(self, secret: str, message: str) -> str:
        """Generate HMAC SHA256 signature for API authentication"""
        message_bytes = bytes(message, 'utf-8')
        secret_bytes = bytes(secret, 'utf-8')
        hash_obj = hmac.new(secret_bytes, message_bytes, hashlib.sha256)
        return hash_obj.hexdigest()
    
    def make_request(self, method: str, path: str, params: Dict = None, data: Dict = None) -> Dict:
        """Make authenticated request to Delta Exchange API"""
        timestamp = str(int(time.time()))
        url = f'{self.base_url}{path}'
        
        # Prepare query string and payload
        query_string = ''
        if params:
            query_string = '?' + '&'.join([f'{k}={v}' for k, v in params.items()])
            
        payload = ''
        if data:
            payload = json.dumps(data)
        
        # Create signature
        signature_data = method + timestamp + path + query_string + payload
        signature = self.generate_signature(self.api_secret, signature_data)
        
        # Prepare headers
        headers = {
            'api-key': self.api_key,
            'timestamp': timestamp,
            'signature': signature,
            'User-Agent': 'python-rest-client',
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.request(
                method, url, 
                params=params, 
                data=payload if data else None, 
                headers=headers, 
                timeout=(3, 27)
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {'success': False, 'error': str(e)}
    
    def get_btc_spot_price(self) -> float:
        """Get current BTC spot price"""
        response = self.make_request('GET', '/v2/tickers/BTCUSD')
        if response.get('success') and 'result' in response:
            return float(response['result']['spot_price'])
        return 0.0
    
    def get_same_day_options(self, underlying_asset: str = 'BTC') -> Tuple[List[Dict], List[Dict]]:
        """Get same day expiry BTC options"""
        today = time.strftime('%d%b%y').upper()  # Format: 26SEP25
        
        # Get all products for BTC options
        response = self.make_request('GET', '/v2/products')
        if not response.get('success'):
            return [], []
        
        all_products = response.get('result', [])
        calls = []
        puts = []
        
        for product in all_products:
            if (product.get('underlying_asset', {}).get('symbol') == underlying_asset and 
                product.get('product_type') == 'options' and
                today in product.get('symbol', '')):
                
                if product.get('option_type') == 'call_option':
                    calls.append(product)
                elif product.get('option_type') == 'put_option':
                    puts.append(product)
        
        return calls, puts
    
    def find_atm_strikes(self, spot_price: float, calls: List[Dict], puts: List[Dict]) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Find ATM (At The Money) call and put options closest to spot price"""
        atm_call = None
        atm_put = None
        min_diff = float('inf')
        
        for call in calls:
            if 'strike_price' in call:
                strike_diff = abs(float(call['strike_price']) - spot_price)
                if strike_diff < min_diff:
                    min_diff = strike_diff
                    atm_call = call
        
        if atm_call:
            strike_price = float(atm_call['strike_price'])
            for put in puts:
                if 'strike_price' in put and abs(float(put['strike_price']) - strike_price) < 0.01:
                    atm_put = put
                    break
        
        return atm_call, atm_put
    
    def get_option_ticker(self, product_id: int) -> Dict:
        """Get ticker data for a specific option product"""
        response = self.make_request('GET', f'/v2/tickers/{product_id}')
        return response.get('result', {}) if response.get('success') else {}
    
    def place_sell_order(self, product_id: int, size: int, limit_price: str) -> Dict:
        """Place a sell order (short position)"""
        order_data = {
            'product_id': product_id,
            'side': 'sell',
            'size': size,
            'order_type': 'limit_order',
            'limit_price': limit_price,
            'time_in_force': 'gtc'
        }
        
        return self.make_request('POST', '/v2/orders', data=order_data)
    
    def place_stop_loss_order(self, product_id: int, size: int, entry_price: float, 
                            premium_increase_percent: float = 25.0) -> Dict:
        """
        Place a stop-limit buy order for closing short position with 25% premium increase trigger
        
        Args:
            product_id: Option product ID
            size: Order size (should be positive for closing short position)
            entry_price: Original premium received when selling
            premium_increase_percent: Percentage increase in premium to trigger stop-loss (default 25%)
        """
        try:
            # Calculate stop price (25% increase from entry premium)
            stop_price = entry_price * (1 + premium_increase_percent / 100)
            
            # Set limit price slightly higher than stop price to ensure execution
            limit_price = stop_price * 1.02  # 2% buffer above stop price
            
            order_data = {
                'product_id': product_id,
                'side': 'buy',  # Buy to close short position
                'size': size,
                'order_type': 'stop_limit_order',
                'stop_price': f'{stop_price:.2f}',
                'limit_price': f'{limit_price:.2f}',
                'time_in_force': 'gtc',
                'reduce_only': True  # Ensures this only closes existing position
            }
            
            response = self.make_request('POST', '/v2/orders', data=order_data)
            
            if response.get('success'):
                return {
                    'success': True,
                    'order_id': response['result']['id'],
                    'stop_price': stop_price,
                    'limit_price': limit_price,
                    'entry_price': entry_price,
                    'premium_increase_percent': premium_increase_percent
                }
            else:
                return {
                    'success': False,
                    'error': response.get('error', 'Unknown error placing stop-loss')
                }
                
        except Exception as e:
            return {'success': False, 'error': f'Stop-loss order failed: {str(e)}'}
    
    def place_trailing_stop_loss(self, product_id: int, size: int, trail_amount: float) -> Dict:
        """
        Place a trailing stop-loss order
        
        Args:
            product_id: Option product ID  
            size: Order size
            trail_amount: Trail amount in points
        """
        order_data = {
            'product_id': product_id,
            'side': 'buy',
            'size': size,
            'order_type': 'market_order',
            'trail_amount': f'{trail_amount:.2f}',
            'time_in_force': 'gtc',
            'reduce_only': True,
            'is_trailing_stop_loss': True
        }
        
        return self.make_request('POST', '/v2/orders', data=order_data)
    
    def execute_short_straddle_with_enhanced_stop_loss(self, lot_size: int = 1) -> Dict:
        """Execute short straddle strategy with enhanced 25% premium increase stop-loss"""
        try:
            # Get BTC spot price
            spot_price = self.get_btc_spot_price()
            if spot_price <= 0:
                return {'success': False, 'error': 'Unable to fetch BTC spot price'}
            
            # Get same day options
            calls, puts = self.get_same_day_options()
            if not calls or not puts:
                return {'success': False, 'error': 'No same day expiry options available'}
            
            # Find ATM options
            atm_call, atm_put = self.find_atm_strikes(spot_price, calls, puts)
            if not atm_call or not atm_put:
                return {'success': False, 'error': 'Unable to find ATM options'}
            
            # Get current market prices
            call_ticker = self.get_option_ticker(atm_call['id'])
            put_ticker = self.get_option_ticker(atm_put['id'])
            
            if not call_ticker or not put_ticker:
                return {'success': False, 'error': 'Unable to fetch option prices'}
            
            call_price = float(call_ticker.get('mark_price', 0))
            put_price = float(put_ticker.get('mark_price', 0))
            
            if call_price <= 0 or put_price <= 0:
                return {'success': False, 'error': 'Invalid option prices'}
            
            results = {
                'success': True,
                'spot_price': spot_price,
                'strike_price': float(atm_call['strike_price']),
                'call_premium': call_price,
                'put_premium': put_price,
                'total_premium_received': call_price + put_price,
                'orders': []
            }
            
            # Execute short call
            call_order = self.place_sell_order(
                atm_call['id'], 
                lot_size, 
                f'{call_price:.2f}'
            )
            
            if call_order.get('success'):
                results['orders'].append({
                    'type': 'short_call',
                    'order_id': call_order['result']['id'],
                    'symbol': atm_call['symbol'],
                    'price': call_price,
                    'size': lot_size
                })
                
                # Place enhanced stop-loss for call with 25% premium increase
                call_stop_order = self.place_stop_loss_order(
                    atm_call['id'],
                    lot_size,
                    call_price,  # Entry price (premium received)
                    25.0  # 25% premium increase
                )
                
                if call_stop_order.get('success'):
                    results['orders'].append({
                        'type': 'call_stop_loss',
                        'order_id': call_stop_order['order_id'],
                        'stop_price': call_stop_order['stop_price'],
                        'limit_price': call_stop_order['limit_price'],
                        'entry_price': call_price,
                        'trigger_condition': '25% premium increase'
                    })
                else:
                    results['orders'].append({
                        'type': 'call_stop_loss_failed',
                        'error': call_stop_order.get('error')
                    })
            
            # Execute short put
            put_order = self.place_sell_order(
                atm_put['id'], 
                lot_size, 
                f'{put_price:.2f}'
            )
            
            if put_order.get('success'):
                results['orders'].append({
                    'type': 'short_put',
                    'order_id': put_order['result']['id'],
                    'symbol': atm_put['symbol'],
                    'price': put_price,
                    'size': lot_size
                })
                
                # Place enhanced stop-loss for put with 25% premium increase
                put_stop_order = self.place_stop_loss_order(
                    atm_put['id'],
                    lot_size,
                    put_price,  # Entry price (premium received)
                    25.0  # 25% premium increase
                )
                
                if put_stop_order.get('success'):
                    results['orders'].append({
                        'type': 'put_stop_loss',
                        'order_id': put_stop_order['order_id'],
                        'stop_price': put_stop_order['stop_price'],
                        'limit_price': put_stop_order['limit_price'],
                        'entry_price': put_price,
                        'trigger_condition': '25% premium increase'
                    })
                else:
                    results['orders'].append({
                        'type': 'put_stop_loss_failed',
                        'error': put_stop_order.get('error')
                    })
            
            # Calculate risk metrics
            max_profit = call_price + put_price  # Premium received
            call_stop_loss = call_price * 1.25  # 25% increase
            put_stop_loss = put_price * 1.25   # 25% increase
            max_loss_per_leg = max(call_stop_loss - call_price, put_stop_loss - put_price)
            
            results['risk_metrics'] = {
                'max_profit': max_profit,
                'call_stop_loss_trigger': call_stop_loss,
                'put_stop_loss_trigger': put_stop_loss,
                'estimated_max_loss_per_leg': max_loss_per_leg,
                'profit_target': max_profit * 0.5,  # 50% of premium as target
                'break_even_upper': float(atm_call['strike_price']) + max_profit,
                'break_even_lower': float(atm_call['strike_price']) - max_profit
            }
            
            return results
            
        except Exception as e:
            return {'success': False, 'error': f'Enhanced strategy execution failed: {str(e)}'}
    
    def get_open_orders(self) -> Dict:
        """Get all open orders"""
        params = {'state': 'open'}
        return self.make_request('GET', '/v2/orders', params=params)
    
    def cancel_order(self, order_id: int) -> Dict:
        """Cancel a specific order"""
        return self.make_request('DELETE', f'/v2/orders/{order_id}')
    
    def modify_stop_loss_order(self, order_id: int, new_stop_price: float, new_limit_price: float) -> Dict:
        """Modify existing stop-loss order"""
        order_data = {
            'stop_price': f'{new_stop_price:.2f}',
            'limit_price': f'{new_limit_price:.2f}'
        }
        
        return self.make_request('PUT', f'/v2/orders/{order_id}', data=order_data)
