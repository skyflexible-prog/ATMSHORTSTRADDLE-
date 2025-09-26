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
        today = time.strftime('%d-%m-%Y')
        
        # Get call options
        call_params = {
            'contract_types': 'call_options',
            'underlying_asset_symbols': underlying_asset,
            'expiry_date': today
        }
        call_response = self.make_request('GET', '/v2/tickers', params=call_params)
        
        # Get put options
        put_params = {
            'contract_types': 'put_options',
            'underlying_asset_symbols': underlying_asset,
            'expiry_date': today
        }
        put_response = self.make_request('GET', '/v2/tickers', params=put_params)
        
        calls = call_response.get('result', []) if call_response.get('success') else []
        puts = put_response.get('result', []) if put_response.get('success') else []
        
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
    
    def place_stop_loss_order(self, product_id: int, size: int, stop_price: str, limit_price: str) -> Dict:
        """Place a stop-limit buy order for closing short position"""
        order_data = {
            'product_id': product_id,
            'side': 'buy',
            'size': size,
            'order_type': 'stop_limit_order',
            'stop_price': stop_price,
            'limit_price': limit_price,
            'time_in_force': 'gtc',
            'reduce_only': True
        }
        
        return self.make_request('POST', '/v2/orders', data=order_data)
    
    def execute_short_straddle(self, lot_size: int = 1) -> Dict:
        """Execute short straddle strategy with automatic stop-loss"""
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
            
            results = {
                'success': True,
                'spot_price': spot_price,
                'strike_price': float(atm_call['strike_price']),
                'orders': []
            }
            
            # Execute short call
            call_price = float(atm_call['mark_price'])
            call_order = self.place_sell_order(
                atm_call['product_id'], 
                lot_size, 
                str(call_price)
            )
            
            if call_order.get('success'):
                results['orders'].append({
                    'type': 'short_call',
                    'order_id': call_order['result']['id'],
                    'symbol': atm_call['symbol'],
                    'price': call_price
                })
                
                # Place stop-loss for call
                call_stop_price = call_price * (1 + 0.25)  # 25% premium increase
                call_stop_order = self.place_stop_loss_order(
                    atm_call['product_id'],
                    lot_size,
                    str(call_stop_price),
                    str(call_stop_price * 1.02)  # Slight buffer for limit price
                )
                
                if call_stop_order.get('success'):
                    results['orders'].append({
                        'type': 'call_stop_loss',
                        'order_id': call_stop_order['result']['id'],
                        'stop_price': call_stop_price
                    })
            
            # Execute short put
            put_price = float(atm_put['mark_price'])
            put_order = self.place_sell_order(
                atm_put['product_id'], 
                lot_size, 
                str(put_price)
            )
            
            if put_order.get('success'):
                results['orders'].append({
                    'type': 'short_put',
                    'order_id': put_order['result']['id'],
                    'symbol': atm_put['symbol'],
                    'price': put_price
                })
                
                # Place stop-loss for put
                put_stop_price = put_price * (1 + 0.25)  # 25% premium increase
                put_stop_order = self.place_stop_loss_order(
                    atm_put['product_id'],
                    lot_size,
                    str(put_stop_price),
                    str(put_stop_price * 1.02)  # Slight buffer for limit price
                )
                
                if put_stop_order.get('success'):
                    results['orders'].append({
                        'type': 'put_stop_loss',
                        'order_id': put_stop_order['result']['id'],
                        'stop_price': put_stop_price
                    })
            
            return results
            
        except Exception as e:
            return {'success': False, 'error': f'Strategy execution failed: {str(e)}'}
    
    def get_open_orders(self) -> Dict:
        """Get all open orders"""
        params = {'state': 'open'}
        return self.make_request('GET', '/v2/orders', params=params)
    
    def cancel_order(self, product_id: int, order_id: int) -> Dict:
        """Cancel a specific order"""
        return self.make_request('DELETE', f'/v2/orders/{order_id}')
                                           
