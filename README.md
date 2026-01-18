# MEGA FOREX v8.2 PRO - PWA Mobile App 📱

A professional 45-pair Forex trading dashboard that works as a Progressive Web App (PWA) on your Android phone.

## ✨ Features

- **45 Forex Pairs** with real-time data
- **9-Factor Weighted Scoring Algorithm**
- **Live Trade Recommendations** (BUY/SELL signals)
- **Trade Journal** with performance tracking
- **Backtesting Module**
- **Economic Calendar**
- **News Feed**
- **IG Markets Positioning Data**
- **Auto-refresh every 2 minutes**
- **Works offline** (cached data)
- **Installable on Android** like a native app

---

## 🚀 Quick Deploy to Render.com (FREE)

### Step 1: Push to GitHub

1. Create a new GitHub repository
2. Upload all files from this folder
3. Make sure `.env` is in `.gitignore` (don't commit your API keys!)

### Step 2: Deploy to Render

1. Go to [render.com](https://render.com) and sign up (free)
2. Click **New** → **Web Service**
3. Connect your GitHub repository
4. Configure:
   - **Name**: mega-forex-pwa
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2`
5. Add Environment Variables (from your `.env` file):
   - `POLYGON_API_KEY`
   - `FINNHUB_API_KEY`
   - `FRED_API_KEY`
   - `ALPHA_VANTAGE_KEY`
   - `IG_API_KEY`
   - `IG_USERNAME`
   - `IG_PASSWORD`
   - `IG_ACC_TYPE` = `DEMO`
6. Click **Create Web Service**

### Step 3: Install on Your Phone

1. Open Chrome on your Android phone
2. Go to your Render URL (e.g., `https://mega-forex-pwa.onrender.com`)
3. Tap the **⋮** menu → **Add to Home screen**
4. Done! You now have MEGA FOREX as an app on your phone

---

## 🔧 Alternative Deployment Options

### Railway.app (FREE)

1. Go to [railway.app](https://railway.app)
2. Click **Deploy from GitHub**
3. Select your repository
4. Add environment variables in Settings
5. Railway will automatically detect the Procfile

### PythonAnywhere (FREE)

1. Upload files to PythonAnywhere
2. Set up a web app with Flask
3. Configure WSGI to point to `app:app`
4. Add environment variables in `.env`

### Local Network (Home WiFi)

Run on your PC and access from phone on same WiFi:

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env with your API keys
cp .env.example .env
nano .env  # Edit and add your keys

# Run the server
python app.py
```

Find your PC's local IP (e.g., `192.168.1.100`) and access from phone:
`http://192.168.1.100:5000`

---

## 📁 Project Structure

```
mega_forex_pwa/
├── app.py              # Main Flask backend + API
├── requirements.txt    # Python dependencies
├── Procfile           # For Render/Railway deployment
├── render.yaml        # Render configuration
├── manifest.json      # PWA manifest
├── sw.js              # Service worker for offline
├── .env.example       # Example environment variables
├── templates/
│   └── index.html     # PWA dashboard
└── static/
    ├── icon-192.png   # App icon (small)
    └── icon-512.png   # App icon (large)
```

---

## 🔑 API Keys Needed

| Service | Purpose | Get Key |
|---------|---------|---------|
| Polygon.io | Real-time forex rates | [polygon.io](https://polygon.io) |
| Finnhub | News & Calendar | [finnhub.io](https://finnhub.io) |
| FRED | Economic data | [fred.stlouisfed.org](https://fred.stlouisfed.org) |
| Alpha Vantage | Backup rates | [alphavantage.co](https://alphavantage.co) |
| IG Markets | Positioning data | [ig.com](https://www.ig.com) |

All services have free tiers that work well for personal use.

---

## 📱 Mobile Screenshots

The app includes:
- **Overview**: All 45 pairs with composite scores
- **Top Signals**: Best trade opportunities ranked
- **Live Rates**: Real-time bid/ask prices
- **Journal**: Track your trades
- **Performance**: Win rate, profit factor, etc.
- **Backtest**: Test strategies on historical data
- **Positioning**: See what retail traders are doing
- **News**: Forex news feed
- **Calendar**: Economic events
- **Weights**: Customize factor weights
- **Audit**: System health check

---

## ⚠️ Important Notes

1. **Free tier limitations**: Render's free tier sleeps after 15 minutes of inactivity. First request after sleep takes ~30 seconds.

2. **Data freshness**: Markets must be open for real-time data. During weekends/holidays, you'll see cached or static rates.

3. **Not financial advice**: This is an educational tool. Always do your own research before trading.

---

## 🆘 Troubleshooting

**App won't install on phone?**
- Make sure you're using Chrome
- Site must be served over HTTPS (automatic on Render)
- Wait for full page load before installing

**Signals showing "undefined"?**
- Check API keys are set correctly
- Run the Audit tab to check API status

**Slow first load?**
- Free tier servers sleep when idle
- Upgrade to paid tier for always-on

---

## 📄 License

MIT License - Use freely for personal trading.

---

Built with ❤️ for forex traders who want mobile access to professional analysis.
