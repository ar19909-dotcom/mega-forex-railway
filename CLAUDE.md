# MEGA FOREX PRO v9.6.2

## Project Overview
Professional forex & commodity signal dashboard powered by Flask. Generates real-time trading signals for 50 instruments (45 forex + 5 commodities) using an 11-factor scoring system with 10-gate quality filtering.

## Architecture
- **Backend**: `app.py` (~18,000 lines) — Flask, Python 3.11+
- **Frontend**: `templates/index.html` (~4,800 lines) — Single-page dashboard
- **Deployment**: Railway (Docker)
- **APIs**: Polygon.io (rates/candles), OpenAI GPT-4o-mini (AI synthesis), FRED (macro data), IG (sentiment), Alpha Vantage (VIX/Oil)

## 11-Factor Scoring System (v9.6.0)
| # | Factor Group | Forex Weight | Commodity Weight |
|---|---|---|---|
| 1 | Trend & Momentum | 20% | 22% |
| 2 | Fundamental | 13% | 12% |
| 3 | Sentiment | 10% | 10% |
| 4 | Intermarket | 9% | 14% |
| 5 | Mean Reversion | 11% | 10% |
| 6 | Calendar Risk | 6% | 5% |
| 7 | AI Synthesis | 8% | 7% |
| 8 | Currency Strength / Supply-Demand | 8% | 7% |
| 9 | Probability | 7% | 6% |
| 10 | Geopolitical Risk | 4% | 3% |
| 11 | Market Depth | 4% | 4% |

## 10-Gate Quality Filter (v9.4.0)
Gates G1-G10. Mandatory: G3 (volatility), G5 (spread), G8 (correlation). Must pass 8/10.

## Commodity-Currency Cross-Correlations (v9.6.2)
| Commodity | Currency | Direction | Strength | Reason |
|---|---|---|---|---|
| Gold | AUD | Positive (+0.4x) | Strong | Australia #2 gold producer |
| Gold | JPY, CHF | Positive (+0.5x) | Strong | Safe-haven correlation |
| Gold | GBP, NZD, CAD, NOK, SEK | Negative (-0.5x) | Moderate | Risk-off pressure |
| Oil | CAD, NOK | Positive (1.0x) | Strong | Oil exporter economies |
| Oil | JPY, INR, TRY | Negative (0.3x) | Moderate | Energy importer cost pressure |

## Key File Locations (app.py)
| Section | Approximate Lines |
|---|---|
| AI_FACTOR_CONFIG | ~200-210 |
| PAIR_CORRELATIONS | ~476-500 |
| Weight constants | ~1020-1070 |
| Cache config & TTLs | ~1275-1290 |
| get_ict_killzones() | ~3689 |
| calculate_probability_factor() | ~5415-6003 |
| calculate_market_depth() | ~4963 |
| analyze_intermarket() | ~8524-8840 |
| calculate_factor_scores() | ~9500+ |
| generate_signal() | ~11950+ |
| _regenerate_signals_background() | ~15875 |
| /signals endpoint | ~15940+ |
| get_all_ig_sentiment() | ~16846 |
| reset_weights() | ~16300+ |

## Critical Development Rules

### Variable Shadowing
Python treats ALL references as local if ANY assignment exists in scope. Never use `is_commodity = pair in (...)` — it shadows the global `is_commodity()` function. Use `is_commodity_pair` for local booleans.

### Scope Isolation
`candles/opens/highs/lows/closes` are LOCAL to `calculate_factor_scores()` — NOT returned. Extract from `_cached_candles` in `generate_signal()`.

### Weight Changes Checklist
Update ALL of these when changing weights:
1. `FACTOR_GROUP_WEIGHTS` dict
2. `COMMODITY_FACTOR_WEIGHTS` dict
3. 4x `REGIME_WEIGHTS` dicts (trending, ranging, volatile, quiet)
4. `reset_weights()` function
5. Frontend `commodityMap` + `groupLabels` in index.html
6. Methodology tables (forex + commodity)
7. Audit `scoring_methodology`

### Adding a New Factor Group
Requires updates in: weight dicts (5 places), regime dicts (4 places), reset_weights(), generate_signal() integration block, factor_grid, frontend commodityMap + groupLabels + cName mapping, methodology tables (2), audit scoring_methodology, version strings (~10 places).

### SL/TP Rules
- Pip sizes: ALL exotics use 0.001 except HUF (0.01, JPY-like)
- SL from entry zone EDGE: LONG SL from entry_min, SHORT SL from entry_max
- TP2 must be > TP1 * 1.2
- PIP_LIMITS EXOTIC/SCANDINAVIAN: sl_abs_min=30, sl_abs_max=600

### Error Handling
- `generate_signal()` has outer try/except returning None — unhandled exceptions kill signals silently
- Always wrap new factor calculations in try/except with neutral fallback (score=50, signal='NEUTRAL')
- Always initialize variables BEFORE conditional blocks
- Use `warning` level for signal failures, not `debug`

### Frontend
- Expects UPPERCASE color values: GREEN, YELLOW, RED
- Version references scattered across both files (~10+ places)

## Performance (v9.6.1)
- Signal cache: 300s TTL, stale-while-revalidate up to 1 hour
- AI cache: 3600s TTL (1 hour)
- IG sentiment: 5 parallel workers (was sequential)
- Background regeneration on stale cache > 5 min
- Frontend localStorage cache for instant render
- Pre-fetch: 4 parallel executors (rates, candles, shared data, positioning)
- Workers: candle=10, signal=10, rate=10, IG=5

## Version History
- **v9.6.2**: Fix commodity-currency cross-correlations (AUD-Gold, oil importers, GBP risk, silver price)
- **v9.6.1**: Dashboard load time optimization (5 performance improvements)
- **v9.6.0**: Add Probability factor (11th factor group, 8 sub-components P1-P8)
- **v9.5.1**: SL/TP edge fixes, TP2 safety check
- **v9.5.0**: Dynamic intermarket baselines, enriched AI analysis
- **v9.4.0**: 10-gate quality filter, parallel pre-fetch, stale-while-revalidate
- **v9.3.0**: Commodity support (5 pairs), IG sentiment batch
