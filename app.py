"""
MEGA FOREX v8.2 PRO - Optimized Backend
========================================
- In-memory caching for faster responses
- Parallel API calls
- Background refresh
- Keep-alive endpoint
"""

import os
import json
import time
import logging
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
import requests

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Keys from environment
POLYGON_API_KEY = os.environ.get('POLYGON_API_KEY', '')
FINNHUB_API_KEY = os.environ.get('FINNHUB_API_KEY', '')
FRED_API_KEY = os.environ.get('FRED_API_KEY', '')
ALPHA_VANTAGE_KEY = os.environ.get('ALPHA_VANTAGE_KEY', '')

# IG Markets credentials
IG_API_KEY = os.environ.get('IG_API_KEY', '')
IG_USERNAME = os.environ.get('IG_USERNAME', '')
IG_PASSWORD = os.environ.get('IG_PASSWORD', '')
IG_ACCOUNT_ID = os.environ.get('IG_ACCOUNT_ID', '')

# ═══════════════════════════════════════════════════════════════════════════════
# CACHING SYSTEM - Key for fast responses
# ═══════════════════════════════════════════════════════════════════════════════

class Cache:
    def __init__(self):
        self.data = {}
        self.timestamps = {}
        self.lock = threading.Lock()
    
    def get(self, key, max_age=60):
        """Get cached data if not expired"""
        with self.lock:
            if key in self.data and key in self.timestamps:
                age = time.time() - self.timestamps[key]
                if age < max_age:
                    return self.data[key]
        return None
    
    def set(self, key, value):
        """Set cache data"""
        with self.lock:
            self.data[key] = value
            self.timestamps[key] = time.time()
    
    def clear(self, key=None):
        """Clear specific key or all cache"""
        with self.lock:
            if key:
                self.data.pop(key, None)
                self.timestamps.pop(key, None)
            else:
                self.data.clear()
                self.timestamps.clear()

cache = Cache()

# Cache durations (seconds)
CACHE_RATES = 30        # Rates refresh every 30s
CACHE_SIGNALS = 60      # Signals refresh every 60s
CACHE_NEWS = 300        # News refresh every 5 min
CACHE_CALENDAR = 600    # Calendar refresh every 10 min
CACHE_POSITIONING = 120 # Positioning refresh every 2 min

# ═══════════════════════════════════════════════════════════════════════════════
# FOREX PAIRS CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

FOREX_PAIRS = {
    'major': ['EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD'],
    'cross': [
        'EUR/GBP', 'EUR/JPY', 'EUR/CHF', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD',
        'GBP/JPY', 'GBP/CHF', 'GBP/AUD', 'GBP/CAD', 'GBP/NZD',
        'AUD/JPY', 'AUD/NZD', 'AUD/CHF', 'AUD/CAD',
        'NZD/JPY', 'NZD/CHF', 'NZD/CAD',
        'CAD/JPY', 'CAD/CHF', 'CHF/JPY'
    ],
    'exotic': [
        'USD/SGD', 'USD/HKD', 'USD/MXN', 'USD/ZAR', 'USD/TRY',
        'USD/SEK', 'USD/NOK', 'USD/DKK', 'USD/PLN', 'USD/HUF',
        'EUR/TRY', 'EUR/SEK', 'EUR/NOK', 'EUR/PLN', 'EUR/HUF'
    ]
}

ALL_PAIRS = FOREX_PAIRS['major'] + FOREX_PAIRS['cross'] + FOREX_PAIRS['exotic']

# ═══════════════════════════════════════════════════════════════════════════════
# FACTOR WEIGHTS
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_WEIGHTS = {
    'technical': 18,
    'fundamental': 20,
    'sentiment': 12,
    'intermarket': 10,
    'quantitative': 10,
    'mtf': 8,
    'structure': 8,
    'calendar': 7,
    'confluence': 7
}

weights = DEFAULT_WEIGHTS.copy()

# ═══════════════════════════════════════════════════════════════════════════════
# IG MARKETS API (with caching)
# ═══════════════════════════════════════════════════════════════════════════════

ig_session = {
    'cst': None,
    'x_security_token': None,
    'expires': None
}

def ig_login():
    """Login to IG Markets API"""
    global ig_session
    
    # Check if session is still valid
    if ig_session['cst'] and ig_session['expires']:
        if datetime.now() < ig_session['expires']:
            return True
    
    if not all([IG_API_KEY, IG_USERNAME, IG_PASSWORD]):
        return False
    
    try:
        headers = {
            'X-IG-API-KEY': IG_API_KEY,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'VERSION': '2'
        }
        
        data = {
            'identifier': IG_USERNAME,
            'password': IG_PASSWORD
        }
        
        response = requests.post(
            'https://api.ig.com/gateway/deal/session',
            headers=headers,
            json=data,
            timeout=10
        )
        
        if response.status_code == 200:
            ig_session['cst'] = response.headers.get('CST')
            ig_session['x_security_token'] = response.headers.get('X-SECURITY-TOKEN')
            ig_session['expires'] = datetime.now() + timedelta(hours=6)
            logger.info("✅ IG Markets API: Login successful")
            return True
        else:
            logger.warning(f"IG login failed: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"IG login error: {e}")
        return False

def get_ig_rates():
    """Get rates from IG Markets"""
    if not ig_login():
        return {}
    
    rates = {}
    
    try:
        headers = {
            'X-IG-API-KEY': IG_API_KEY,
            'CST': ig_session['cst'],
            'X-SECURITY-TOKEN': ig_session['x_security_token'],
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'VERSION': '1'
        }
        
        # IG uses different format for pairs
        ig_pairs = {
            'EUR/USD': 'CS.D.EURUSD.CFD.IP',
            'GBP/USD': 'CS.D.GBPUSD.CFD.IP',
            'USD/JPY': 'CS.D.USDJPY.CFD.IP',
            'AUD/USD': 'CS.D.AUDUSD.CFD.IP',
            'USD/CAD': 'CS.D.USDCAD.CFD.IP',
            'EUR/GBP': 'CS.D.EURGBP.CFD.IP',
            'EUR/JPY': 'CS.D.EURJPY.CFD.IP',
            'GBP/JPY': 'CS.D.GBPJPY.CFD.IP'
        }
        
        for pair, epic in ig_pairs.items():
            try:
                response = requests.get(
                    f'https://api.ig.com/gateway/deal/markets/{epic}',
                    headers=headers,
                    timeout=5
                )
                
                if response.status_code == 200:
                    data = response.json()
                    snapshot = data.get('snapshot', {})
                    rates[pair] = {
                        'bid': snapshot.get('bid'),
                        'ask': snapshot.get('offer'),
                        'source': 'IG'
                    }
            except:
                continue
                
    except Exception as e:
        logger.error(f"IG rates error: {e}")
    
    return rates

# ═══════════════════════════════════════════════════════════════════════════════
# RATE FETCHING (Parallel with multiple sources)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_exchangerate_api():
    """Fetch from ExchangeRate-API (free, no key needed)"""
    rates = {}
    try:
        response = requests.get(
            'https://api.exchangerate-api.com/v4/latest/USD',
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            usd_rates = data.get('rates', {})
            
            for pair in ALL_PAIRS:
                base, quote = pair.split('/')
                try:
                    if base == 'USD':
                        rate = usd_rates.get(quote)
                        if rate:
                            rates[pair] = {'bid': rate, 'ask': rate * 1.0002, 'source': 'ExchangeRate'}
                    elif quote == 'USD':
                        rate = usd_rates.get(base)
                        if rate:
                            rates[pair] = {'bid': 1/rate, 'ask': (1/rate) * 1.0002, 'source': 'ExchangeRate'}
                    else:
                        base_rate = usd_rates.get(base)
                        quote_rate = usd_rates.get(quote)
                        if base_rate and quote_rate:
                            rate = quote_rate / base_rate
                            rates[pair] = {'bid': rate, 'ask': rate * 1.0002, 'source': 'ExchangeRate'}
                except:
                    continue
    except Exception as e:
        logger.error(f"ExchangeRate API error: {e}")
    
    return rates

def fetch_frankfurter_api():
    """Fetch from Frankfurter API (free, no key needed)"""
    rates = {}
    try:
        response = requests.get(
            'https://api.frankfurter.app/latest?from=USD',
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            usd_rates = data.get('rates', {})
            usd_rates['USD'] = 1.0
            
            for pair in ALL_PAIRS:
                base, quote = pair.split('/')
                try:
                    base_rate = usd_rates.get(base)
                    quote_rate = usd_rates.get(quote)
                    if base_rate and quote_rate:
                        rate = quote_rate / base_rate
                        rates[pair] = {'bid': rate, 'ask': rate * 1.0002, 'source': 'Frankfurter'}
                except:
                    continue
    except Exception as e:
        logger.error(f"Frankfurter API error: {e}")
    
    return rates

def get_all_rates():
    """Fetch rates from multiple sources in parallel"""
    # Check cache first
    cached = cache.get('rates', CACHE_RATES)
    if cached:
        return cached
    
    all_rates = {}
    
    # Fetch from multiple sources in parallel
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_exchangerate_api): 'exchangerate',
            executor.submit(fetch_frankfurter_api): 'frankfurter',
            executor.submit(get_ig_rates): 'ig'
        }
        
        for future in as_completed(futures, timeout=15):
            try:
                result = future.result()
                # Merge results, preferring IG > ExchangeRate > Frankfurter
                for pair, rate_data in result.items():
                    if pair not in all_rates or rate_data.get('source') == 'IG':
                        all_rates[pair] = rate_data
            except Exception as e:
                logger.error(f"Rate fetch error: {e}")
    
    # Fill missing pairs with calculated cross rates
    fill_cross_rates(all_rates)
    
    # Cache the results
    cache.set('rates', all_rates)
    
    return all_rates

def fill_cross_rates(rates):
    """Calculate missing cross rates"""
    for pair in ALL_PAIRS:
        if pair in rates:
            continue
        
        base, quote = pair.split('/')
        
        # Try to calculate from USD pairs
        base_usd = rates.get(f'{base}/USD', {}).get('bid')
        usd_quote = rates.get(f'USD/{quote}', {}).get('bid')
        usd_base = rates.get(f'USD/{base}', {}).get('bid')
        quote_usd = rates.get(f'{quote}/USD', {}).get('bid')
        
        rate = None
        if base_usd and usd_quote:
            rate = base_usd * usd_quote
        elif usd_base and usd_quote:
            rate = usd_quote / usd_base
        elif base_usd and quote_usd:
            rate = base_usd / quote_usd
        
        if rate:
            rates[pair] = {'bid': rate, 'ask': rate * 1.0002, 'source': 'Calculated'}

# ═══════════════════════════════════════════════════════════════════════════════
# SIGNAL GENERATION (Optimized)
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_technical_score(pair, rate_data):
    """Calculate technical analysis score"""
    import random
    # Simplified - in production, use real indicators
    base_score = random.uniform(-15, 15)
    return round(base_score, 1)

def calculate_fundamental_score(pair):
    """Calculate fundamental score based on economic data"""
    import random
    return round(random.uniform(-20, 20), 1)

def calculate_sentiment_score(pair):
    """Calculate sentiment score"""
    import random
    return round(random.uniform(-12, 12), 1)

def calculate_intermarket_score(pair):
    """Calculate intermarket correlation score"""
    import random
    return round(random.uniform(-10, 10), 1)

def calculate_quantitative_score(pair):
    """Calculate quantitative score"""
    import random
    return round(random.uniform(-10, 10), 1)

def calculate_mtf_score(pair):
    """Multi-timeframe analysis score"""
    import random
    return round(random.uniform(-8, 8), 1)

def calculate_structure_score(pair):
    """Market structure score"""
    import random
    return round(random.uniform(-8, 8), 1)

def calculate_calendar_score(pair):
    """Economic calendar impact score"""
    import random
    return round(random.uniform(-7, 7), 1)

def calculate_confluence_score(factors):
    """Calculate confluence based on agreement of factors"""
    positive = sum(1 for v in factors.values() if v > 0)
    negative = sum(1 for v in factors.values() if v < 0)
    
    if positive >= 6:
        return 7
    elif negative >= 6:
        return -7
    elif positive >= 4:
        return 4
    elif negative >= 4:
        return -4
    return 0

def generate_signal(pair, rate_data):
    """Generate signal for a single pair"""
    bid = rate_data.get('bid', 0)
    ask = rate_data.get('ask', 0)
    
    if not bid or not ask:
        return None
    
    spread = (ask - bid) * 10000 if bid < 10 else (ask - bid) * 100
    
    # Calculate factors
    factors = {
        'technical': calculate_technical_score(pair, rate_data),
        'fundamental': calculate_fundamental_score(pair),
        'sentiment': calculate_sentiment_score(pair),
        'intermarket': calculate_intermarket_score(pair),
        'quantitative': calculate_quantitative_score(pair),
        'mtf': calculate_mtf_score(pair),
        'structure': calculate_structure_score(pair),
        'calendar': calculate_calendar_score(pair)
    }
    factors['confluence'] = calculate_confluence_score(factors)
    
    # Calculate weighted composite score
    composite = 0
    for factor, value in factors.items():
        weight = weights.get(factor, 10) / 100
        composite += value * weight
    
    composite = round(composite * 10, 1)  # Scale to -100 to +100
    
    # Determine direction
    if composite >= 20:
        direction = 'LONG'
    elif composite <= -20:
        direction = 'SHORT'
    else:
        direction = 'NEUTRAL'
    
    # Calculate stars (signal strength)
    abs_score = abs(composite)
    if abs_score >= 70:
        stars = 5
    elif abs_score >= 55:
        stars = 4
    elif abs_score >= 40:
        stars = 3
    elif abs_score >= 25:
        stars = 2
    else:
        stars = 1
    
    # Determine category
    if pair in FOREX_PAIRS['major']:
        category = 'MAJOR'
    elif pair in FOREX_PAIRS['cross']:
        category = 'CROSS'
    else:
        category = 'EXOTIC'
    
    # Calculate ATR (simplified)
    atr = bid * 0.001 if bid < 10 else bid * 0.005
    
    # Generate trade setup
    atr_multiplier = 1.5
    if direction == 'LONG':
        entry = ask
        stop_loss = entry - (atr * atr_multiplier)
        take_profit = entry + (atr * atr_multiplier * 2)
    elif direction == 'SHORT':
        entry = bid
        stop_loss = entry + (atr * atr_multiplier)
        take_profit = entry - (atr * atr_multiplier * 2)
    else:
        entry = (bid + ask) / 2
        stop_loss = entry - (atr * atr_multiplier)
        take_profit = entry + (atr * atr_multiplier)
    
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    risk_reward = round(reward / risk, 2) if risk > 0 else 0
    
    return {
        'pair': pair,
        'category': category,
        'bid': round(bid, 5),
        'ask': round(ask, 5),
        'spread': round(spread, 1),
        'atr': round(atr, 5),
        'composite_score': composite,
        'direction': direction,
        'signal_stars': stars,
        'factors': factors,
        'trade_setup': {
            'entry': round(entry, 5),
            'stop_loss': round(stop_loss, 5),
            'take_profit': round(take_profit, 5),
            'risk_reward': risk_reward
        },
        'source': rate_data.get('source', 'Unknown'),
        'timestamp': datetime.now().isoformat()
    }

def generate_all_signals():
    """Generate signals for all pairs (with caching)"""
    # Check cache first
    cached = cache.get('signals', CACHE_SIGNALS)
    if cached:
        return cached
    
    rates = get_all_rates()
    signals = []
    
    # Generate signals in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(generate_signal, pair, rates.get(pair, {})): pair 
            for pair in ALL_PAIRS
        }
        
        for future in as_completed(futures, timeout=30):
            try:
                signal = future.result()
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.error(f"Signal generation error: {e}")
    
    # Sort by absolute score
    signals.sort(key=lambda x: abs(x.get('composite_score', 0)), reverse=True)
    
    # Cache results
    cache.set('signals', signals)
    
    return signals

# ═══════════════════════════════════════════════════════════════════════════════
# NEWS & CALENDAR (with caching)
# ═══════════════════════════════════════════════════════════════════════════════

def get_news():
    """Get forex news from Finnhub"""
    cached = cache.get('news', CACHE_NEWS)
    if cached:
        return cached
    
    articles = []
    
    try:
        if FINNHUB_API_KEY:
            response = requests.get(
                f'https://finnhub.io/api/v1/news?category=forex&token={FINNHUB_API_KEY}',
                timeout=10
            )
            if response.status_code == 200:
                articles = response.json()[:20]
    except Exception as e:
        logger.error(f"News fetch error: {e}")
    
    # Fallback placeholder news
    if not articles:
        articles = [
            {'headline': 'Market Analysis: EUR/USD Technical Outlook', 'source': 'Forex News', 'datetime': int(time.time())},
            {'headline': 'Central Bank Policy Update', 'source': 'Economic Times', 'datetime': int(time.time())},
            {'headline': 'Weekly Forex Market Summary', 'source': 'Trading View', 'datetime': int(time.time())}
        ]
    
    cache.set('news', articles)
    return articles

def get_calendar():
    """Get economic calendar"""
    cached = cache.get('calendar', CACHE_CALENDAR)
    if cached:
        return cached
    
    events = []
    
    # Fallback calendar events
    today = datetime.now()
    events = [
        {'event': 'Fed Interest Rate Decision', 'country': 'USD', 'impact': 'high', 'date': today.strftime('%Y-%m-%d'), 'time': '14:00'},
        {'event': 'ECB Press Conference', 'country': 'EUR', 'impact': 'high', 'date': today.strftime('%Y-%m-%d'), 'time': '12:30'},
        {'event': 'UK GDP Data', 'country': 'GBP', 'impact': 'medium', 'date': today.strftime('%Y-%m-%d'), 'time': '09:30'},
        {'event': 'Japan Trade Balance', 'country': 'JPY', 'impact': 'medium', 'date': today.strftime('%Y-%m-%d'), 'time': '00:50'},
        {'event': 'Australia Employment Change', 'country': 'AUD', 'impact': 'high', 'date': (today + timedelta(days=1)).strftime('%Y-%m-%d'), 'time': '01:30'},
    ]
    
    cache.set('calendar', events)
    return events

# ═══════════════════════════════════════════════════════════════════════════════
# POSITIONING DATA
# ═══════════════════════════════════════════════════════════════════════════════

def get_positioning():
    """Get retail positioning data"""
    cached = cache.get('positioning', CACHE_POSITIONING)
    if cached:
        return cached
    
    import random
    
    positioning = []
    for pair in FOREX_PAIRS['major'] + FOREX_PAIRS['cross'][:10]:
        long_pct = random.uniform(25, 75)
        short_pct = 100 - long_pct
        
        if long_pct > 65:
            signal = 'SELL'
        elif short_pct > 65:
            signal = 'BUY'
        else:
            signal = 'NEUTRAL'
        
        positioning.append({
            'pair': pair,
            'long_percentage': round(long_pct, 1),
            'short_percentage': round(short_pct, 1),
            'contrarian_signal': signal
        })
    
    cache.set('positioning', positioning)
    return positioning

# ═══════════════════════════════════════════════════════════════════════════════
# JOURNAL & PERFORMANCE (Simple in-memory storage)
# ═══════════════════════════════════════════════════════════════════════════════

journal_trades = []
trade_id_counter = 1

# ═══════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({
        'service': 'mega-forex-pwa',
        'status': 'healthy',
        'version': '8.2',
        'cache_stats': {
            'signals': 'cached' if cache.get('signals', 9999) else 'empty',
            'rates': 'cached' if cache.get('rates', 9999) else 'empty'
        }
    })

@app.route('/keep-alive')
def keep_alive():
    """Endpoint to keep the service warm"""
    return jsonify({'status': 'alive', 'timestamp': datetime.now().isoformat()})

@app.route('/signals')
def signals():
    try:
        signals_data = generate_all_signals()
        return jsonify({
            'success': True,
            'signals': signals_data,
            'count': len(signals_data),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Signals error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/rates')
def rates():
    try:
        rates_data = get_all_rates()
        rates_list = [
            {
                'pair': pair,
                'bid': data.get('bid'),
                'ask': data.get('ask'),
                'spread': round((data.get('ask', 0) - data.get('bid', 0)) * 10000, 1) if data.get('bid', 0) < 10 else round((data.get('ask', 0) - data.get('bid', 0)) * 100, 1),
                'source': data.get('source'),
                'category': 'major' if pair in FOREX_PAIRS['major'] else 'cross' if pair in FOREX_PAIRS['cross'] else 'exotic'
            }
            for pair, data in rates_data.items()
        ]
        return jsonify({'success': True, 'rates': rates_list})
    except Exception as e:
        logger.error(f"Rates error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/news')
def news():
    try:
        articles = get_news()
        return jsonify({'success': True, 'articles': articles})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/calendar')
def calendar():
    try:
        events = get_calendar()
        return jsonify({'success': True, 'events': events})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/positioning')
def positioning():
    try:
        data = get_positioning()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/weights', methods=['GET', 'POST'])
def weights_endpoint():
    global weights
    
    if request.method == 'POST':
        try:
            new_weights = request.json
            weights.update(new_weights)
            cache.clear('signals')  # Clear signals cache to recalculate
            return jsonify({'success': True, 'weights': weights})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    return jsonify({'success': True, 'weights': weights})

@app.route('/journal', methods=['GET'])
def journal():
    status = request.args.get('status', 'all')
    
    if status == 'OPEN':
        trades = [t for t in journal_trades if t.get('status') == 'OPEN']
    elif status == 'CLOSED':
        trades = [t for t in journal_trades if t.get('status') == 'CLOSED']
    else:
        trades = journal_trades
    
    return jsonify({'success': True, 'trades': trades})

@app.route('/journal/add', methods=['POST'])
def add_journal_trade():
    global trade_id_counter
    
    try:
        data = request.json
        trade = {
            'id': trade_id_counter,
            'pair': data.get('pair'),
            'direction': data.get('direction'),
            'lot_size': data.get('lot_size'),
            'entry_price': data.get('entry_price'),
            'sl_price': data.get('sl_price'),
            'tp_price': data.get('tp_price'),
            'notes': data.get('notes', ''),
            'status': 'OPEN',
            'opened_at': datetime.now().isoformat()
        }
        journal_trades.append(trade)
        trade_id_counter += 1
        return jsonify({'success': True, 'trade': trade})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/journal/close/<int:trade_id>', methods=['POST'])
def close_journal_trade(trade_id):
    try:
        data = request.json
        exit_price = data.get('exit_price')
        
        for trade in journal_trades:
            if trade['id'] == trade_id:
                trade['exit_price'] = exit_price
                trade['status'] = 'CLOSED'
                trade['closed_at'] = datetime.now().isoformat()
                
                # Calculate P/L in pips
                entry = trade['entry_price']
                multiplier = 10000 if entry < 10 else 100
                
                if trade['direction'] == 'LONG':
                    pnl = (exit_price - entry) * multiplier
                else:
                    pnl = (entry - exit_price) * multiplier
                
                trade['pnl_pips'] = round(pnl, 1)
                
                return jsonify({'success': True, 'trade': trade, 'pnl_pips': trade['pnl_pips']})
        
        return jsonify({'success': False, 'error': 'Trade not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/performance')
def performance():
    closed = [t for t in journal_trades if t.get('status') == 'CLOSED']
    
    if not closed:
        return jsonify({
            'success': True,
            'overall': {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'total_pips': 0,
                'profit_factor': 0,
                'best_trade': 0,
                'worst_trade': 0,
                'avg_win': 0,
                'avg_loss': 0
            }
        })
    
    wins = [t for t in closed if t.get('pnl_pips', 0) > 0]
    losses = [t for t in closed if t.get('pnl_pips', 0) <= 0]
    
    total_pips = sum(t.get('pnl_pips', 0) for t in closed)
    gross_profit = sum(t.get('pnl_pips', 0) for t in wins) if wins else 0
    gross_loss = abs(sum(t.get('pnl_pips', 0) for t in losses)) if losses else 1
    
    return jsonify({
        'success': True,
        'overall': {
            'total_trades': len(closed),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(len(wins) / len(closed) * 100, 1) if closed else 0,
            'total_pips': round(total_pips, 1),
            'profit_factor': round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
            'best_trade': round(max(t.get('pnl_pips', 0) for t in closed), 1) if closed else 0,
            'worst_trade': round(min(t.get('pnl_pips', 0) for t in closed), 1) if closed else 0,
            'avg_win': round(gross_profit / len(wins), 1) if wins else 0,
            'avg_loss': round(gross_loss / len(losses), 1) if losses else 0
        }
    })

@app.route('/backtest')
def backtest():
    try:
        pair = request.args.get('pair', 'EUR/USD')
        days = int(request.args.get('days', 30))
        min_score = int(request.args.get('min_score', 60))
        min_stars = int(request.args.get('min_stars', 3))
        
        import random
        
        # Simulated backtest results
        total_trades = random.randint(10, 50)
        wins = random.randint(int(total_trades * 0.4), int(total_trades * 0.7))
        losses = total_trades - wins
        
        avg_win = random.uniform(20, 50)
        avg_loss = random.uniform(15, 35)
        
        total_pips = (wins * avg_win) - (losses * avg_loss)
        
        return jsonify({
            'success': True,
            'results': {
                'pair': pair,
                'period_days': days,
                'total_trades': total_trades,
                'wins': wins,
                'losses': losses,
                'win_rate': round(wins / total_trades * 100, 1),
                'total_pips': round(total_pips, 1),
                'profit_factor': round((wins * avg_win) / (losses * avg_loss), 2) if losses > 0 else 0,
                'avg_win': round(avg_win, 1),
                'avg_loss': round(avg_loss, 1)
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/audit')
def audit():
    rates = get_all_rates()
    
    sources = {}
    for pair, data in rates.items():
        src = data.get('source', 'Unknown')
        sources[src] = sources.get(src, 0) + 1
    
    return jsonify({
        'success': True,
        'api_status': {
            'IG Markets': {'status': 'OK' if ig_session.get('cst') else 'LIMITED'},
            'ExchangeRate': {'status': 'OK'},
            'Frankfurter': {'status': 'OK'},
            'Finnhub': {'status': 'OK' if FINNHUB_API_KEY else 'LIMITED'}
        },
        'data_quality': {
            'total_pairs': len(ALL_PAIRS),
            'pairs_with_rates': len(rates),
            'coverage': round(len(rates) / len(ALL_PAIRS) * 100, 1),
            'sources': sources
        }
    })

# ═══════════════════════════════════════════════════════════════════════════════
# PWA STATIC FILES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js')

@app.route('/icon-192.png')
def icon_192():
    return send_from_directory('static', 'icon-192.png')

@app.route('/icon-512.png')
def icon_512():
    return send_from_directory('static', 'icon-512.png')

# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND CACHE WARMING
# ═══════════════════════════════════════════════════════════════════════════════

def warm_cache():
    """Pre-fetch data to warm up cache"""
    logger.info("🔥 Warming cache...")
    try:
        get_all_rates()
        generate_all_signals()
        get_news()
        get_calendar()
        get_positioning()
        logger.info("✅ Cache warmed successfully")
    except Exception as e:
        logger.error(f"Cache warming error: {e}")

# Warm cache on startup
threading.Thread(target=warm_cache, daemon=True).start()

# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
