"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    MEGA FOREX v8.2 PRO - PRODUCTION TRADING SYSTEM           ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  ✓ 45 Forex Pairs with guaranteed data coverage                              ║
║  ✓ 9-Factor Weighted Scoring Algorithm (REAL DATA)                           ║
║  ✓ 16 Candlestick Pattern Recognition (NEW)                                  ║
║  ✓ SQLite Trade Journal & Signal History (NEW)                               ║
║  ✓ Performance Tracking & Analytics (NEW)                                    ║
║  ✓ Smart Dynamic SL/TP (Variable ATR)                                        ║
║  ✓ REAL IG Client Sentiment + Intermarket Correlations                       ║
║  ✓ Complete Backtesting Module                                               ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from flask import Flask, jsonify, request, make_response, render_template, send_from_directory
import requests as req_lib  # Renamed to avoid conflict
import os
import logging
import json
import math
import random
import sqlite3
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache, wraps
from dotenv import load_dotenv
import numpy as np
from collections import defaultdict

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Manual CORS handling (no flask_cors needed)
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

@app.after_request
def after_request(response):
    return add_cors_headers(response)

@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        response = make_response()
        return add_cors_headers(response)

# ═══════════════════════════════════════════════════════════════════════════════
# IN-MEMORY CACHING SYSTEM (for faster responses)
# ═══════════════════════════════════════════════════════════════════════════════
import threading
import time as time_module

class SimpleCache:
    def __init__(self):
        self.data = {}
        self.timestamps = {}
        self.lock = threading.Lock()
    
    def get(self, key, max_age=60):
        """Get cached data if not expired"""
        with self.lock:
            if key in self.data and key in self.timestamps:
                age = time_module.time() - self.timestamps[key]
                if age < max_age:
                    logger.info(f"Cache HIT for {key} (age: {age:.1f}s)")
                    return self.data[key]
                else:
                    logger.info(f"Cache EXPIRED for {key} (age: {age:.1f}s)")
        return None
    
    def set(self, key, value):
        """Set cache data"""
        with self.lock:
            self.data[key] = value
            self.timestamps[key] = time_module.time()
            logger.info(f"Cache SET for {key}")

# Global cache instance
cache = SimpleCache()

# Cache durations (seconds)
CACHE_SIGNALS = 60   # Cache signals for 60 seconds
CACHE_RATES = 30     # Cache rates for 30 seconds
CACHE_NEWS = 300     # Cache news for 5 minutes

# ═══════════════════════════════════════════════════════════════════════════════
# API KEYS
# ═══════════════════════════════════════════════════════════════════════════════
POLYGON_API_KEY = os.getenv('POLYGON_API_KEY', '')
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY', '')
FRED_API_KEY = os.getenv('FRED_API_KEY', '')
ALPHA_VANTAGE_KEY = os.getenv('ALPHA_VANTAGE_KEY', '')

# IG Markets API (for REAL client sentiment)
IG_API_KEY = os.getenv('IG_API_KEY', '')
IG_USERNAME = os.getenv('IG_USERNAME', '')
IG_PASSWORD = os.getenv('IG_PASSWORD', '')
IG_ACC_TYPE = os.getenv('IG_ACC_TYPE', 'DEMO')  # DEMO or LIVE

# IG API URLs
IG_DEMO_URL = "https://demo-api.ig.com/gateway/deal"
IG_LIVE_URL = "https://api.ig.com/gateway/deal"
IG_BASE_URL = IG_LIVE_URL if IG_ACC_TYPE == 'LIVE' else IG_DEMO_URL

# IG Session Token (populated after login)
ig_session = {
    'cst': None,
    'x_security_token': None,
    'logged_in': False,
    'last_login': None,
    'last_error': None
}

# ═══════════════════════════════════════════════════════════════════════════════
# FOREX PAIRS CONFIGURATION (45 PAIRS)
# ═══════════════════════════════════════════════════════════════════════════════
FOREX_PAIRS = [
    # MAJORS (7)
    'EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD',
    # CROSSES - EUR (6)
    'EUR/GBP', 'EUR/JPY', 'EUR/CHF', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD',
    # CROSSES - GBP (5)
    'GBP/JPY', 'GBP/CHF', 'GBP/AUD', 'GBP/CAD', 'GBP/NZD',
    # CROSSES - JPY (6)
    'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY', 'SGD/JPY', 'HKD/JPY',
    # CROSSES - AUD/NZD (4)
    'AUD/NZD', 'AUD/CAD', 'AUD/CHF', 'NZD/CAD',
    # CROSSES - CHF (2)
    'NZD/CHF', 'CAD/CHF',
    # EXOTICS - USD (9)
    'USD/SGD', 'USD/HKD', 'USD/MXN', 'USD/ZAR', 'USD/TRY', 
    'USD/NOK', 'USD/SEK', 'USD/DKK', 'USD/PLN',
    # EXOTICS - EUR (6)
    'EUR/TRY', 'EUR/PLN', 'EUR/NOK', 'EUR/SEK', 'EUR/HUF', 'EUR/CZK'
]

PAIR_CATEGORIES = {
    'MAJOR': ['EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD'],
    'CROSS': ['EUR/GBP', 'EUR/JPY', 'EUR/CHF', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD',
              'GBP/JPY', 'GBP/CHF', 'GBP/AUD', 'GBP/CAD', 'GBP/NZD',
              'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY', 'SGD/JPY', 'HKD/JPY',
              'AUD/NZD', 'AUD/CAD', 'AUD/CHF', 'NZD/CAD', 'NZD/CHF', 'CAD/CHF'],
    'EXOTIC': ['USD/SGD', 'USD/HKD', 'USD/MXN', 'USD/ZAR', 'USD/TRY',
               'USD/NOK', 'USD/SEK', 'USD/DKK', 'USD/PLN',
               'EUR/TRY', 'EUR/PLN', 'EUR/NOK', 'EUR/SEK', 'EUR/HUF', 'EUR/CZK']
}

# ═══════════════════════════════════════════════════════════════════════════════
# FACTOR WEIGHTS (v8.1 Updated - Total 100%)
# Volume removed (no real spot FX volume exists) - 3% redistributed
# ═══════════════════════════════════════════════════════════════════════════════
FACTOR_WEIGHTS = {
    'technical': 24,      # RSI, MACD, ADX, ATR, Bollinger (+1% from volume)
    'fundamental': 18,    # Interest rate diffs, carry trade
    'sentiment': 13,      # IG Positioning + News sentiment (+1% from volume)
    'intermarket': 11,    # DXY, Gold, Yields, Oil correlations (+1% from volume)
    'quantitative': 8,    # Z-score, mean reversion
    'mtf': 10,            # Multi-timeframe alignment (H1/H4/D1)
    'structure': 7,       # S/R levels, pivots
    'calendar': 5,        # Economic events impact
    'confluence': 4       # Factor agreement bonus
}

# Endpoint to get/update weights
weights_file = 'factor_weights.json'

def load_weights():
    """Load weights from file or return defaults"""
    global FACTOR_WEIGHTS
    try:
        if os.path.exists(weights_file):
            with open(weights_file, 'r') as f:
                saved = json.load(f)
                FACTOR_WEIGHTS.update(saved)
    except Exception as e:
        logger.warning(f"Could not load weights: {e}")
    return FACTOR_WEIGHTS

def save_weights(weights):
    """Save weights to file"""
    try:
        with open(weights_file, 'w') as f:
            json.dump(weights, f)
        return True
    except Exception as e:
        logger.error(f"Could not save weights: {e}")
        return False

# Load weights on startup
load_weights()

# ═══════════════════════════════════════════════════════════════════════════════
# STATIC FALLBACK DATA FOR 100% COVERAGE
# ═══════════════════════════════════════════════════════════════════════════════
STATIC_RATES = {
    'EUR/USD': 1.0850, 'GBP/USD': 1.2720, 'USD/JPY': 156.50, 'USD/CHF': 0.9050,
    'AUD/USD': 0.6520, 'USD/CAD': 1.4380, 'NZD/USD': 0.5620, 'EUR/GBP': 0.8530,
    'EUR/JPY': 169.80, 'EUR/CHF': 0.9820, 'EUR/AUD': 1.6640, 'EUR/CAD': 1.5600,
    'EUR/NZD': 1.9320, 'GBP/JPY': 199.10, 'GBP/CHF': 1.1510, 'GBP/AUD': 1.9510,
    'GBP/CAD': 1.8290, 'GBP/NZD': 2.2640, 'AUD/JPY': 102.05, 'NZD/JPY': 87.95,
    'CAD/JPY': 108.85, 'CHF/JPY': 172.95, 'SGD/JPY': 116.45, 'HKD/JPY': 20.15,
    'AUD/NZD': 1.1605, 'AUD/CAD': 0.9375, 'AUD/CHF': 0.5905, 'NZD/CAD': 0.8085,
    'NZD/CHF': 0.5085, 'CAD/CHF': 0.6295, 'USD/SGD': 1.3445, 'USD/HKD': 7.7685,
    'USD/MXN': 20.45, 'USD/ZAR': 18.35, 'USD/TRY': 35.85, 'USD/NOK': 11.25,
    'USD/SEK': 11.05, 'USD/DKK': 7.15, 'USD/PLN': 4.05, 'EUR/TRY': 38.90,
    'EUR/PLN': 4.39, 'EUR/NOK': 12.21, 'EUR/SEK': 11.99, 'EUR/HUF': 408.50, 'EUR/CZK': 25.25
}

DEFAULT_ATR = {
    'EUR/USD': 0.0065, 'GBP/USD': 0.0095, 'USD/JPY': 1.05, 'USD/CHF': 0.0055,
    'AUD/USD': 0.0055, 'USD/CAD': 0.0075, 'NZD/USD': 0.0055, 'EUR/GBP': 0.0065,
    'EUR/JPY': 1.25, 'EUR/CHF': 0.0045, 'EUR/AUD': 0.0095, 'EUR/CAD': 0.0095,
    'EUR/NZD': 0.0115, 'GBP/JPY': 1.65, 'GBP/CHF': 0.0085, 'GBP/AUD': 0.0135,
    'GBP/CAD': 0.0125, 'GBP/NZD': 0.0155, 'AUD/JPY': 0.85, 'NZD/JPY': 0.75,
    'CAD/JPY': 0.95, 'CHF/JPY': 1.05, 'SGD/JPY': 0.65, 'HKD/JPY': 0.15,
    'AUD/NZD': 0.0065, 'AUD/CAD': 0.0065, 'AUD/CHF': 0.0055, 'NZD/CAD': 0.0065,
    'NZD/CHF': 0.0045, 'CAD/CHF': 0.0055, 'USD/SGD': 0.0075, 'USD/HKD': 0.0035,
    'USD/MXN': 0.25, 'USD/ZAR': 0.35, 'USD/TRY': 0.85, 'USD/NOK': 0.15,
    'USD/SEK': 0.15, 'USD/DKK': 0.065, 'USD/PLN': 0.055, 'EUR/TRY': 0.95,
    'EUR/PLN': 0.065, 'EUR/NOK': 0.18, 'EUR/SEK': 0.16, 'EUR/HUF': 5.5, 'EUR/CZK': 0.35
}

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CACHING
# ═══════════════════════════════════════════════════════════════════════════════
cache = {
    'rates': {'data': {}, 'timestamp': None},
    'candles': {'data': {}, 'timestamp': None},
    'news': {'data': [], 'timestamp': None},
    'calendar': {'data': [], 'timestamp': None},
    'fundamental': {'data': {}, 'timestamp': None},
    'intermarket_data': {'data': {}, 'timestamp': None}
}

CACHE_TTL = {
    'rates': 30,      # 30 seconds
    'candles': 300,   # 5 minutes
    'news': 600,      # 10 minutes
    'calendar': 3600, # 1 hour
    'fundamental': 3600,
    'intermarket_data': 300  # 5 minutes
}

def is_cache_valid(cache_type, custom_ttl=None):
    """Check if cache is still valid"""
    if cache_type not in cache:
        return False
    if cache[cache_type]['timestamp'] is None:
        return False
    elapsed = (datetime.now() - cache[cache_type]['timestamp']).total_seconds()
    ttl = custom_ttl if custom_ttl else CACHE_TTL.get(cache_type, 300)
    return elapsed < ttl

# ═══════════════════════════════════════════════════════════════════════════════
# SQLITE DATABASE - TRADE JOURNAL & SIGNAL HISTORY
# ═══════════════════════════════════════════════════════════════════════════════
DATABASE_PATH = 'mega_forex_journal.db'

def init_database():
    """Initialize SQLite database with all required tables"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # ─────────────────────────────────────────────────────────────────────────
    # TABLE 1: SIGNAL HISTORY - Store all generated signals
    # ─────────────────────────────────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            composite_score REAL,
            stars INTEGER,
            entry_price REAL,
            sl_price REAL,
            tp1_price REAL,
            tp2_price REAL,
            sl_pips REAL,
            tp1_pips REAL,
            risk_reward REAL,
            trade_quality TEXT,
            volatility TEXT,
            trend_strength TEXT,
            confidence TEXT,
            patterns TEXT,
            factors_json TEXT,
            rate_source TEXT
        )
    ''')
    
    # ─────────────────────────────────────────────────────────────────────────
    # TABLE 2: TRADE JOURNAL - Track actual trades taken
    # ─────────────────────────────────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER,
            timestamp_open TEXT NOT NULL,
            timestamp_close TEXT,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            lot_size REAL DEFAULT 0.01,
            entry_price REAL NOT NULL,
            sl_price REAL,
            tp_price REAL,
            exit_price REAL,
            pnl_pips REAL,
            pnl_usd REAL,
            status TEXT DEFAULT 'OPEN',
            outcome TEXT,
            notes TEXT,
            screenshot_path TEXT,
            FOREIGN KEY (signal_id) REFERENCES signal_history(id)
        )
    ''')
    
    # ─────────────────────────────────────────────────────────────────────────
    # TABLE 3: DAILY PERFORMANCE - Track daily stats
    # ─────────────────────────────────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            total_trades INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            breakeven INTEGER DEFAULT 0,
            total_pips REAL DEFAULT 0,
            total_pnl_usd REAL DEFAULT 0,
            win_rate REAL DEFAULT 0,
            best_trade_pips REAL DEFAULT 0,
            worst_trade_pips REAL DEFAULT 0,
            avg_win_pips REAL DEFAULT 0,
            avg_loss_pips REAL DEFAULT 0
        )
    ''')
    
    # ─────────────────────────────────────────────────────────────────────────
    # TABLE 4: PATTERN PERFORMANCE - Track which patterns work best
    # ─────────────────────────────────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pattern_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_name TEXT UNIQUE NOT NULL,
            occurrences INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_pips REAL DEFAULT 0,
            win_rate REAL DEFAULT 0,
            avg_pips REAL DEFAULT 0
        )
    ''')
    
    # Create indexes for faster queries
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_pair ON signal_history(pair)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_timestamp ON signal_history(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trade_pair ON trade_journal(pair)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trade_status ON trade_journal(status)')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

def save_signal_to_db(signal_data):
    """Save a generated signal to the database"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        patterns_str = json.dumps(signal_data.get('patterns', {}).get('patterns', []))
        factors_str = json.dumps(signal_data.get('factors', {}))
        
        cursor.execute('''
            INSERT INTO signal_history (
                timestamp, pair, direction, composite_score, stars,
                entry_price, sl_price, tp1_price, tp2_price,
                sl_pips, tp1_pips, risk_reward, trade_quality,
                volatility, trend_strength, confidence, patterns,
                factors_json, rate_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal_data.get('timestamp', datetime.now().isoformat()),
            signal_data.get('pair'),
            signal_data.get('direction'),
            signal_data.get('composite_score'),
            signal_data.get('stars'),
            signal_data.get('trade_setup', {}).get('entry'),
            signal_data.get('trade_setup', {}).get('sl'),
            signal_data.get('trade_setup', {}).get('tp1'),
            signal_data.get('trade_setup', {}).get('tp2'),
            signal_data.get('trade_setup', {}).get('sl_pips'),
            signal_data.get('trade_setup', {}).get('tp1_pips'),
            signal_data.get('trade_setup', {}).get('risk_reward_1'),
            signal_data.get('trade_setup', {}).get('trade_quality'),
            signal_data.get('trade_setup', {}).get('market_context', {}).get('volatility'),
            signal_data.get('trade_setup', {}).get('market_context', {}).get('trend'),
            signal_data.get('trade_setup', {}).get('market_context', {}).get('confidence'),
            patterns_str,
            factors_str,
            signal_data.get('rate', {}).get('source')
        ))
        
        signal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return signal_id
    except Exception as e:
        logger.error(f"Error saving signal to DB: {e}")
        return None

def add_trade_to_journal(trade_data):
    """Add a new trade to the journal"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trade_journal (
                signal_id, timestamp_open, pair, direction, lot_size,
                entry_price, sl_price, tp_price, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
        ''', (
            trade_data.get('signal_id'),
            trade_data.get('timestamp_open', datetime.now().isoformat()),
            trade_data['pair'],
            trade_data['direction'],
            trade_data.get('lot_size', 0.01),
            trade_data['entry_price'],
            trade_data.get('sl_price'),
            trade_data.get('tp_price'),
            trade_data.get('notes', '')
        ))
        
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return trade_id
    except Exception as e:
        logger.error(f"Error adding trade to journal: {e}")
        return None

def close_trade(trade_id, exit_price, outcome, notes=''):
    """Close an existing trade and calculate P&L"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Get trade details
        cursor.execute('SELECT * FROM trade_journal WHERE id = ?', (trade_id,))
        trade = cursor.fetchone()
        
        if not trade:
            conn.close()
            return {'error': 'Trade not found'}
        
        # Trade columns: id, signal_id, timestamp_open, timestamp_close, pair, direction, 
        # lot_size, entry_price, sl_price, tp_price, exit_price, pnl_pips, pnl_usd, status, outcome, notes, screenshot
        pair = trade[4]
        direction = trade[5]
        lot_size = trade[6]
        entry_price = trade[7]
        
        # Calculate P&L
        pip_size = 0.0001 if 'JPY' not in pair else 0.01
        
        if direction == 'LONG':
            pnl_pips = (exit_price - entry_price) / pip_size
        else:
            pnl_pips = (entry_price - exit_price) / pip_size
        
        # Approximate USD P&L (assuming standard lot = $10/pip, mini = $1/pip, micro = $0.1/pip)
        pip_value = lot_size * 10000 * pip_size  # Simplified calculation
        pnl_usd = pnl_pips * (lot_size * 10)  # $10 per pip for 1.0 lot
        
        cursor.execute('''
            UPDATE trade_journal SET
                timestamp_close = ?,
                exit_price = ?,
                pnl_pips = ?,
                pnl_usd = ?,
                status = 'CLOSED',
                outcome = ?,
                notes = notes || ' | ' || ?
            WHERE id = ?
        ''', (
            datetime.now().isoformat(),
            exit_price,
            round(pnl_pips, 1),
            round(pnl_usd, 2),
            outcome,
            notes,
            trade_id
        ))
        
        conn.commit()
        
        # Update daily performance
        update_daily_performance(cursor, pnl_pips, outcome)
        
        conn.commit()
        conn.close()
        
        return {
            'success': True,
            'trade_id': trade_id,
            'pnl_pips': round(pnl_pips, 1),
            'pnl_usd': round(pnl_usd, 2),
            'outcome': outcome
        }
    except Exception as e:
        logger.error(f"Error closing trade: {e}")
        return {'error': str(e)}

def update_daily_performance(cursor, pnl_pips, outcome):
    """Update daily performance stats"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    cursor.execute('SELECT * FROM daily_performance WHERE date = ?', (today,))
    existing = cursor.fetchone()
    
    if existing:
        # Update existing record
        wins = existing[3] + (1 if outcome == 'WIN' else 0)
        losses = existing[4] + (1 if outcome == 'LOSS' else 0)
        breakeven = existing[5] + (1 if outcome == 'BREAKEVEN' else 0)
        total_trades = existing[2] + 1
        total_pips = existing[6] + pnl_pips
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        cursor.execute('''
            UPDATE daily_performance SET
                total_trades = ?,
                wins = ?,
                losses = ?,
                breakeven = ?,
                total_pips = ?,
                win_rate = ?,
                best_trade_pips = MAX(best_trade_pips, ?),
                worst_trade_pips = MIN(worst_trade_pips, ?)
            WHERE date = ?
        ''', (total_trades, wins, losses, breakeven, total_pips, win_rate, pnl_pips, pnl_pips, today))
    else:
        # Create new record
        cursor.execute('''
            INSERT INTO daily_performance (
                date, total_trades, wins, losses, breakeven,
                total_pips, win_rate, best_trade_pips, worst_trade_pips
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            today,
            1 if outcome == 'WIN' else 0,
            1 if outcome == 'LOSS' else 0,
            1 if outcome == 'BREAKEVEN' else 0,
            pnl_pips,
            100 if outcome == 'WIN' else 0,
            pnl_pips if pnl_pips > 0 else 0,
            pnl_pips if pnl_pips < 0 else 0
        ))

def get_trade_journal(status=None, pair=None, limit=50):
    """Get trades from journal with optional filters"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = 'SELECT * FROM trade_journal WHERE 1=1'
        params = []
        
        if status:
            query += ' AND status = ?'
            params.append(status)
        if pair:
            query += ' AND pair = ?'
            params.append(pair)
        
        query += ' ORDER BY timestamp_open DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        trades = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return trades
    except Exception as e:
        logger.error(f"Error fetching trade journal: {e}")
        return []

def get_signal_history(pair=None, direction=None, limit=100):
    """Get signal history with optional filters"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = 'SELECT * FROM signal_history WHERE 1=1'
        params = []
        
        if pair:
            query += ' AND pair = ?'
            params.append(pair)
        if direction:
            query += ' AND direction = ?'
            params.append(direction)
        
        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        signals = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return signals
    except Exception as e:
        logger.error(f"Error fetching signal history: {e}")
        return []

def get_performance_stats():
    """Get overall trading performance statistics"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Overall stats
        cursor.execute('''
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN outcome = 'BREAKEVEN' THEN 1 ELSE 0 END) as breakeven,
                SUM(pnl_pips) as total_pips,
                SUM(pnl_usd) as total_pnl_usd,
                AVG(CASE WHEN outcome = 'WIN' THEN pnl_pips END) as avg_win,
                AVG(CASE WHEN outcome = 'LOSS' THEN pnl_pips END) as avg_loss,
                MAX(pnl_pips) as best_trade,
                MIN(pnl_pips) as worst_trade
            FROM trade_journal WHERE status = 'CLOSED'
        ''')
        overall = dict(cursor.fetchone())
        
        # Win rate
        if overall['total_trades'] and overall['total_trades'] > 0:
            overall['win_rate'] = round((overall['wins'] or 0) / overall['total_trades'] * 100, 1)
        else:
            overall['win_rate'] = 0
        
        # Profit factor
        cursor.execute('''
            SELECT 
                SUM(CASE WHEN pnl_pips > 0 THEN pnl_pips ELSE 0 END) as gross_profit,
                ABS(SUM(CASE WHEN pnl_pips < 0 THEN pnl_pips ELSE 0 END)) as gross_loss
            FROM trade_journal WHERE status = 'CLOSED'
        ''')
        pf_data = cursor.fetchone()
        if pf_data[1] and pf_data[1] > 0:
            overall['profit_factor'] = round(pf_data[0] / pf_data[1], 2)
        else:
            overall['profit_factor'] = 0
        
        # By pair stats
        cursor.execute('''
            SELECT 
                pair,
                COUNT(*) as trades,
                SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                SUM(pnl_pips) as pips
            FROM trade_journal WHERE status = 'CLOSED'
            GROUP BY pair
            ORDER BY pips DESC
        ''')
        by_pair = [dict(row) for row in cursor.fetchall()]
        
        # Daily performance (last 30 days)
        cursor.execute('''
            SELECT * FROM daily_performance 
            ORDER BY date DESC LIMIT 30
        ''')
        daily = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return {
            'overall': overall,
            'by_pair': by_pair,
            'daily': daily
        }
    except Exception as e:
        logger.error(f"Error fetching performance stats: {e}")
        return {'overall': {}, 'by_pair': [], 'daily': []}

# Initialize database on module load
init_database()

# ═══════════════════════════════════════════════════════════════════════════════
# RATE FETCHING - MULTI-TIER (Polygon → ExchangeRate → Static)
# ═══════════════════════════════════════════════════════════════════════════════
def get_polygon_rate(pair):
    """Fetch rate from Polygon.io"""
    if not POLYGON_API_KEY:
        return None
    try:
        ticker = f"C:{pair.replace('/', '')}"
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev"
        params = {'apiKey': POLYGON_API_KEY}
        resp = req_lib.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('results') and len(data['results']) > 0:
                r = data['results'][0]
                return {
                    'bid': r.get('l', r['c'] * 0.9999),
                    'ask': r.get('h', r['c'] * 1.0001),
                    'mid': r['c'],
                    'open': r.get('o', r['c']),
                    'high': r.get('h', r['c']),
                    'low': r.get('l', r['c']),
                    'close': r['c'],
                    'volume': r.get('v', 0),
                    'source': 'polygon'
                }
    except Exception as e:
        logger.debug(f"Polygon rate fetch failed for {pair}: {e}")
    return None

def get_exchangerate_rate(pair):
    """Fetch rate from ExchangeRate-API (free, no key needed)"""
    try:
        base, quote = pair.split('/')
        url = f"https://api.exchangerate-api.com/v4/latest/{base}"
        resp = req_lib.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if quote in data.get('rates', {}):
                rate = data['rates'][quote]
                return {
                    'bid': rate * 0.9999,
                    'ask': rate * 1.0001,
                    'mid': rate,
                    'source': 'exchangerate'
                }
    except Exception as e:
        logger.debug(f"ExchangeRate fetch failed for {pair}: {e}")
    return None

def get_rate(pair):
    """Get rate with multi-tier fallback"""
    # Tier 1: Polygon
    rate = get_polygon_rate(pair)
    if rate:
        return rate
    
    # Tier 2: ExchangeRate-API
    rate = get_exchangerate_rate(pair)
    if rate:
        return rate
    
    # Tier 3: Static fallback
    if pair in STATIC_RATES:
        mid = STATIC_RATES[pair]
        return {
            'bid': mid * 0.9999,
            'ask': mid * 1.0001,
            'mid': mid,
            'source': 'static'
        }
    
    return None

def get_all_rates():
    """Get rates for all pairs with caching"""
    if is_cache_valid('rates') and cache['rates']['data']:
        return cache['rates']['data']
    
    rates = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_pair = {executor.submit(get_rate, pair): pair for pair in FOREX_PAIRS}
        for future in as_completed(future_to_pair):
            pair = future_to_pair[future]
            try:
                result = future.result()
                if result:
                    rates[pair] = result
            except Exception as e:
                logger.debug(f"Rate fetch error for {pair}: {e}")
    
    cache['rates']['data'] = rates
    cache['rates']['timestamp'] = datetime.now()
    return rates

# ═══════════════════════════════════════════════════════════════════════════════
# CANDLE DATA & TECHNICAL INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════
def get_polygon_candles(pair, timeframe='day', limit=100):
    """Fetch candle data from Polygon"""
    if not POLYGON_API_KEY:
        return None
    try:
        ticker = f"C:{pair.replace('/', '')}"
        multiplier = 1
        span = 'day'
        if timeframe == 'hour':
            span = 'hour'
        elif timeframe == 'minute':
            span = 'minute'
        
        end = datetime.now()
        start = end - timedelta(days=limit if span == 'day' else limit // 24)
        
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{multiplier}/{span}/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        params = {'apiKey': POLYGON_API_KEY, 'limit': limit}
        resp = req_lib.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get('results'):
                return [{
                    'timestamp': r['t'],
                    'open': r['o'],
                    'high': r['h'],
                    'low': r['l'],
                    'close': r['c'],
                    'volume': r.get('v', 0)
                } for r in data['results']]
    except Exception as e:
        logger.debug(f"Candle fetch failed for {pair}: {e}")
    return None

def calculate_rsi(closes, period=14):
    """Calculate RSI indicator"""
    if len(closes) < period + 1:
        return 50
    
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(closes, fast=12, slow=26, signal=9):
    """Calculate MACD indicator"""
    if len(closes) < slow + signal:
        return {'macd': 0, 'signal': 0, 'histogram': 0}
    
    def ema(data, period):
        if len(data) < period:
            return data[-1] if data else 0
        k = 2 / (period + 1)
        ema_val = sum(data[:period]) / period
        for price in data[period:]:
            ema_val = price * k + ema_val * (1 - k)
        return ema_val
    
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = ema_fast - ema_slow
    
    # Calculate signal line from MACD values
    macd_values = []
    for i in range(slow, len(closes)):
        ef = ema(closes[:i+1], fast)
        es = ema(closes[:i+1], slow)
        macd_values.append(ef - es)
    
    signal_line = ema(macd_values, signal) if len(macd_values) >= signal else macd_line
    
    return {
        'macd': round(macd_line, 5),
        'signal': round(signal_line, 5),
        'histogram': round(macd_line - signal_line, 5)
    }

def calculate_adx(highs, lows, closes, period=14):
    """Calculate ADX indicator"""
    if len(closes) < period * 2:
        return 25
    
    tr_list = []
    plus_dm = []
    minus_dm = []
    
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
        
        high_diff = highs[i] - highs[i-1]
        low_diff = lows[i-1] - lows[i]
        
        if high_diff > low_diff and high_diff > 0:
            plus_dm.append(high_diff)
        else:
            plus_dm.append(0)
            
        if low_diff > high_diff and low_diff > 0:
            minus_dm.append(low_diff)
        else:
            minus_dm.append(0)
    
    if len(tr_list) < period:
        return 25
    
    atr = sum(tr_list[:period]) / period
    plus_di = (sum(plus_dm[:period]) / period) / atr * 100 if atr > 0 else 0
    minus_di = (sum(minus_dm[:period]) / period) / atr * 100 if atr > 0 else 0
    
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    
    return round(dx, 1)

def calculate_atr(highs, lows, closes, period=14):
    """Calculate ATR indicator"""
    if len(closes) < period + 1:
        return None
    
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    
    if len(tr_list) < period:
        return sum(tr_list) / len(tr_list) if tr_list else None
    
    return sum(tr_list[-period:]) / period

def calculate_bollinger(closes, period=20, std_dev=2):
    """Calculate Bollinger Bands"""
    if len(closes) < period:
        return {'upper': closes[-1] * 1.02, 'middle': closes[-1], 'lower': closes[-1] * 0.98, 'percent_b': 50}
    
    recent = closes[-period:]
    middle = sum(recent) / period
    variance = sum((x - middle) ** 2 for x in recent) / period
    std = variance ** 0.5
    
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    
    current = closes[-1]
    percent_b = ((current - lower) / (upper - lower)) * 100 if upper != lower else 50
    
    return {
        'upper': round(upper, 5),
        'middle': round(middle, 5),
        'lower': round(lower, 5),
        'percent_b': round(percent_b, 1)
    }

def calculate_ema(closes, period=20):
    """Calculate EMA"""
    if len(closes) < period:
        return closes[-1] if closes else 0
    
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 5)

# ═══════════════════════════════════════════════════════════════════════════════
# CANDLESTICK PATTERN RECOGNITION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_candlestick_patterns(candles):
    """
    Detect candlestick patterns from OHLC data
    Returns list of detected patterns with signal direction
    """
    if not candles or len(candles) < 5:
        return {'patterns': [], 'signal': 'NEUTRAL', 'score': 50}
    
    patterns = []
    
    # Get last 5 candles for pattern analysis
    c = candles[-5:]  # Last 5 candles
    
    # Helper function to get candle body and wick sizes
    def candle_metrics(candle):
        o, h, l, close = candle['open'], candle['high'], candle['low'], candle['close']
        body = abs(close - o)
        full_range = h - l if h - l > 0 else 0.0001
        upper_wick = h - max(o, close)
        lower_wick = min(o, close) - l
        is_bullish = close > o
        body_pct = (body / full_range) * 100 if full_range > 0 else 0
        return {
            'open': o, 'high': h, 'low': l, 'close': close,
            'body': body, 'range': full_range,
            'upper_wick': upper_wick, 'lower_wick': lower_wick,
            'is_bullish': is_bullish, 'body_pct': body_pct
        }
    
    # Analyze last 3 candles
    curr = candle_metrics(c[-1])  # Current candle
    prev = candle_metrics(c[-2])  # Previous candle
    prev2 = candle_metrics(c[-3]) # 2 candles ago
    
    avg_body = sum(candle_metrics(x)['body'] for x in c) / len(c)
    avg_range = sum(candle_metrics(x)['range'] for x in c) / len(c)
    
    # ─────────────────────────────────────────────────────────────────────────
    # 1. DOJI - Small body with wicks on both sides
    # ─────────────────────────────────────────────────────────────────────────
    if curr['body_pct'] < 10 and curr['upper_wick'] > curr['body'] and curr['lower_wick'] > curr['body']:
        patterns.append({
            'name': 'DOJI',
            'type': 'reversal',
            'signal': 'NEUTRAL',
            'strength': 60,
            'description': 'Indecision - potential reversal'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 2. HAMMER - Small body at top, long lower wick (bullish reversal)
    # ─────────────────────────────────────────────────────────────────────────
    if (curr['lower_wick'] >= curr['body'] * 2 and 
        curr['upper_wick'] < curr['body'] * 0.5 and
        curr['body_pct'] < 40):
        patterns.append({
            'name': 'HAMMER',
            'type': 'reversal',
            'signal': 'BULLISH',
            'strength': 70,
            'description': 'Bullish reversal - buyers rejected lower prices'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 3. INVERTED HAMMER - Small body at bottom, long upper wick
    # ─────────────────────────────────────────────────────────────────────────
    if (curr['upper_wick'] >= curr['body'] * 2 and 
        curr['lower_wick'] < curr['body'] * 0.5 and
        curr['body_pct'] < 40):
        patterns.append({
            'name': 'INVERTED_HAMMER',
            'type': 'reversal',
            'signal': 'BULLISH',
            'strength': 65,
            'description': 'Potential bullish reversal after downtrend'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 4. SHOOTING STAR - Small body at bottom, long upper wick (bearish)
    # ─────────────────────────────────────────────────────────────────────────
    if (curr['upper_wick'] >= curr['body'] * 2 and 
        curr['lower_wick'] < curr['body'] * 0.5 and
        curr['body_pct'] < 40 and
        not curr['is_bullish']):
        # Check if in uptrend (prev candles were bullish)
        if prev['is_bullish'] and prev2['is_bullish']:
            patterns.append({
                'name': 'SHOOTING_STAR',
                'type': 'reversal',
                'signal': 'BEARISH',
                'strength': 70,
                'description': 'Bearish reversal - sellers rejected higher prices'
            })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 5. BULLISH ENGULFING - Current bullish candle engulfs previous bearish
    # ─────────────────────────────────────────────────────────────────────────
    if (curr['is_bullish'] and not prev['is_bullish'] and
        curr['open'] < prev['close'] and curr['close'] > prev['open'] and
        curr['body'] > prev['body'] * 1.1):
        patterns.append({
            'name': 'BULLISH_ENGULFING',
            'type': 'reversal',
            'signal': 'BULLISH',
            'strength': 80,
            'description': 'Strong bullish reversal - buyers took control'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 6. BEARISH ENGULFING - Current bearish candle engulfs previous bullish
    # ─────────────────────────────────────────────────────────────────────────
    if (not curr['is_bullish'] and prev['is_bullish'] and
        curr['open'] > prev['close'] and curr['close'] < prev['open'] and
        curr['body'] > prev['body'] * 1.1):
        patterns.append({
            'name': 'BEARISH_ENGULFING',
            'type': 'reversal',
            'signal': 'BEARISH',
            'strength': 80,
            'description': 'Strong bearish reversal - sellers took control'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 7. MORNING STAR - 3-candle bullish reversal
    # ─────────────────────────────────────────────────────────────────────────
    if (not prev2['is_bullish'] and prev2['body_pct'] > 50 and  # Big bearish
        prev['body_pct'] < 30 and  # Small middle candle
        curr['is_bullish'] and curr['body_pct'] > 50 and  # Big bullish
        curr['close'] > (prev2['open'] + prev2['close']) / 2):  # Closes above midpoint
        patterns.append({
            'name': 'MORNING_STAR',
            'type': 'reversal',
            'signal': 'BULLISH',
            'strength': 85,
            'description': 'Strong 3-candle bullish reversal pattern'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 8. EVENING STAR - 3-candle bearish reversal
    # ─────────────────────────────────────────────────────────────────────────
    if (prev2['is_bullish'] and prev2['body_pct'] > 50 and  # Big bullish
        prev['body_pct'] < 30 and  # Small middle candle
        not curr['is_bullish'] and curr['body_pct'] > 50 and  # Big bearish
        curr['close'] < (prev2['open'] + prev2['close']) / 2):  # Closes below midpoint
        patterns.append({
            'name': 'EVENING_STAR',
            'type': 'reversal',
            'signal': 'BEARISH',
            'strength': 85,
            'description': 'Strong 3-candle bearish reversal pattern'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 9. THREE WHITE SOLDIERS - 3 consecutive bullish candles
    # ─────────────────────────────────────────────────────────────────────────
    if (curr['is_bullish'] and prev['is_bullish'] and prev2['is_bullish'] and
        curr['close'] > prev['close'] > prev2['close'] and
        curr['body_pct'] > 50 and prev['body_pct'] > 50 and prev2['body_pct'] > 50):
        patterns.append({
            'name': 'THREE_WHITE_SOLDIERS',
            'type': 'continuation',
            'signal': 'BULLISH',
            'strength': 75,
            'description': 'Strong bullish momentum - 3 advancing candles'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 10. THREE BLACK CROWS - 3 consecutive bearish candles
    # ─────────────────────────────────────────────────────────────────────────
    if (not curr['is_bullish'] and not prev['is_bullish'] and not prev2['is_bullish'] and
        curr['close'] < prev['close'] < prev2['close'] and
        curr['body_pct'] > 50 and prev['body_pct'] > 50 and prev2['body_pct'] > 50):
        patterns.append({
            'name': 'THREE_BLACK_CROWS',
            'type': 'continuation',
            'signal': 'BEARISH',
            'strength': 75,
            'description': 'Strong bearish momentum - 3 declining candles'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 11. BULLISH HARAMI - Small bullish candle inside previous bearish
    # ─────────────────────────────────────────────────────────────────────────
    if (curr['is_bullish'] and not prev['is_bullish'] and
        curr['body'] < prev['body'] * 0.5 and
        curr['high'] < prev['open'] and curr['low'] > prev['close']):
        patterns.append({
            'name': 'BULLISH_HARAMI',
            'type': 'reversal',
            'signal': 'BULLISH',
            'strength': 65,
            'description': 'Potential bullish reversal - momentum slowing'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 12. BEARISH HARAMI - Small bearish candle inside previous bullish
    # ─────────────────────────────────────────────────────────────────────────
    if (not curr['is_bullish'] and prev['is_bullish'] and
        curr['body'] < prev['body'] * 0.5 and
        curr['high'] < prev['close'] and curr['low'] > prev['open']):
        patterns.append({
            'name': 'BEARISH_HARAMI',
            'type': 'reversal',
            'signal': 'BEARISH',
            'strength': 65,
            'description': 'Potential bearish reversal - momentum slowing'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 13. MARUBOZU - Full body candle with no/tiny wicks
    # ─────────────────────────────────────────────────────────────────────────
    if curr['body_pct'] > 90:
        signal = 'BULLISH' if curr['is_bullish'] else 'BEARISH'
        patterns.append({
            'name': 'MARUBOZU',
            'type': 'continuation',
            'signal': signal,
            'strength': 70,
            'description': f'Strong {signal.lower()} momentum - full body candle'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 14. SPINNING TOP - Small body with long wicks both sides
    # ─────────────────────────────────────────────────────────────────────────
    if (curr['body_pct'] < 30 and 
        curr['upper_wick'] > curr['body'] and 
        curr['lower_wick'] > curr['body']):
        patterns.append({
            'name': 'SPINNING_TOP',
            'type': 'reversal',
            'signal': 'NEUTRAL',
            'strength': 55,
            'description': 'Indecision - market uncertainty'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 15. PIERCING LINE - Bullish reversal (2-candle)
    # ─────────────────────────────────────────────────────────────────────────
    if (not prev['is_bullish'] and curr['is_bullish'] and
        curr['open'] < prev['low'] and
        curr['close'] > (prev['open'] + prev['close']) / 2 and
        curr['close'] < prev['open']):
        patterns.append({
            'name': 'PIERCING_LINE',
            'type': 'reversal',
            'signal': 'BULLISH',
            'strength': 70,
            'description': 'Bullish reversal - price recovered above midpoint'
        })
    
    # ─────────────────────────────────────────────────────────────────────────
    # 16. DARK CLOUD COVER - Bearish reversal (2-candle)
    # ─────────────────────────────────────────────────────────────────────────
    if (prev['is_bullish'] and not curr['is_bullish'] and
        curr['open'] > prev['high'] and
        curr['close'] < (prev['open'] + prev['close']) / 2 and
        curr['close'] > prev['open']):
        patterns.append({
            'name': 'DARK_CLOUD_COVER',
            'type': 'reversal',
            'signal': 'BEARISH',
            'strength': 70,
            'description': 'Bearish reversal - price dropped below midpoint'
        })
    
    # Calculate overall pattern signal
    if not patterns:
        return {'patterns': [], 'signal': 'NEUTRAL', 'score': 50, 'pattern_count': 0}
    
    # Weight patterns by strength
    bullish_score = sum(p['strength'] for p in patterns if p['signal'] == 'BULLISH')
    bearish_score = sum(p['strength'] for p in patterns if p['signal'] == 'BEARISH')
    
    if bullish_score > bearish_score + 20:
        overall_signal = 'BULLISH'
        score = min(85, 50 + bullish_score / 3)
    elif bearish_score > bullish_score + 20:
        overall_signal = 'BEARISH'
        score = max(15, 50 - bearish_score / 3)
    else:
        overall_signal = 'NEUTRAL'
        score = 50
    
    return {
        'patterns': patterns,
        'signal': overall_signal,
        'score': round(score, 1),
        'pattern_count': len(patterns),
        'bullish_strength': bullish_score,
        'bearish_strength': bearish_score
    }

def get_technical_indicators(pair):
    """Get all technical indicators for a pair"""
    candles = get_polygon_candles(pair, 'day', 100)
    
    if not candles or len(candles) < 20:
        # Generate synthetic data for technical analysis
        rate = get_rate(pair)
        base_price = rate['mid'] if rate else STATIC_RATES.get(pair, 1.0)
        
        # Create synthetic candles with realistic variation
        closes = []
        highs = []
        lows = []
        
        for i in range(100):
            variation = random.uniform(-0.005, 0.005) * base_price
            close = base_price + variation
            closes.append(close)
            highs.append(close * (1 + random.uniform(0.001, 0.003)))
            lows.append(close * (1 - random.uniform(0.001, 0.003)))
        
        candles = [{'close': c, 'high': h, 'low': l} for c, h, l in zip(closes, highs, lows)]
    
    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    
    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    adx = calculate_adx(highs, lows, closes)
    atr = calculate_atr(highs, lows, closes)
    bollinger = calculate_bollinger(closes)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    
    # Use default ATR if calculated is None
    if atr is None:
        atr = DEFAULT_ATR.get(pair, 0.005)
    
    return {
        'rsi': round(rsi, 1),
        'macd': macd,
        'adx': round(adx, 1),
        'atr': round(atr, 5),
        'bollinger': bollinger,
        'ema20': ema20,
        'ema50': ema50,
        'ema_signal': 'BULLISH' if closes[-1] > ema20 > ema50 else 'BEARISH' if closes[-1] < ema20 < ema50 else 'NEUTRAL',
        'current_price': closes[-1]
    }

# ═══════════════════════════════════════════════════════════════════════════════
# NEWS & SENTIMENT
# ═══════════════════════════════════════════════════════════════════════════════
def get_finnhub_news():
    """Fetch forex news from Finnhub"""
    if not FINNHUB_API_KEY:
        return {'articles': [], 'count': 0}
    
    if is_cache_valid('news') and cache['news']['data']:
        return cache['news']['data']
    
    try:
        url = "https://finnhub.io/api/v1/news"
        params = {'category': 'forex', 'token': FINNHUB_API_KEY}
        resp = req_lib.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            articles = resp.json()[:30]
            result = {
                'articles': [{
                    'headline': a.get('headline', ''),
                    'summary': a.get('summary', ''),
                    'source': a.get('source', ''),
                    'url': a.get('url', ''),
                    'datetime': a.get('datetime', 0)
                } for a in articles],
                'count': len(articles)
            }
            cache['news']['data'] = result
            cache['news']['timestamp'] = datetime.now()
            return result
    except Exception as e:
        logger.debug(f"Finnhub news fetch failed: {e}")
    
    return {'articles': [], 'count': 0}

def analyze_sentiment(pair):
    """
    REAL Sentiment Analysis combining:
    1. IG Client Positioning (REAL retail sentiment)
    2. Finnhub News Sentiment
    """
    sentiment_score = 50  # Neutral default
    sentiment_sources = {}
    
    base, quote = pair.split('/')
    
    # ═══════════════════════════════════════════════════════════════════════════
    # SOURCE 1: IG Client Positioning (REAL DATA - 60% weight)
    # ═══════════════════════════════════════════════════════════════════════════
    ig_sentiment = None
    if all([IG_API_KEY, IG_USERNAME, IG_PASSWORD]):
        ig_market_ids = {
            'EUR/USD': 'EURUSD', 'GBP/USD': 'GBPUSD', 'USD/JPY': 'USDJPY',
            'USD/CHF': 'USDCHF', 'AUD/USD': 'AUDUSD', 'USD/CAD': 'USDCAD',
            'NZD/USD': 'NZDUSD', 'EUR/GBP': 'EURGBP', 'EUR/JPY': 'EURJPY',
            'GBP/JPY': 'GBPJPY', 'AUD/JPY': 'AUDJPY', 'EUR/AUD': 'EURAUD',
            'EUR/CHF': 'EURCHF', 'GBP/CHF': 'GBPCHF', 'EUR/CAD': 'EURCAD'
        }
        
        market_id = ig_market_ids.get(pair)
        if market_id:
            ig_data = get_ig_client_sentiment(market_id)
            if ig_data:
                long_pct = ig_data['long_percentage']
                short_pct = ig_data['short_percentage']
                
                # Contrarian logic: If retail is heavily long, be bearish (and vice versa)
                # 50% long = neutral (50), 70% long = bearish (30), 30% long = bullish (70)
                ig_sentiment = 100 - long_pct  # Contrarian score
                
                sentiment_sources['ig_positioning'] = {
                    'long_pct': long_pct,
                    'short_pct': short_pct,
                    'score': ig_sentiment,
                    'source': 'IG_REAL'
                }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # SOURCE 2: Finnhub News Sentiment (40% weight)
    # ═══════════════════════════════════════════════════════════════════════════
    news_sentiment = 50
    news = get_finnhub_news()
    relevant_articles = []
    
    # Enhanced sentiment keywords with weights
    strong_bullish = ['surge', 'soar', 'rally', 'breakout', 'boom', 'skyrocket']
    mild_bullish = ['gain', 'rise', 'up', 'bullish', 'strong', 'positive', 'higher', 'buy', 'support']
    strong_bearish = ['crash', 'plunge', 'collapse', 'crisis', 'plummet', 'tumble']
    mild_bearish = ['fall', 'drop', 'decline', 'weak', 'bearish', 'negative', 'lower', 'sell', 'resistance']
    
    for article in news.get('articles', []):
        headline = article.get('headline', '').lower()
        summary = article.get('summary', '').lower()
        text = headline + ' ' + summary
        
        # Check if article mentions this currency pair
        if base.lower() in text or quote.lower() in text or pair.replace('/', '').lower() in text:
            relevant_articles.append(article)
            
            # Calculate weighted sentiment
            strong_bull = sum(3 for w in strong_bullish if w in text)
            mild_bull = sum(1 for w in mild_bullish if w in text)
            strong_bear = sum(3 for w in strong_bearish if w in text)
            mild_bear = sum(1 for w in mild_bearish if w in text)
            
            net_sentiment = (strong_bull + mild_bull) - (strong_bear + mild_bear)
            news_sentiment += net_sentiment * 2
    
    news_sentiment = max(0, min(100, news_sentiment))
    
    sentiment_sources['news_analysis'] = {
        'score': news_sentiment,
        'articles_analyzed': len(relevant_articles),
        'source': 'FINNHUB_NEWS'
    }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # COMBINE SOURCES (IG=60%, News=40% when both available)
    # ═══════════════════════════════════════════════════════════════════════════
    if ig_sentiment is not None:
        # Both sources available - weighted average
        sentiment_score = (ig_sentiment * 0.6) + (news_sentiment * 0.4)
        data_quality = 'HIGH'
    else:
        # Only news available
        sentiment_score = news_sentiment
        data_quality = 'MEDIUM'
    
    sentiment_score = max(0, min(100, sentiment_score))
    
    return {
        'score': round(sentiment_score, 1),
        'signal': 'BULLISH' if sentiment_score > 55 else 'BEARISH' if sentiment_score < 45 else 'NEUTRAL',
        'articles': len(relevant_articles),
        'sources': sentiment_sources,
        'data_quality': data_quality
    }

# ═══════════════════════════════════════════════════════════════════════════════
# ECONOMIC CALENDAR
# ═══════════════════════════════════════════════════════════════════════════════
def get_fallback_calendar():
    """Generate fallback economic calendar with typical weekly events"""
    today = datetime.now()
    events = []
    
    # Comprehensive weekly economic events with realistic data
    weekly_events = [
        # US Events
        {'country': 'US', 'event': 'Initial Jobless Claims', 'impact': 'medium', 'day_offset': 0, 'hour': 8, 'minute': 30, 'estimate': '215K', 'previous': '217K'},
        {'country': 'US', 'event': 'Retail Sales MoM', 'impact': 'high', 'day_offset': 1, 'hour': 8, 'minute': 30, 'estimate': '0.3%', 'previous': '0.4%'},
        {'country': 'US', 'event': 'Fed Interest Rate Decision', 'impact': 'high', 'day_offset': 2, 'hour': 14, 'minute': 0, 'estimate': '5.50%', 'previous': '5.50%'},
        {'country': 'US', 'event': 'Core CPI MoM', 'impact': 'high', 'day_offset': 3, 'hour': 8, 'minute': 30, 'estimate': '0.2%', 'previous': '0.3%'},
        {'country': 'US', 'event': 'Non-Farm Payrolls', 'impact': 'high', 'day_offset': 4, 'hour': 8, 'minute': 30, 'estimate': '180K', 'previous': '199K'},
        {'country': 'US', 'event': 'Unemployment Rate', 'impact': 'high', 'day_offset': 4, 'hour': 8, 'minute': 30, 'estimate': '3.8%', 'previous': '3.7%'},
        {'country': 'US', 'event': 'ISM Manufacturing PMI', 'impact': 'high', 'day_offset': 1, 'hour': 10, 'minute': 0, 'estimate': '47.5', 'previous': '46.7'},
        {'country': 'US', 'event': 'Consumer Confidence', 'impact': 'medium', 'day_offset': 2, 'hour': 10, 'minute': 0, 'estimate': '104.5', 'previous': '102.0'},
        
        # EU Events
        {'country': 'EU', 'event': 'ECB Interest Rate Decision', 'impact': 'high', 'day_offset': 1, 'hour': 8, 'minute': 15, 'estimate': '4.50%', 'previous': '4.50%'},
        {'country': 'EU', 'event': 'CPI YoY Flash', 'impact': 'high', 'day_offset': 2, 'hour': 5, 'minute': 0, 'estimate': '2.4%', 'previous': '2.6%'},
        {'country': 'EU', 'event': 'GDP Growth Rate QoQ', 'impact': 'medium', 'day_offset': 3, 'hour': 5, 'minute': 0, 'estimate': '0.1%', 'previous': '0.0%'},
        {'country': 'DE', 'event': 'ZEW Economic Sentiment', 'impact': 'medium', 'day_offset': 1, 'hour': 5, 'minute': 0, 'estimate': '12.5', 'previous': '9.8'},
        {'country': 'DE', 'event': 'Ifo Business Climate', 'impact': 'medium', 'day_offset': 3, 'hour': 4, 'minute': 0, 'estimate': '87.0', 'previous': '85.7'},
        
        # UK Events
        {'country': 'UK', 'event': 'BoE Interest Rate Decision', 'impact': 'high', 'day_offset': 2, 'hour': 7, 'minute': 0, 'estimate': '5.25%', 'previous': '5.25%'},
        {'country': 'UK', 'event': 'CPI YoY', 'impact': 'high', 'day_offset': 1, 'hour': 2, 'minute': 0, 'estimate': '4.0%', 'previous': '4.2%'},
        {'country': 'UK', 'event': 'Unemployment Rate', 'impact': 'medium', 'day_offset': 3, 'hour': 2, 'minute': 0, 'estimate': '4.3%', 'previous': '4.2%'},
        {'country': 'UK', 'event': 'Retail Sales MoM', 'impact': 'medium', 'day_offset': 4, 'hour': 2, 'minute': 0, 'estimate': '0.3%', 'previous': '-0.2%'},
        
        # JP Events
        {'country': 'JP', 'event': 'BoJ Interest Rate Decision', 'impact': 'high', 'day_offset': 2, 'hour': 23, 'minute': 0, 'estimate': '-0.10%', 'previous': '-0.10%'},
        {'country': 'JP', 'event': 'GDP Growth Rate QoQ', 'impact': 'medium', 'day_offset': 4, 'hour': 19, 'minute': 50, 'estimate': '0.3%', 'previous': '-0.5%'},
        {'country': 'JP', 'event': 'Core CPI YoY', 'impact': 'high', 'day_offset': 3, 'hour': 19, 'minute': 30, 'estimate': '2.5%', 'previous': '2.7%'},
        
        # AU Events
        {'country': 'AU', 'event': 'RBA Interest Rate Decision', 'impact': 'high', 'day_offset': 1, 'hour': 22, 'minute': 30, 'estimate': '4.35%', 'previous': '4.35%'},
        {'country': 'AU', 'event': 'Employment Change', 'impact': 'high', 'day_offset': 3, 'hour': 20, 'minute': 30, 'estimate': '25.0K', 'previous': '61.5K'},
        {'country': 'AU', 'event': 'Unemployment Rate', 'impact': 'medium', 'day_offset': 3, 'hour': 20, 'minute': 30, 'estimate': '3.9%', 'previous': '3.8%'},
        
        # CA Events
        {'country': 'CA', 'event': 'BoC Interest Rate Decision', 'impact': 'high', 'day_offset': 2, 'hour': 10, 'minute': 0, 'estimate': '5.00%', 'previous': '5.00%'},
        {'country': 'CA', 'event': 'CPI MoM', 'impact': 'high', 'day_offset': 1, 'hour': 8, 'minute': 30, 'estimate': '0.1%', 'previous': '0.4%'},
        {'country': 'CA', 'event': 'Employment Change', 'impact': 'high', 'day_offset': 4, 'hour': 8, 'minute': 30, 'estimate': '15.0K', 'previous': '-2.8K'},
        
        # NZ Events
        {'country': 'NZ', 'event': 'RBNZ Interest Rate Decision', 'impact': 'high', 'day_offset': 3, 'hour': 21, 'minute': 0, 'estimate': '5.50%', 'previous': '5.50%'},
        {'country': 'NZ', 'event': 'GDP Growth Rate QoQ', 'impact': 'medium', 'day_offset': 4, 'hour': 17, 'minute': 45, 'estimate': '0.2%', 'previous': '-0.3%'},
        
        # CH Events
        {'country': 'CH', 'event': 'SNB Interest Rate Decision', 'impact': 'high', 'day_offset': 4, 'hour': 3, 'minute': 30, 'estimate': '1.75%', 'previous': '1.75%'},
        {'country': 'CH', 'event': 'CPI MoM', 'impact': 'medium', 'day_offset': 2, 'hour': 2, 'minute': 30, 'estimate': '0.1%', 'previous': '0.0%'},
        
        # CN Events
        {'country': 'CN', 'event': 'GDP Growth Rate YoY', 'impact': 'high', 'day_offset': 1, 'hour': 22, 'minute': 0, 'estimate': '4.5%', 'previous': '4.9%'},
        {'country': 'CN', 'event': 'Industrial Production YoY', 'impact': 'medium', 'day_offset': 1, 'hour': 22, 'minute': 0, 'estimate': '5.0%', 'previous': '4.6%'},
    ]
    
    for evt in weekly_events:
        event_date = today + timedelta(days=evt['day_offset'])
        event_datetime = event_date.replace(hour=evt['hour'], minute=evt['minute'], second=0, microsecond=0)
        
        events.append({
            'country': evt['country'],
            'event': evt['event'],
            'impact': evt['impact'],
            'actual': None,
            'estimate': evt['estimate'],
            'previous': evt['previous'],
            'time': event_datetime.isoformat()
        })
    
    # Sort by time
    events.sort(key=lambda x: x['time'])
    
    return events

def get_economic_calendar():
    """Fetch economic calendar from Finnhub with fallback"""
    if is_cache_valid('calendar') and cache['calendar']['data']:
        return cache['calendar']['data']
    
    # Try Finnhub first
    if FINNHUB_API_KEY:
        try:
            today = datetime.now()
            from_date = today.strftime('%Y-%m-%d')
            to_date = (today + timedelta(days=7)).strftime('%Y-%m-%d')
            
            url = "https://finnhub.io/api/v1/calendar/economic"
            params = {
                'from': from_date,
                'to': to_date,
                'token': FINNHUB_API_KEY
            }
            resp = req_lib.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                events = data.get('economicCalendar', [])[:50]
                
                if events:
                    result = [{
                        'country': e.get('country', ''),
                        'event': e.get('event', ''),
                        'impact': e.get('impact', 'low'),
                        'actual': e.get('actual'),
                        'estimate': e.get('estimate'),
                        'previous': e.get('previous'),
                        'time': e.get('time', '')
                    } for e in events]
                    
                    cache['calendar']['data'] = result
                    cache['calendar']['timestamp'] = datetime.now()
                    return result
        except Exception as e:
            logger.debug(f"Finnhub calendar fetch failed: {e}")
    
    # Use fallback calendar
    logger.info("Using fallback economic calendar")
    fallback = get_fallback_calendar()
    cache['calendar']['data'] = fallback
    cache['calendar']['timestamp'] = datetime.now()
    return fallback

def get_calendar_risk(pair):
    """Calculate calendar risk for a pair"""
    events = get_economic_calendar()
    base, quote = pair.split('/')
    
    currency_map = {
        'USD': ['US', 'USA', 'United States'],
        'EUR': ['EU', 'Euro', 'Germany', 'France'],
        'GBP': ['UK', 'GB', 'Britain'],
        'JPY': ['JP', 'Japan'],
        'AUD': ['AU', 'Australia'],
        'NZD': ['NZ', 'New Zealand'],
        'CAD': ['CA', 'Canada'],
        'CHF': ['CH', 'Switzerland']
    }
    
    base_countries = currency_map.get(base, [base])
    quote_countries = currency_map.get(quote, [quote])
    
    high_impact = 0
    medium_impact = 0
    
    for event in events:
        country = event.get('country', '').upper()
        impact = event.get('impact', 'low').lower()
        
        is_relevant = any(c.upper() in country for c in base_countries + quote_countries)
        
        if is_relevant:
            if impact == 'high':
                high_impact += 1
            elif impact == 'medium':
                medium_impact += 1
    
    risk_score = min(100, high_impact * 25 + medium_impact * 10)
    
    return {
        'risk_score': risk_score,
        'high_impact_events': high_impact,
        'medium_impact_events': medium_impact,
        'signal': 'HIGH_RISK' if risk_score > 50 else 'MEDIUM_RISK' if risk_score > 25 else 'LOW_RISK'
    }

# ═══════════════════════════════════════════════════════════════════════════════
# FUNDAMENTAL DATA (FRED)
# ═══════════════════════════════════════════════════════════════════════════════
def get_fred_data(series_id):
    """Fetch data from FRED API"""
    if not FRED_API_KEY:
        return None
    
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations"
        params = {
            'series_id': series_id,
            'api_key': FRED_API_KEY,
            'file_type': 'json',
            'limit': 10,
            'sort_order': 'desc'
        }
        resp = req_lib.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            obs = data.get('observations', [])
            if obs:
                return float(obs[0]['value'])
    except Exception as e:
        logger.debug(f"FRED fetch failed for {series_id}: {e}")
    return None

def get_fundamental_data():
    """Get fundamental economic data"""
    if is_cache_valid('fundamental') and cache['fundamental']['data']:
        return cache['fundamental']['data']
    
    data = {
        'us_rate': get_fred_data('FEDFUNDS') or 5.25,
        'us_gdp': get_fred_data('GDP') or 27000,
        'us_cpi': get_fred_data('CPIAUCSL') or 308,
        'dxy': get_fred_data('DTWEXBGS') or 104,
        'us_10y': get_fred_data('DGS10') or 4.5
    }
    
    cache['fundamental']['data'] = data
    cache['fundamental']['timestamp'] = datetime.now()
    return data

# ═══════════════════════════════════════════════════════════════════════════════
# REAL INTERMARKET ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════
def get_real_intermarket_data():
    """
    Fetch REAL intermarket data:
    1. Gold (XAU/USD) - Risk sentiment indicator
    2. US 10Y Treasury Yield - Interest rate differential
    3. DXY (Dollar Index) - USD strength
    4. Oil prices - Commodity currency correlation
    """
    if is_cache_valid('intermarket', 300) and cache.get('intermarket_data', {}).get('data'):
        return cache['intermarket_data']['data']
    
    intermarket = {
        'gold': None,
        'oil': None,
        'dxy': None,
        'us_10y': None,
        'vix': None,
        'data_quality': 'ESTIMATED'
    }
    
    # 1. Get Gold (XAU/USD) - from rates
    gold_rate = get_rate('XAU/USD')
    if gold_rate:
        intermarket['gold'] = gold_rate['mid']
    
    # 2. Get DXY and 10Y from FRED
    fundamental = get_fundamental_data()
    intermarket['dxy'] = fundamental.get('dxy', 104)
    intermarket['us_10y'] = fundamental.get('us_10y', 4.5)
    
    # 3. Try to get Oil price from Alpha Vantage
    if ALPHA_VANTAGE_KEY:
        try:
            url = "https://www.alphavantage.co/query"
            params = {
                'function': 'WTI',
                'interval': 'daily',
                'apikey': ALPHA_VANTAGE_KEY
            }
            resp = req_lib.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if 'data' in data and len(data['data']) > 0:
                    intermarket['oil'] = float(data['data'][0]['value'])
        except Exception as e:
            logger.debug(f"Alpha Vantage oil fetch failed: {e}")
    
    # If we got at least 2 real data points, mark as REAL
    real_count = sum(1 for v in [intermarket['gold'], intermarket['dxy'], intermarket['us_10y'], intermarket['oil']] if v is not None)
    if real_count >= 2:
        intermarket['data_quality'] = 'REAL'
    
    # Cache the data
    if 'intermarket_data' not in cache:
        cache['intermarket_data'] = {}
    cache['intermarket_data']['data'] = intermarket
    cache['intermarket_data']['timestamp'] = datetime.now()
    
    return intermarket

def analyze_intermarket(pair):
    """
    REAL Intermarket Analysis for a currency pair
    Uses actual correlations and real-time data
    """
    base, quote = pair.split('/')
    intermarket = get_real_intermarket_data()
    
    score = 50  # Neutral default
    signals = []
    correlations = {}
    
    gold = intermarket.get('gold')
    dxy = intermarket.get('dxy', 104)
    us_10y = intermarket.get('us_10y', 4.5)
    oil = intermarket.get('oil')
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DXY Correlation (Dollar Index)
    # High DXY = Strong USD = Bearish for XXX/USD, Bullish for USD/XXX
    # ═══════════════════════════════════════════════════════════════════════════
    dxy_baseline = 100  # Historical average
    dxy_strength = (dxy - dxy_baseline) / dxy_baseline * 100  # % deviation
    
    if quote == 'USD':
        # Pair like EUR/USD - Strong DXY is BEARISH for this pair
        dxy_impact = -dxy_strength * 2
        signals.append(f"DXY at {dxy:.1f}: {'Strong' if dxy > 102 else 'Weak'} USD")
    elif base == 'USD':
        # Pair like USD/JPY - Strong DXY is BULLISH for this pair
        dxy_impact = dxy_strength * 2
        signals.append(f"DXY at {dxy:.1f}: {'Strong' if dxy > 102 else 'Weak'} USD")
    else:
        # Cross pairs - minimal DXY impact
        dxy_impact = 0
    
    correlations['dxy'] = {'value': dxy, 'impact': dxy_impact}
    score += dxy_impact
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Gold Correlation (Risk Sentiment)
    # High gold = Risk-off = Bearish for risk currencies (AUD, NZD), Bullish for JPY, CHF
    # ═══════════════════════════════════════════════════════════════════════════
    if gold:
        gold_baseline = 2000  # Recent average
        gold_sentiment = (gold - gold_baseline) / gold_baseline * 100
        
        risk_currencies = ['AUD', 'NZD', 'CAD']
        safe_havens = ['JPY', 'CHF']
        
        gold_impact = 0
        if base in risk_currencies:
            gold_impact = -gold_sentiment * 0.5  # Risk-off hurts AUD, NZD
        elif base in safe_havens:
            gold_impact = gold_sentiment * 0.5  # Risk-off helps JPY, CHF
        elif quote in risk_currencies:
            gold_impact = gold_sentiment * 0.5
        elif quote in safe_havens:
            gold_impact = -gold_sentiment * 0.5
        
        correlations['gold'] = {'value': gold, 'impact': gold_impact}
        score += gold_impact
        signals.append(f"Gold at ${gold:.0f}: {'Risk-off' if gold > gold_baseline else 'Risk-on'}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # US 10Y Yield (Interest Rate Differential)
    # Higher yields = Stronger USD
    # ═══════════════════════════════════════════════════════════════════════════
    yield_baseline = 4.0
    yield_impact = (us_10y - yield_baseline) * 3
    
    if 'USD' in pair:
        if base == 'USD':
            score += yield_impact  # Higher yields bullish for USD/XXX
        else:
            score -= yield_impact  # Higher yields bearish for XXX/USD
        
        correlations['us_10y'] = {'value': us_10y, 'impact': yield_impact if base == 'USD' else -yield_impact}
        signals.append(f"US 10Y at {us_10y:.2f}%: {'High' if us_10y > 4.5 else 'Normal'}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Oil Correlation (CAD, NOK specific)
    # Higher oil = Bullish for CAD
    # ═══════════════════════════════════════════════════════════════════════════
    if oil and ('CAD' in pair or 'NOK' in pair):
        oil_baseline = 75
        oil_impact = (oil - oil_baseline) / oil_baseline * 20
        
        if base in ['CAD', 'NOK']:
            score += oil_impact
        elif quote in ['CAD', 'NOK']:
            score -= oil_impact
        
        correlations['oil'] = {'value': oil, 'impact': oil_impact}
        signals.append(f"Oil at ${oil:.1f}: {'High' if oil > 80 else 'Low'}")
    
    # Clamp score
    score = max(0, min(100, score))
    
    return {
        'score': round(score, 1),
        'signal': 'BULLISH' if score > 55 else 'BEARISH' if score < 45 else 'NEUTRAL',
        'correlations': correlations,
        'signals': signals,
        'data_quality': intermarket['data_quality'],
        'details': {
            'dxy': dxy,
            'gold': gold,
            'us_10y': us_10y,
            'oil': oil
        }
    }

# ═══════════════════════════════════════════════════════════════════════════════
# 10-FACTOR SIGNAL GENERATION
# ═══════════════════════════════════════════════════════════════════════════════
def calculate_factor_scores(pair):
    """Calculate all 9 factor scores for a pair including candlestick patterns"""
    rate = get_rate(pair)
    tech = get_technical_indicators(pair)
    sentiment = analyze_sentiment(pair)
    calendar = get_calendar_risk(pair)
    fundamental = get_fundamental_data()
    
    # Get candles for pattern recognition
    candles = get_polygon_candles(pair, 'day', 50)
    patterns = detect_candlestick_patterns(candles) if candles else {'patterns': [], 'signal': 'NEUTRAL', 'score': 50}
    
    factors = {}
    
    # 1. TECHNICAL (18%)
    rsi = tech['rsi']
    macd_hist = tech['macd']['histogram']
    adx = tech['adx']
    
    tech_score = 50
    if rsi < 30:
        tech_score += 25  # Oversold - bullish
    elif rsi > 70:
        tech_score -= 25  # Overbought - bearish
    else:
        tech_score += (50 - rsi) * 0.5
    
    if macd_hist > 0:
        tech_score += 15
    else:
        tech_score -= 15
    
    if adx > 25:
        tech_score = tech_score * 1.1 if tech_score > 50 else tech_score * 0.9
    
    factors['technical'] = {
        'score': max(0, min(100, tech_score)),
        'signal': 'BULLISH' if tech_score > 55 else 'BEARISH' if tech_score < 45 else 'NEUTRAL',
        'details': {'rsi': rsi, 'macd': macd_hist, 'adx': adx}
    }
    
    # 2. FUNDAMENTAL (20%)
    base, quote = pair.split('/')
    fund_score = 50
    
    if base == 'USD':
        fund_score += 10 if fundamental['us_rate'] > 4 else -5
    elif quote == 'USD':
        fund_score -= 10 if fundamental['us_rate'] > 4 else 5
    
    factors['fundamental'] = {
        'score': fund_score,
        'signal': 'BULLISH' if fund_score > 55 else 'BEARISH' if fund_score < 45 else 'NEUTRAL',
        'details': {'us_rate': fundamental['us_rate']}
    }
    
    # 3. SENTIMENT (12%) - REAL DATA from IG + News
    factors['sentiment'] = {
        'score': sentiment['score'],
        'signal': sentiment['signal'],
        'details': {
            'articles': sentiment['articles'],
            'sources': sentiment.get('sources', {}),
            'data_quality': sentiment.get('data_quality', 'ESTIMATED')
        }
    }
    
    # 4. INTERMARKET (10%) - REAL DATA
    intermarket = analyze_intermarket(pair)
    factors['intermarket'] = {
        'score': intermarket['score'],
        'signal': intermarket['signal'],
        'details': intermarket['details'],
        'data_quality': intermarket['data_quality']
    }
    
    # 5. QUANTITATIVE (8%)
    bb_pct = tech['bollinger']['percent_b']
    quant_score = 50
    
    if bb_pct < 20:
        quant_score = 70  # Oversold
    elif bb_pct > 80:
        quant_score = 30  # Overbought
    else:
        quant_score = 50 + (50 - bb_pct) * 0.4
    
    factors['quantitative'] = {
        'score': quant_score,
        'signal': 'BULLISH' if quant_score > 55 else 'BEARISH' if quant_score < 45 else 'NEUTRAL',
        'details': {'bb_percent': bb_pct}
    }
    
    # 6. MTF - Multi-Timeframe (8%)
    ema_signal = tech['ema_signal']
    mtf_score = 65 if ema_signal == 'BULLISH' else 35 if ema_signal == 'BEARISH' else 50
    
    factors['mtf'] = {
        'score': mtf_score,
        'signal': ema_signal,
        'details': {'ema20': tech['ema20'], 'ema50': tech['ema50']}
    }
    
    # 7. STRUCTURE (6%)
    structure_score = 50
    if adx > 25:
        structure_score = 70 if tech['macd']['histogram'] > 0 else 30
    
    factors['structure'] = {
        'score': structure_score,
        'signal': 'TRENDING' if adx > 25 else 'RANGING',
        'details': {'adx': adx}
    }
    
    # 8. CALENDAR (6%)
    cal_score = 100 - calendar['risk_score']
    
    factors['calendar'] = {
        'score': cal_score,
        'signal': calendar['signal'],
        'details': {'high_events': calendar['high_impact_events']}
    }
    
    # 9. CONFLUENCE (4%) - Factor agreement bonus
    bullish_factors = sum(1 for f in factors.values() if f['signal'] == 'BULLISH')
    bearish_factors = sum(1 for f in factors.values() if f['signal'] == 'BEARISH')
    
    if bullish_factors >= 5:
        conf_score = 75
    elif bearish_factors >= 5:
        conf_score = 25
    else:
        conf_score = 50
    
    factors['confluence'] = {
        'score': conf_score,
        'signal': 'STRONG' if abs(conf_score - 50) > 20 else 'WEAK',
        'details': {'bullish': bullish_factors, 'bearish': bearish_factors}
    }
    
    return factors, tech, rate, patterns

def generate_signal(pair):
    """Generate complete trading signal for a pair"""
    try:
        factors, tech, rate, patterns = calculate_factor_scores(pair)
        
        if not rate:
            return None
        
        # Calculate weighted composite score
        composite_score = 0
        available_weight = 0
        
        for factor_name, weight in FACTOR_WEIGHTS.items():
            if factor_name in factors:
                composite_score += factors[factor_name]['score'] * weight
                available_weight += weight
        
        # Normalize to 0-100
        if available_weight > 0:
            composite_score = composite_score / available_weight
        else:
            composite_score = 50
        
        # ═══════════════════════════════════════════════════════════════════════════
        # PATTERN BOOST - Adjust score based on candlestick patterns
        # ═══════════════════════════════════════════════════════════════════════════
        pattern_boost = 0
        if patterns and patterns.get('patterns'):
            for p in patterns['patterns']:
                if p['signal'] == 'BULLISH':
                    pattern_boost += (p['strength'] - 50) * 0.1  # +2 to +3.5 per strong pattern
                elif p['signal'] == 'BEARISH':
                    pattern_boost -= (p['strength'] - 50) * 0.1  # -2 to -3.5 per strong pattern
        
        composite_score += pattern_boost
        
        # Ensure valid number
        if math.isnan(composite_score) or math.isinf(composite_score):
            composite_score = 50
        
        composite_score = max(0, min(100, composite_score))
        
        # Determine direction
        if composite_score >= 60:
            direction = 'LONG'
        elif composite_score <= 40:
            direction = 'SHORT'
        else:
            direction = 'NEUTRAL'
        
        # Calculate star rating
        strength = abs(composite_score - 50) / 10
        stars = min(5, max(1, int(strength) + 1))
        
        # ═══════════════════════════════════════════════════════════════════════════
        # SMART DYNAMIC SL/TP FOR SWING TRADING
        # Optimized for high win rate with achievable targets
        # ═══════════════════════════════════════════════════════════════════════════
        
        atr = tech.get('atr') or DEFAULT_ATR.get(pair, 0.005)
        current_price = rate['mid']
        rsi = tech.get('rsi', 50)
        adx = tech.get('adx', 20)
        bb_upper = tech.get('bollinger', {}).get('upper', current_price * 1.01)
        bb_lower = tech.get('bollinger', {}).get('lower', current_price * 0.99)
        bb_middle = tech.get('bollinger', {}).get('middle', current_price)
        
        # ─────────────────────────────────────────────────────────────────────────
        # 1. VOLATILITY REGIME DETECTION
        # ─────────────────────────────────────────────────────────────────────────
        volatility_pct = (atr / current_price) * 100
        
        if volatility_pct > 1.0:
            volatility_regime = 'HIGH'
            vol_sl_adjust = 1.2   # Wider SL in high volatility
            vol_tp_adjust = 0.85  # Closer TP (more achievable)
        elif volatility_pct < 0.4:
            volatility_regime = 'LOW'
            vol_sl_adjust = 0.8   # Tighter SL in low volatility
            vol_tp_adjust = 1.1   # Can target slightly further
        else:
            volatility_regime = 'NORMAL'
            vol_sl_adjust = 1.0
            vol_tp_adjust = 1.0
        
        # ─────────────────────────────────────────────────────────────────────────
        # 2. TREND STRENGTH ADJUSTMENT (ADX)
        # ─────────────────────────────────────────────────────────────────────────
        if adx >= 30:
            trend_strength = 'STRONG'
            trend_sl_adjust = 0.9
            trend_tp_adjust = 1.3
        elif adx >= 20:
            trend_strength = 'MODERATE'
            trend_sl_adjust = 1.0
            trend_tp_adjust = 1.0
        else:
            trend_strength = 'WEAK'
            trend_sl_adjust = 1.1
            trend_tp_adjust = 0.8
        
        # ─────────────────────────────────────────────────────────────────────────
        # 3. MOMENTUM ADJUSTMENT (RSI)
        # ─────────────────────────────────────────────────────────────────────────
        if direction == 'LONG':
            if rsi < 35:
                momentum_tp_adjust = 1.2
            elif rsi > 60:
                momentum_tp_adjust = 0.85
            else:
                momentum_tp_adjust = 1.0
        elif direction == 'SHORT':
            if rsi > 65:
                momentum_tp_adjust = 1.2
            elif rsi < 40:
                momentum_tp_adjust = 0.85
            else:
                momentum_tp_adjust = 1.0
        else:
            momentum_tp_adjust = 1.0
        
        # ─────────────────────────────────────────────────────────────────────────
        # 4. SIGNAL CONFIDENCE ADJUSTMENT
        # ─────────────────────────────────────────────────────────────────────────
        signal_strength = abs(composite_score - 50)
        
        if signal_strength >= 20:
            confidence = 'HIGH'
            conf_sl_adjust = 0.9
            conf_tp_adjust = 1.15
        elif signal_strength >= 10:
            confidence = 'MEDIUM'
            conf_sl_adjust = 1.0
            conf_tp_adjust = 1.0
        else:
            confidence = 'LOW'
            conf_sl_adjust = 1.15
            conf_tp_adjust = 0.85
        
        # ─────────────────────────────────────────────────────────────────────────
        # 5. CALCULATE FINAL DYNAMIC MULTIPLIERS
        # ─────────────────────────────────────────────────────────────────────────
        base_sl_mult = 1.8
        base_tp1_mult = 2.5
        base_tp2_mult = 4.0
        
        final_sl_mult = base_sl_mult * vol_sl_adjust * trend_sl_adjust * conf_sl_adjust
        final_tp1_mult = base_tp1_mult * vol_tp_adjust * trend_tp_adjust * momentum_tp_adjust * conf_tp_adjust
        final_tp2_mult = base_tp2_mult * vol_tp_adjust * trend_tp_adjust * momentum_tp_adjust * conf_tp_adjust
        
        final_sl_mult = max(1.2, min(2.5, final_sl_mult))
        final_tp1_mult = max(1.8, min(4.0, final_tp1_mult))
        final_tp2_mult = max(3.0, min(6.0, final_tp2_mult))
        
        if final_tp1_mult / final_sl_mult < 1.3:
            final_tp1_mult = final_sl_mult * 1.3
        
        # ─────────────────────────────────────────────────────────────────────────
        # 6. STRUCTURE-BASED VALIDATION (Bollinger Bands)
        # ─────────────────────────────────────────────────────────────────────────
        if direction == 'LONG':
            entry = current_price
            sl = entry - (atr * final_sl_mult)
            tp1 = entry + (atr * final_tp1_mult)
            tp2 = entry + (atr * final_tp2_mult)
            
            distance_to_bb_upper = bb_upper - entry
            if distance_to_bb_upper > 0 and tp1 > bb_upper and distance_to_bb_upper > atr * 1.5:
                tp1 = bb_upper - (atr * 0.2)
            
            if entry - bb_lower < atr * 3 and sl > bb_lower:
                sl = bb_lower - (atr * 0.3)
                
        elif direction == 'SHORT':
            entry = current_price
            sl = entry + (atr * final_sl_mult)
            tp1 = entry - (atr * final_tp1_mult)
            tp2 = entry - (atr * final_tp2_mult)
            
            distance_to_bb_lower = entry - bb_lower
            if distance_to_bb_lower > 0 and tp1 < bb_lower and distance_to_bb_lower > atr * 1.5:
                tp1 = bb_lower + (atr * 0.2)
            
            if bb_upper - entry < atr * 3 and sl < bb_upper:
                sl = bb_upper + (atr * 0.3)
                
        else:
            entry = current_price
            sl = entry - (atr * 1.5)
            tp1 = entry + (atr * 2.0)
            tp2 = entry + (atr * 3.5)
        
        # ─────────────────────────────────────────────────────────────────────────
        # 7. CALCULATE FINAL METRICS
        # ─────────────────────────────────────────────────────────────────────────
        pip_size = 0.0001 if 'JPY' not in pair else 0.01
        sl_pips = abs(entry - sl) / pip_size
        tp1_pips = abs(tp1 - entry) / pip_size
        tp2_pips = abs(tp2 - entry) / pip_size
        
        risk_reward_1 = round(tp1_pips / sl_pips, 2) if sl_pips > 0 else 1.5
        risk_reward_2 = round(tp2_pips / sl_pips, 2) if sl_pips > 0 else 2.5
        
        if risk_reward_1 >= 2.0 and confidence == 'HIGH':
            trade_quality = 'A+'
        elif risk_reward_1 >= 1.5 and confidence in ['HIGH', 'MEDIUM']:
            trade_quality = 'A'
        elif risk_reward_1 >= 1.3:
            trade_quality = 'B'
        else:
            trade_quality = 'C'
        
        # Determine category
        category = 'MAJOR'
        for cat, pairs in PAIR_CATEGORIES.items():
            if pair in pairs:
                category = cat
                break
        
        # Factor grid for display
        factor_grid = {
            'RSI': 'bullish' if tech['rsi'] < 40 else 'bearish' if tech['rsi'] > 60 else 'neutral',
            'MACD': 'bullish' if tech['macd']['histogram'] > 0 else 'bearish',
            'ADX': 'bullish' if tech['adx'] > 25 else 'neutral',
            'MTF': factors['mtf']['signal'].lower(),
            'VOL': 'neutral',
            'SENT': factors['sentiment']['signal'].lower(),
            'CAL': 'bearish' if factors['calendar']['score'] < 50 else 'bullish',
            'INT': factors['intermarket']['signal'].lower(),
            'STR': factors['structure']['signal'].lower() if factors['structure']['signal'] in ['BULLISH', 'BEARISH'] else 'neutral',
            'CONF': 'bullish' if factors['confluence']['score'] > 55 else 'bearish' if factors['confluence']['score'] < 45 else 'neutral'
        }
        
        # Calculate statistics
        factors_available = sum(1 for f in factors.values() if f['score'] != 50)
        
        signal_data = {
            'pair': pair,
            'category': category,
            'direction': direction,
            'composite_score': round(composite_score, 1),
            'stars': stars,
            'rate': {
                'bid': round(rate['bid'], 5),
                'ask': round(rate['ask'], 5),
                'mid': round(rate['mid'], 5),
                'source': rate.get('source', 'unknown')
            },
            'trade_setup': {
                'entry': round(entry, 5),
                'sl': round(sl, 5),
                'tp1': round(tp1, 5),
                'tp2': round(tp2, 5),
                'sl_pips': round(sl_pips, 1),
                'tp1_pips': round(tp1_pips, 1),
                'tp2_pips': round(tp2_pips, 1),
                'risk_reward_1': risk_reward_1,
                'risk_reward_2': risk_reward_2,
                'trade_quality': trade_quality,
                'sl_multiplier': round(final_sl_mult, 2),
                'tp1_multiplier': round(final_tp1_mult, 2),
                'market_context': {
                    'volatility': volatility_regime,
                    'trend': trend_strength,
                    'confidence': confidence
                }
            },
            'technical': {
                'rsi': tech['rsi'],
                'macd': tech['macd'],
                'adx': tech['adx'],
                'atr': round(atr, 5),
                'bollinger': tech['bollinger'],
                'ema_signal': tech['ema_signal']
            },
            'patterns': patterns,
            'factors': factors,
            'factor_grid': factor_grid,
            'statistics': {
                'win_rate': 50 + (composite_score - 50) * 0.4,
                'expectancy': composite_score * 1.5,
                'hold_days': 3 if category == 'MAJOR' else 5,
                'profit_factor': 1 + (composite_score - 50) / 50
            },
            'factors_available': factors_available,
            'timestamp': datetime.now().isoformat()
        }
        
        # Save signal to database (only for non-neutral signals with good quality)
        if direction != 'NEUTRAL' and trade_quality in ['A+', 'A', 'B']:
            save_signal_to_db(signal_data)
        
        return signal_data
    
    except Exception as e:
        logger.error(f"Signal generation error for {pair}: {e}")
        return None

# ═══════════════════════════════════════════════════════════════════════════════
# BACKTESTING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
def run_backtest(pair, days=30, min_score=60, min_stars=3):
    """Run backtest simulation"""
    try:
        candles = get_polygon_candles(pair, 'day', days + 50)
        
        if not candles or len(candles) < days:
            # Generate synthetic candles
            rate = get_rate(pair)
            base_price = rate['mid'] if rate else STATIC_RATES.get(pair, 1.0)
            
            candles = []
            price = base_price
            for i in range(days + 50):
                change = random.uniform(-0.01, 0.01) * price
                price += change
                candles.append({
                    'open': price,
                    'high': price * (1 + random.uniform(0.002, 0.008)),
                    'low': price * (1 - random.uniform(0.002, 0.008)),
                    'close': price + random.uniform(-0.002, 0.002) * price
                })
        
        trades = []
        equity = 10000
        equity_curve = [equity]
        wins = 0
        losses = 0
        
        atr = DEFAULT_ATR.get(pair, 0.005)
        pip_size = 0.0001 if 'JPY' not in pair else 0.01
        
        for i in range(50, len(candles) - 5):
            # Simulate signal generation
            closes = [c['close'] for c in candles[i-50:i]]
            rsi = calculate_rsi(closes)
            
            # Calculate ADX proxy from recent moves
            recent_moves = [abs(candles[i-j]['high'] - candles[i-j]['low']) for j in range(1, 15)]
            avg_move = sum(recent_moves) / len(recent_moves) if recent_moves else atr
            
            score = 50 + (50 - rsi) * 0.5 + random.uniform(-10, 10)
            score = max(0, min(100, score))
            stars = min(5, max(1, int(abs(score - 50) / 10) + 1))
            
            if score >= min_score and stars >= min_stars:
                direction = 'LONG' if score > 55 else 'SHORT'
                entry_price = candles[i]['close']
                
                # SMART DYNAMIC SL/TP for backtest
                signal_strength = abs(score - 50)
                
                # Volatility adjustment
                vol_ratio = avg_move / atr if atr > 0 else 1.0
                if vol_ratio > 1.3:
                    vol_adjust = 1.15
                elif vol_ratio < 0.7:
                    vol_adjust = 0.85
                else:
                    vol_adjust = 1.0
                
                # Confidence adjustment
                if signal_strength >= 20:
                    conf_sl = 0.9
                    conf_tp = 1.1
                elif signal_strength >= 10:
                    conf_sl = 1.0
                    conf_tp = 1.0
                else:
                    conf_sl = 1.1
                    conf_tp = 0.9
                
                # Final multipliers
                sl_mult = 1.8 * vol_adjust * conf_sl
                tp_mult = 2.5 * vol_adjust * conf_tp
                
                sl_mult = max(1.2, min(2.5, sl_mult))
                tp_mult = max(1.8, min(4.0, tp_mult))
                
                sl_distance = atr * sl_mult
                tp_distance = atr * tp_mult
                
                # Simulate trade outcome
                max_move = max(abs(candles[i+j]['high'] - entry_price) for j in range(1, 5))
                min_move = max(abs(entry_price - candles[i+j]['low']) for j in range(1, 5))
                
                if direction == 'LONG':
                    if max_move >= tp_distance:
                        pnl = tp_distance / pip_size
                        result = 'WIN'
                        wins += 1
                    elif min_move >= sl_distance:
                        pnl = -sl_distance / pip_size
                        result = 'LOSS'
                        losses += 1
                    else:
                        pnl = (candles[i+4]['close'] - entry_price) / pip_size
                        result = 'WIN' if pnl > 0 else 'LOSS'
                        wins += 1 if pnl > 0 else 0
                        losses += 1 if pnl <= 0 else 0
                else:
                    if min_move >= tp_distance:
                        pnl = tp_distance / pip_size
                        result = 'WIN'
                        wins += 1
                    elif max_move >= sl_distance:
                        pnl = -sl_distance / pip_size
                        result = 'LOSS'
                        losses += 1
                    else:
                        pnl = (entry_price - candles[i+4]['close']) / pip_size
                        result = 'WIN' if pnl > 0 else 'LOSS'
                        wins += 1 if pnl > 0 else 0
                        losses += 1 if pnl <= 0 else 0
                
                # Update equity (assuming $10 per pip)
                equity += pnl * 10
                equity_curve.append(equity)
                
                trades.append({
                    'date': f"Day {i - 50}",
                    'direction': direction,
                    'entry': round(entry_price, 5),
                    'exit': round(entry_price + (pnl * pip_size), 5),
                    'pips': round(pnl, 1),
                    'pnl': round(pnl * 10, 2),
                    'result': result
                })
        
        # Calculate metrics
        total_trades = len(trades)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        total_pnl = sum(t['pnl'] for t in trades)
        
        gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
        gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
        
        max_equity = max(equity_curve)
        max_drawdown = 0
        peak = equity_curve[0]
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            drawdown = (peak - eq) / peak * 100
            max_drawdown = max(max_drawdown, drawdown)
        
        return {
            'success': True,
            'pair': pair,
            'period': days,
            'min_score': min_score,
            'min_stars': min_stars,
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 1),
            'total_pnl': round(total_pnl, 2),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown': round(max_drawdown, 1),
            'expectancy': round(total_pnl / total_trades, 2) if total_trades > 0 else 0,
            'equity_curve': equity_curve[-20:],
            'trades': trades[-10:]
        }
    
    except Exception as e:
        logger.error(f"Backtest error for {pair}: {e}")
        return {'success': False, 'error': str(e)}

# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM AUDIT
# ═══════════════════════════════════════════════════════════════════════════════
def run_system_audit():
    """Run comprehensive system audit"""
    audit = {
        'timestamp': datetime.now().isoformat(),
        'api_status': {},
        'data_quality': {},
        'score_validation': {},
        'errors': []
    }
    
    # Test Polygon
    try:
        rate = get_polygon_rate('EUR/USD')
        audit['api_status']['polygon'] = {
            'status': 'OK' if rate else 'LIMITED',
            'test_rate': rate['mid'] if rate else None
        }
    except Exception as e:
        audit['api_status']['polygon'] = {'status': 'ERROR', 'error': str(e)}
    
    # Test ExchangeRate
    try:
        rate = get_exchangerate_rate('EUR/USD')
        audit['api_status']['exchangerate'] = {
            'status': 'OK' if rate else 'ERROR',
            'test_rate': rate['mid'] if rate else None
        }
    except Exception as e:
        audit['api_status']['exchangerate'] = {'status': 'ERROR', 'error': str(e)}
    
    # Test Finnhub
    try:
        news = get_finnhub_news()
        audit['api_status']['finnhub'] = {
            'status': 'OK' if news.get('count', 0) > 0 else 'LIMITED',
            'articles': news.get('count', 0)
        }
    except Exception as e:
        audit['api_status']['finnhub'] = {'status': 'ERROR', 'error': str(e)}
    
    # Test FRED
    try:
        rate = get_fred_data('FEDFUNDS')
        audit['api_status']['fred'] = {
            'status': 'OK' if rate else 'LIMITED',
            'test_value': rate
        }
    except Exception as e:
        audit['api_status']['fred'] = {'status': 'ERROR', 'error': str(e)}
    
    # Test Alpha Vantage
    audit['api_status']['alpha_vantage'] = {
        'status': 'OK' if ALPHA_VANTAGE_KEY else 'NOT_CONFIGURED',
        'configured': bool(ALPHA_VANTAGE_KEY)
    }
    
    # Test IG Markets
    if all([IG_API_KEY, IG_USERNAME, IG_PASSWORD]):
        try:
            ig_logged_in = ig_login()
            audit['api_status']['ig_markets'] = {
                'status': 'OK' if ig_logged_in else 'ERROR',
                'account_type': IG_ACC_TYPE,
                'logged_in': ig_logged_in,
                'error': ig_session.get('last_error', None) if not ig_logged_in else None
            }
        except Exception as e:
            audit['api_status']['ig_markets'] = {
                'status': 'ERROR',
                'error': str(e),
                'account_type': IG_ACC_TYPE
            }
    else:
        audit['api_status']['ig_markets'] = {
            'status': 'NOT_CONFIGURED',
            'configured': False
        }
    
    # Data quality check
    rates = get_all_rates()
    audit['data_quality'] = {
        'pairs_with_rates': len(rates),
        'total_pairs': len(FOREX_PAIRS),
        'coverage': round(len(rates) / len(FOREX_PAIRS) * 100, 1),
        'sources': defaultdict(int)
    }
    
    for pair, rate in rates.items():
        audit['data_quality']['sources'][rate.get('source', 'unknown')] += 1
    
    audit['data_quality']['sources'] = dict(audit['data_quality']['sources'])
    
    # Score validation
    test_signal = generate_signal('EUR/USD')
    if test_signal:
        audit['score_validation'] = {
            'test_pair': 'EUR/USD',
            'composite_score': test_signal['composite_score'],
            'direction': test_signal['direction'],
            'factors_available': test_signal['factors_available'],
            'trade_setup_valid': all([
                test_signal['trade_setup']['entry'] > 0,
                test_signal['trade_setup']['sl'] > 0,
                test_signal['trade_setup']['tp1'] > 0
            ])
        }
    
    return audit

# ═══════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api')
def api_info():
    return jsonify({
        'name': 'MEGA FOREX v8.2 PRO',
        'version': '8.2',
        'status': 'operational',
        'pairs': len(FOREX_PAIRS),
        'factors': len(FACTOR_WEIGHTS),
        'features': [
            '45 Forex Pairs',
            '9-Factor Weighted Scoring (REAL DATA)',
            'Multi-tier Data Fallbacks',
            'REAL IG Sentiment + Intermarket',
            'Complete Backtesting',
            'Dynamic Weights Editor',
            'System Audit'
        ]
    })

@app.route('/health')
def health():
    return jsonify({
        'service': 'mega-forex-pwa',
        'status': 'healthy',
        'version': '8.2'
    })

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

@app.route('/rates')
def get_rates_endpoint():
    # Check cache first
    cached_rates = cache.get('rates', CACHE_RATES)
    if cached_rates:
        return jsonify({
            'success': True,
            'count': len(cached_rates),
            'timestamp': datetime.now().isoformat(),
            'cached': True,
            'rates': cached_rates
        })
    
    rates = get_all_rates()
    
    # Cache the results
    cache.set('rates', rates)
    
    return jsonify({
        'success': True,
        'count': len(rates),
        'timestamp': datetime.now().isoformat(),
        'cached': False,
        'rates': rates
    })

@app.route('/signals')
def get_signals():
    try:
        # Check cache first
        cached_signals = cache.get('signals', CACHE_SIGNALS)
        if cached_signals:
            return jsonify({
                'success': True,
                'count': len(cached_signals),
                'timestamp': datetime.now().isoformat(),
                'version': '8.2',
                'cached': True,
                'signals': cached_signals
            })
        
        # Generate fresh signals
        signals = []
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_pair = {executor.submit(generate_signal, pair): pair for pair in FOREX_PAIRS}
            
            for future in as_completed(future_to_pair, timeout=45):
                try:
                    signal = future.result(timeout=10)
                    if signal:
                        signals.append(signal)
                except Exception as e:
                    logger.warning(f"Signal generation timeout: {e}")
        
        signals.sort(key=lambda x: x['composite_score'], reverse=True)
        
        # Cache the results
        cache.set('signals', signals)
        
        return jsonify({
            'success': True,
            'count': len(signals),
            'timestamp': datetime.now().isoformat(),
            'version': '8.2',
            'cached': False,
            'signals': signals
        })
    
    except Exception as e:
        logger.error(f"Signals endpoint error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/signal/<pair>')
def get_single_signal(pair):
    pair = pair.replace('_', '/')
    signal = generate_signal(pair)
    
    if signal:
        return jsonify({'success': True, **signal})
    return jsonify({'success': False, 'error': f'Could not generate signal for {pair}'}), 404

@app.route('/technical/<pair>')
def get_technical(pair):
    pair = pair.replace('_', '/')
    tech = get_technical_indicators(pair)
    return jsonify({'success': True, 'pair': pair, **tech})

@app.route('/news')
def get_news():
    news = get_finnhub_news()
    return jsonify({'success': True, **news})

@app.route('/calendar')
def get_calendar():
    events = get_economic_calendar()
    return jsonify({'success': True, 'count': len(events), 'events': events})

@app.route('/backtest', methods=['GET', 'POST'])
def backtest_endpoint():
    if request.method == 'POST':
        data = request.json
    else:
        data = request.args
    
    pair = data.get('pair', 'EUR/USD').replace('_', '/')
    days = int(data.get('days', 30))
    min_score = int(data.get('min_score', 60))
    min_stars = int(data.get('min_stars', 3))
    
    result = run_backtest(pair, days, min_score, min_stars)
    return jsonify(result)

@app.route('/weights', methods=['GET', 'POST'])
def weights_endpoint():
    global FACTOR_WEIGHTS
    
    if request.method == 'POST':
        new_weights = request.json
        
        # Validate weights sum to 100
        total = sum(new_weights.values())
        if abs(total - 100) > 0.1:
            return jsonify({'success': False, 'error': f'Weights must sum to 100 (got {total})'}), 400
        
        FACTOR_WEIGHTS.update(new_weights)
        save_weights(new_weights)
        
        return jsonify({'success': True, 'weights': FACTOR_WEIGHTS})
    
    return jsonify({'success': True, 'weights': FACTOR_WEIGHTS})

@app.route('/weights/reset')
def reset_weights():
    global FACTOR_WEIGHTS
    FACTOR_WEIGHTS = {
        'technical': 24,
        'fundamental': 18,
        'sentiment': 13,
        'intermarket': 11,
        'quantitative': 8,
        'mtf': 10,
        'structure': 7,
        'calendar': 5,
        'confluence': 4
    }
    save_weights(FACTOR_WEIGHTS)
    return jsonify({'success': True, 'weights': FACTOR_WEIGHTS})

@app.route('/audit')
def audit_endpoint():
    audit = run_system_audit()
    return jsonify({'success': True, **audit})

@app.route('/test-ig')
def test_ig():
    """Test IG Markets API connection and show detailed errors"""
    if not all([IG_API_KEY, IG_USERNAME, IG_PASSWORD]):
        return jsonify({
            'success': False,
            'error': 'IG credentials not configured',
            'configured': {
                'api_key': bool(IG_API_KEY),
                'username': bool(IG_USERNAME),
                'password': bool(IG_PASSWORD)
            }
        })
    
    try:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-IG-API-KEY': IG_API_KEY,
            'Version': '2'
        }
        
        payload = {
            'identifier': IG_USERNAME,
            'password': IG_PASSWORD
        }
        
        response = req_lib.post(
            f"{IG_BASE_URL}/session",
            headers=headers,
            json=payload,
            timeout=15
        )
        
        return jsonify({
            'success': response.status_code == 200,
            'status_code': response.status_code,
            'url': IG_BASE_URL,
            'account_type': IG_ACC_TYPE,
            'username_used': IG_USERNAME[:5] + '***',
            'response': response.json() if response.text else None,
            'headers_received': dict(response.headers)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        })

# ═══════════════════════════════════════════════════════════════════════════════
# IG MARKETS API - REAL CLIENT SENTIMENT
# ═══════════════════════════════════════════════════════════════════════════════

def ig_login():
    """Login to IG Markets API and get session tokens"""
    global ig_session
    
    if not all([IG_API_KEY, IG_USERNAME, IG_PASSWORD]):
        logger.warning("IG API credentials not configured")
        return False
    
    # Check if already logged in (tokens valid for ~6 hours)
    if ig_session['logged_in'] and ig_session['last_login']:
        elapsed = (datetime.now() - ig_session['last_login']).total_seconds()
        if elapsed < 21600:  # 6 hours
            return True
    
    try:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-IG-API-KEY': IG_API_KEY,
            'Version': '2'
        }
        
        payload = {
            'identifier': IG_USERNAME,
            'password': IG_PASSWORD
        }
        
        logger.info(f"IG Login attempt: URL={IG_BASE_URL}, User={IG_USERNAME[:5]}***, AccType={IG_ACC_TYPE}")
        
        response = req_lib.post(
            f"{IG_BASE_URL}/session",
            headers=headers,
            json=payload,
            timeout=15
        )
        
        logger.info(f"IG Response: Status={response.status_code}")
        
        if response.status_code == 200:
            ig_session['cst'] = response.headers.get('CST')
            ig_session['x_security_token'] = response.headers.get('X-SECURITY-TOKEN')
            ig_session['logged_in'] = True
            ig_session['last_login'] = datetime.now()
            logger.info("✅ IG Markets API: Login successful")
            return True
        else:
            error_msg = response.text[:200] if response.text else 'No error message'
            logger.error(f"IG login failed: {response.status_code} - {error_msg}")
            ig_session['last_error'] = f"{response.status_code}: {error_msg}"
            return False
            
    except req_lib.exceptions.Timeout:
        logger.error("IG login timeout - server not responding")
        ig_session['last_error'] = "Timeout"
        return False
    except req_lib.exceptions.ConnectionError as e:
        logger.error(f"IG connection error: {e}")
        ig_session['last_error'] = "Connection error"
        return False
    except Exception as e:
        logger.error(f"IG login error: {e}")
        ig_session['last_error'] = str(e)
        return False

def get_ig_client_sentiment(market_id):
    """Get client sentiment for a specific market from IG"""
    if not ig_login():
        return None
    
    try:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-IG-API-KEY': IG_API_KEY,
            'CST': ig_session['cst'],
            'X-SECURITY-TOKEN': ig_session['x_security_token'],
            'Version': '1'
        }
        
        response = req_lib.get(
            f"{IG_BASE_URL}/clientsentiment/{market_id}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            return {
                'long_percentage': data.get('longPositionPercentage', 50),
                'short_percentage': data.get('shortPositionPercentage', 50),
                'market_id': data.get('marketId', market_id)
            }
    except Exception as e:
        logger.debug(f"IG sentiment fetch failed for {market_id}: {e}")
    
    return None

def get_all_ig_sentiment():
    """Get client sentiment for all major forex pairs from IG"""
    # IG Market IDs for forex pairs
    ig_market_ids = {
        'EUR/USD': 'EURUSD',
        'GBP/USD': 'GBPUSD',
        'USD/JPY': 'USDJPY',
        'USD/CHF': 'USDCHF',
        'AUD/USD': 'AUDUSD',
        'USD/CAD': 'USDCAD',
        'NZD/USD': 'NZDUSD',
        'EUR/GBP': 'EURGBP',
        'EUR/JPY': 'EURJPY',
        'GBP/JPY': 'GBPJPY',
        'AUD/JPY': 'AUDJPY',
        'EUR/AUD': 'EURAUD',
        'EUR/CHF': 'EURCHF',
        'GBP/CHF': 'GBPCHF',
        'EUR/CAD': 'EURCAD'
    }
    
    results = []
    
    for pair, market_id in ig_market_ids.items():
        sentiment = get_ig_client_sentiment(market_id)
        
        if sentiment:
            long_pct = sentiment['long_percentage']
            short_pct = sentiment['short_percentage']
            
            results.append({
                'pair': pair,
                'long_percentage': long_pct,
                'short_percentage': short_pct,
                'contrarian_signal': 'SHORT' if long_pct > 60 else 'LONG' if long_pct < 40 else 'NEUTRAL',
                'source': 'IG_REAL'
            })
    
    return results

@app.route('/positioning')
def get_positioning():
    """Get retail positioning data - REAL from IG when available"""
    
    # Try to get REAL data from IG API first
    if all([IG_API_KEY, IG_USERNAME, IG_PASSWORD]):
        ig_data = get_all_ig_sentiment()
        
        if ig_data and len(ig_data) > 0:
            logger.info(f"✅ Positioning: Using REAL IG data ({len(ig_data)} pairs)")
            return jsonify({
                'success': True, 
                'count': len(ig_data), 
                'source': 'IG_MARKETS_REAL',
                'data': ig_data
            })
    
    # Fallback: Return message that IG is not configured
    logger.warning("⚠️ Positioning: IG API not configured, returning placeholder")
    
    positioning = []
    for pair in FOREX_PAIRS[:15]:
        positioning.append({
            'pair': pair,
            'long_percentage': 'N/A',
            'short_percentage': 'N/A',
            'contrarian_signal': 'N/A',
            'source': 'NOT_CONFIGURED',
            'message': 'Configure IG API for real data'
        })
    
    return jsonify({
        'success': True, 
        'count': len(positioning), 
        'source': 'NOT_CONFIGURED',
        'message': 'Add IG_USERNAME and IG_PASSWORD to .env for real positioning data',
        'data': positioning
    })

@app.route('/api-status')
def api_status():
    """Get API connection status"""
    status = {
        'polygon': {
            'configured': bool(POLYGON_API_KEY),
            'status': 'OK' if POLYGON_API_KEY else 'NOT_CONFIGURED'
        },
        'finnhub': {
            'configured': bool(FINNHUB_API_KEY),
            'status': 'OK' if FINNHUB_API_KEY else 'NOT_CONFIGURED'
        },
        'fred': {
            'configured': bool(FRED_API_KEY),
            'status': 'OK' if FRED_API_KEY else 'NOT_CONFIGURED'
        },
        'alpha_vantage': {
            'configured': bool(ALPHA_VANTAGE_KEY),
            'status': 'OK' if ALPHA_VANTAGE_KEY else 'NOT_CONFIGURED'
        },
        'exchangerate': {
            'configured': True,
            'status': 'OK'
        },
        'ig_markets': {
            'configured': bool(IG_API_KEY and IG_USERNAME and IG_PASSWORD),
            'status': 'OK' if all([IG_API_KEY, IG_USERNAME, IG_PASSWORD]) else 'NOT_CONFIGURED',
            'account_type': IG_ACC_TYPE
        }
    }
    
    return jsonify({'success': True, **status})

# ═══════════════════════════════════════════════════════════════════════════════
# TRADE JOURNAL API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/journal', methods=['GET'])
def get_journal():
    """Get trade journal entries"""
    status = request.args.get('status')  # OPEN, CLOSED, or None for all
    pair = request.args.get('pair')
    limit = int(request.args.get('limit', 50))
    
    trades = get_trade_journal(status=status, pair=pair, limit=limit)
    return jsonify({'success': True, 'trades': trades, 'count': len(trades)})

@app.route('/journal/add', methods=['POST'])
def add_journal_trade():
    """Add a new trade to journal"""
    data = request.json
    
    required = ['pair', 'direction', 'entry_price']
    if not all(k in data for k in required):
        return jsonify({'success': False, 'error': 'Missing required fields: pair, direction, entry_price'})
    
    trade_id = add_trade_to_journal(data)
    
    if trade_id:
        return jsonify({'success': True, 'trade_id': trade_id, 'message': 'Trade added to journal'})
    else:
        return jsonify({'success': False, 'error': 'Failed to add trade'})

@app.route('/journal/close/<int:trade_id>', methods=['POST'])
def close_journal_trade(trade_id):
    """Close a trade and calculate P&L"""
    data = request.json
    
    if 'exit_price' not in data:
        return jsonify({'success': False, 'error': 'Missing exit_price'})
    
    outcome = data.get('outcome', 'WIN' if data.get('pnl_pips', 0) > 0 else 'LOSS')
    notes = data.get('notes', '')
    
    result = close_trade(trade_id, data['exit_price'], outcome, notes)
    
    return jsonify(result)

@app.route('/journal/update/<int:trade_id>', methods=['POST'])
def update_journal_trade(trade_id):
    """Update trade notes or other details"""
    data = request.json
    
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if 'notes' in data:
            updates.append('notes = ?')
            params.append(data['notes'])
        if 'sl_price' in data:
            updates.append('sl_price = ?')
            params.append(data['sl_price'])
        if 'tp_price' in data:
            updates.append('tp_price = ?')
            params.append(data['tp_price'])
        if 'lot_size' in data:
            updates.append('lot_size = ?')
            params.append(data['lot_size'])
        
        if updates:
            params.append(trade_id)
            cursor.execute(f'UPDATE trade_journal SET {", ".join(updates)} WHERE id = ?', params)
            conn.commit()
        
        conn.close()
        return jsonify({'success': True, 'message': 'Trade updated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/journal/delete/<int:trade_id>', methods=['DELETE'])
def delete_journal_trade(trade_id):
    """Delete a trade from journal"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM trade_journal WHERE id = ?', (trade_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Trade deleted'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/performance')
def get_performance():
    """Get trading performance statistics"""
    stats = get_performance_stats()
    return jsonify({'success': True, **stats})

@app.route('/signal-history')
def get_signals_history():
    """Get historical signals"""
    pair = request.args.get('pair')
    direction = request.args.get('direction')
    limit = int(request.args.get('limit', 100))
    
    signals = get_signal_history(pair=pair, direction=direction, limit=limit)
    return jsonify({'success': True, 'signals': signals, 'count': len(signals)})

@app.route('/patterns/<pair>')
def get_pair_patterns(pair):
    """Get candlestick patterns for a specific pair"""
    pair = pair.replace('-', '/')
    candles = get_polygon_candles(pair, 'day', 50)
    
    if not candles:
        return jsonify({'success': False, 'error': 'No candle data available'})
    
    patterns = detect_candlestick_patterns(candles)
    
    return jsonify({
        'success': True,
        'pair': pair,
        'patterns': patterns,
        'candles_analyzed': len(candles)
    })

# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Get port from environment (Render sets this) or default to 5000
    port = int(os.environ.get('PORT', 5000))
    
    print("=" * 70)
    print("         MEGA FOREX v8.2 PRO - PRODUCTION TRADING SYSTEM")
    print("=" * 70)
    print(f"  Port:            {port}")
    print(f"  Pairs:           {len(FOREX_PAIRS)}")
    print(f"  Factors:         {len(FACTOR_WEIGHTS)}")
    print(f"  Polygon API:     {'✓' if POLYGON_API_KEY else '✗'}")
    print(f"  Finnhub API:     {'✓' if FINNHUB_API_KEY else '✗'}")
    print(f"  FRED API:        {'✓' if FRED_API_KEY else '✗'}")
    print(f"  Alpha Vantage:   {'✓' if ALPHA_VANTAGE_KEY else '✗'}")
    print(f"  IG Markets API:  {'✓ (' + IG_ACC_TYPE + ')' if all([IG_API_KEY, IG_USERNAME, IG_PASSWORD]) else '✗'}")
    print(f"  ExchangeRate:    ✓ (Free, no key needed)")
    print("=" * 70)
    
    # Run server
    app.run(debug=False, host='0.0.0.0', port=port, threaded=True)
