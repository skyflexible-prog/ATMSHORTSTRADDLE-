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
    
    def place_market_sell_order(self, product_id: int, size: int) -> Dict:
        """Place a market sell order for immediate execution"""
        order_data = {
            'product_id': product_id,
            'side': 'sell',
            'size': size,
            'order_type': 'market_order'
        }
        
        return self.make_request('POST', '/v2/orders', data=order_data)
    
    def place_bracket_order(self, product_id: int, size: int, entry_price: float, stop_loss_percentage: float = 25.0) -> Dict:
        """Place bracket order with stop-loss for short position"""
        # Calculate stop-loss price (25% premium increase for short position)
        stop_loss_price = entry_price * (1 + stop_loss_percentage / 100)
        stop_loss_limit_price = stop_loss_price * 1.02  # 2% buffer for limit price
        
        bracket_data = {
            'product_id': product_id,
            'stop_loss_order': {
                'order_type': 'stop_limit_order',
                'stop_price': str(stop_loss_price),
                'limit_price': str(stop_loss_limit_price)
            },
            'bracket_stop_trigger_method': 'mark_price'
        }
        
        return self.make_request('POST', '/v2/orders/bracket', data=bracket_data)
    
    def place_market_order_with_bracket(self, product_id: int, size: int, current_price: float) -> Dict:
        """Place market order and immediately set up bracket order"""
        # First place the market order
        market_order = self.place_market_sell_order(product_id, size)
        
        if not market_order.get('success'):
            return market_order
        
        # Wait a moment for order to be filled
        time.sleep(1)
        
        # Place bracket order for position
        bracket_order = self.place_bracket_order(product_id, size, current_price, 25.0)
        
        return {
            'success': True,
            'market_order': market_order,
            'bracket_order': bracket_order
        }
    
    def execute_short_straddle_market(self, lot_size: int = 1) -> Dict:
        """Execute short straddle strategy with market orders and bracket stop-loss"""
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
                'orders': [],
                'bracket_orders': []
            }
            
            # Execute short call with market order
            call_price = float(atm_call['mark_price'])
            call_result = self.place_market_order_with_bracket(
                atm_call['product_id'], 
                lot_size, 
                call_price
            )
            
            if call_result.get('success'):
                results['orders'].append({
                    'type': 'short_call_market',
                    'order_id': call_result['market_order']['result']['id'],
                    'symbol': atm_call['symbol'],
                    'price': call_price,
                    'executed': 'market_order'
                })
                
                if call_result['bracket_order'].get('success'):
                    stop_price = call_price * 1.25  # 25% stop-loss
                    results['bracket_orders'].append({
                        'type': 'call_bracket',
                        'product_id': atm_call['product_id'],
                        'stop_price': stop_price,
                        'status': 'active'
                    })
                else:
                    results['bracket_orders'].append({
                        'type': 'call_bracket',
                        'status': 'failed',
                        'error': call_result['bracket_order'].get('error', 'Unknown error')
                    })
            
            # Execute short put with market order
            put_price = float(atm_put['mark_price'])
            put_result = self.place_market_order_with_bracket(
                atm_put['product_id'], 
                lot_size, 
                put_price
            )
            
            if put_result.get('success'):
                results['orders'].append({
                    'type': 'short_put_market',
                    'order_id': put_result['market_order']['result']['id'],
                    'symbol': atm_put['symbol'],
                    'price': put_price,
                    'executed': 'market_order'
                })
                
                if put_result['bracket_order'].get('success'):
                    stop_price = put_price * 1.25  # 25% stop-loss
                    results['bracket_orders'].append({
                        'type': 'put_bracket',
                        'product_id': atm_put['product_id'],
                        'stop_price': stop_price,
                        'status': 'active'
                    })
                else:
                    results['bracket_orders'].append({
                        'type': 'put_bracket',
                        'status': 'failed',
                        'error': put_result['bracket_order'].get('error', 'Unknown error')
                    })
            
            return results
            
        except Exception as e:
            return {'success': False, 'error': f'Strategy execution failed: {str(e)}'}
    
    def get_open_positions(self) -> Dict:
        """Get all open positions"""
        return self.make_request('GET', '/v2/positions')
    
    def get_bracket_orders(self) -> Dict:
        """Get all bracket orders"""
        return self.make_request('GET', '/v2/orders/bracket')
    
    def cancel_bracket_order(self, product_id: int) -> Dict:
        """Cancel bracket order for a specific product"""
        data = {'product_id': product_id}
        return self.make_request('DELETE', '/v2/orders/bracket', data=data)
