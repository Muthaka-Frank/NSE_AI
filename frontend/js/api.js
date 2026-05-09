/**
 * NSE AI Platform — API Client
 * All communication with the FastAPI backend.
 */

const API_BASE = 'http://localhost:8000';

const api = {
  _headers() {
    const token = localStorage.getItem('nse_ai_token');
    return token
      ? { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }
      : { 'Content-Type': 'application/json' };
  },

  async get(path) {
    try {
      const res = await fetch(`${API_BASE}${path}`, { headers: this._headers() });
      if (res.status === 401) { localStorage.removeItem('nse_ai_token'); window.location.href = 'login.html'; return null; }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn(`[API] ${path} failed:`, err.message);
      return null;
    }
  },

  async getStocks()            { return this.get('/api/stocks'); },
  async getStock(ticker)       { return this.get(`/api/stocks/${ticker}`); },
  async getHistory(ticker, period = '3mo') { return this.get(`/api/stocks/${ticker}/history?period=${period}`); },
  async getPrediction(ticker)  { return this.get(`/api/stocks/${ticker}/prediction`); },
  async getNews(ticker = null) { return this.get(`/api/news${ticker ? `?ticker=${ticker}` : ''}`); },
  async getRecommendations()   { return this.get('/api/recommendations'); },
  async getAlerts()            { return this.get('/api/recommendations/alerts'); },
};

// ── Mock data (fallback when backend is offline) ───────────────────────────
const MOCK = {
  stocks: [
    { ticker:'SCOM', name:'Safaricom PLC',         sector:'Telecommunications', price:19.80, change:0.40,  change_pct:2.06,  volume:4200000 },
    { ticker:'EQTY', name:'Equity Group Holdings',  sector:'Banking',           price:52.25, change:-0.75, change_pct:-1.42, volume:1800000 },
    { ticker:'KCB',  name:'KCB Group PLC',          sector:'Banking',           price:43.10, change:0.60,  change_pct:1.41,  volume:2100000 },
    { ticker:'COOP', name:'Co-operative Bank',      sector:'Banking',           price:13.35, change:-0.15, change_pct:-1.11, volume:900000  },
    { ticker:'EABL', name:'East African Breweries',  sector:'Consumer Staples',  price:162.0, change:2.0,   change_pct:1.25,  volume:310000  },
    { ticker:'BAT',  name:'BAT Kenya',              sector:'Consumer Staples',  price:418.0, change:-7.0,  change_pct:-1.65, volume:85000   },
    { ticker:'KPLC', name:'Kenya Power & Lighting', sector:'Energy',            price:2.28,  change:0.03,  change_pct:1.33,  volume:5200000 },
    { ticker:'ABSA', name:'Absa Bank Kenya',        sector:'Banking',           price:15.60, change:0.10,  change_pct:0.65,  volume:670000  },
    { ticker:'NCBA', name:'NCBA Group PLC',         sector:'Banking',           price:44.50, change:0.50,  change_pct:1.14,  volume:440000  },
    { ticker:'BAMB', name:'Bamburi Cement',         sector:'Manufacturing',     price:40.25, change:-0.25, change_pct:-0.62, volume:210000  },
  ],

  recommendations: [
    {
      ticker:'SCOM', name:'Safaricom PLC', sector:'Telecommunications',
      price:19.80, change_pct:2.06, direction:'BUY', confidence:0.87,
      confidence_pct:'87.0%', signal_strength:'STRONG', price_target:21.38,
      risk_level:'LOW', news_sentiment:'POSITIVE',
      reasoning:[
        'RSI 28.4 — oversold territory (bullish reversal signal)',
        'MA20 (19.42) above MA50 (18.91) — bullish crossover',
        'News sentiment: POSITIVE — M-Pesa revenue growth reported',
      ]
    },
    {
      ticker:'KCB', name:'KCB Group PLC', sector:'Banking',
      price:43.10, change_pct:1.41, direction:'BUY', confidence:0.78,
      confidence_pct:'78.0%', signal_strength:'MODERATE', price_target:46.55,
      risk_level:'MEDIUM', news_sentiment:'NEUTRAL',
      reasoning:[
        'MACD above signal line — upward momentum building',
        'MA20 (42.80) above MA50 (41.20) — bullish crossover',
        'Volume spike 1.8x above 10-day average',
      ]
    },
    {
      ticker:'KPLC', name:'Kenya Power & Lighting', sector:'Energy',
      price:2.28, change_pct:1.33, direction:'BUY', confidence:0.74,
      confidence_pct:'74.0%', signal_strength:'MODERATE', price_target:2.46,
      risk_level:'MEDIUM', news_sentiment:'POSITIVE',
      reasoning:[
        'RSI 31.2 — approaching oversold territory',
        'Price below lower Bollinger Band — potential bounce',
        'Government tariff review announced positively',
      ]
    },
  ],

  news: [
    { title:'Safaricom reports record M-Pesa transaction volumes in Q3', source:'Business Daily Africa', url:'#', published:'Wed, 23 Apr 2025', related_tickers:['SCOM'], sentiment:{ label:'POSITIVE', score:0.84, score_pct:'84%' }},
    { title:'KCB Group expands into South Sudan with new digital banking platform', source:'Capital Business', url:'#', published:'Wed, 23 Apr 2025', related_tickers:['KCB'], sentiment:{ label:'POSITIVE', score:0.76, score_pct:'76%' }},
    { title:'Kenya shilling steadies against dollar as forex reserves improve', source:'The Standard', url:'#', published:'Tue, 22 Apr 2025', related_tickers:[], sentiment:{ label:'NEUTRAL', score:0.52, score_pct:'52%' }},
    { title:'BAT Kenya profits decline amid stricter tobacco regulations', source:'Business Daily Africa', url:'#', published:'Tue, 22 Apr 2025', related_tickers:['BAT'], sentiment:{ label:'NEGATIVE', score:0.81, score_pct:'81%' }},
    { title:'Equity Group posts 18% profit growth driven by regional expansion', source:'Capital Business', url:'#', published:'Mon, 21 Apr 2025', related_tickers:['EQTY'], sentiment:{ label:'POSITIVE', score:0.88, score_pct:'88%' }},
    { title:'NSE 20 Share Index gains 1.2% on strong banking sector performance', source:'KBC Business', url:'#', published:'Mon, 21 Apr 2025', related_tickers:['EQTY','KCB','COOP'], sentiment:{ label:'POSITIVE', score:0.79, score_pct:'79%' }},
  ],

  generateHistory(ticker, days = 90) {
    const bases = { SCOM:19.80, EQTY:52.00, KCB:42.50, COOP:13.20, EABL:160.0, BAT:418.0, KPLC:2.28, ABSA:15.50, NCBA:44.00, BAMB:40.25 };
    let price = bases[ticker] || 50.0;
    const history = [];
    const now = new Date();
    for (let i = days; i >= 0; i--) {
      const d = new Date(now); d.setDate(d.getDate() - i);
      if (d.getDay() === 0 || d.getDay() === 6) continue;
      const change = (Math.random() - 0.48) * 0.03;
      price = Math.max(0.5, price * (1 + change));
      history.push({
        date:  d.toISOString().split('T')[0],
        open:  +price.toFixed(2),
        high:  +(price * (1 + Math.random() * 0.012)).toFixed(2),
        low:   +(price * (1 - Math.random() * 0.012)).toFixed(2),
        close: +(price * (1 + (Math.random() - 0.5) * 0.005)).toFixed(2),
        volume: Math.floor(100000 + Math.random() * 4900000),
      });
    }
    return history;
  }
};
