/**
 * NSE AI Platform — Main App Logic
 * Dashboard orchestration: ticker, recommendations, chart, news, stocks table.
 */

// ── State ─────────────────────────────────────────────────────────────────
let allStocks   = [];
let currentTicker  = 'SCOM';
let currentPeriod  = '1mo';
let watchlistTickers = new Set();

// ── Boot ──────────────────────────────────────────────────────────────────
function bootDashboard() {
  startClock();

  // Load cached stock prices if available, else fall back to MOCK
  const cachedStocks = localStorage.getItem('nse_stocks_cache');
  const initialStocks = cachedStocks ? JSON.parse(cachedStocks) : MOCK.stocks;
  allStocks = initialStocks;

  // ── Step 1: Render cached/mock data instantly so user sees content immediately ────
  try { renderTicker(initialStocks); } catch(e) { console.warn('ticker:', e); }
  try { renderTable(initialStocks); } catch(e) { console.warn('table:', e); }
  try { _renderOverviewFromStocks(initialStocks); } catch(e) { console.warn('overview:', e); }
  try {
    populateChartSelect();
    populateWatchlistAndBuySelects();
    initChart();
    updateChart(currentTicker, currentPeriod);
  } catch(e) { console.warn('chart:', e); }
  try { loadSignal(currentTicker); } catch(e) { console.warn('signal:', e); }
  try {
    bindChartControls();
    bindTableSearch();
    bindWatchlistAndPortfolioEvents();
  } catch(e) { console.warn('controls:', e); }

  // ── Step 1b: Render cached watchlist and portfolio instantly, and fetch fresh ────
  try {
    const cachedWatchlist = localStorage.getItem('nse_watchlist_cache');
    if (cachedWatchlist) {
      renderWatchlistFromData(JSON.parse(cachedWatchlist));
    }
  } catch(e) { console.warn('cached watchlist load:', e); }
  try {
    const cachedPortfolio = localStorage.getItem('nse_portfolio_cache');
    if (cachedPortfolio) {
      renderPortfolioFromData(JSON.parse(cachedPortfolio));
    }
  } catch(e) { console.warn('cached portfolio load:', e); }
  loadWatchlist().catch(e => console.warn('watchlist fetch:', e));
  loadPortfolio().catch(e => console.warn('portfolio fetch:', e));

  // ── Step 1c: Load IPO Alerts & Banner ────────────────────────────────
  loadActiveIpoAlert().catch(e => console.warn('ipo alert fetch:', e));

  // ── Step 2: Load news immediately (fast — not Yahoo Finance) ─────────
  // Try loading cached news first
  try {
    const cachedNews = localStorage.getItem('nse_news_cache');
    if (cachedNews) {
      renderNewsFromData(JSON.parse(cachedNews));
    }
  } catch(e) {}
  loadNews().catch(e => console.warn('news:', e));

  // ── Step 3: Load recommendations independently ───────────────────────
  // Try loading cached recommendations first
  try {
    const cachedRecs = localStorage.getItem('nse_recs_cache');
    if (cachedRecs) {
      renderRecommendationsFromData(JSON.parse(cachedRecs));
    }
  } catch(e) {}
  loadRecommendations().catch(e => console.warn('recs:', e));

  // ── Step 4: Fetch real stock data, replace mock when ready ───────────
  api.getStocks().then(data => {
    if (!data?.stocks?.length) return;
    allStocks = data.stocks;
    localStorage.setItem('nse_stocks_cache', JSON.stringify(data.stocks));
    try { renderTicker(data.stocks); } catch(e) {}
    try { renderTable(data.stocks); } catch(e) {}
    try { _renderOverviewFromStocks(data.stocks); } catch(e) {}
    try {
      populateChartSelect();
      populateWatchlistAndBuySelects();
      updateChart(currentTicker, currentPeriod).then(() => loadSignal(currentTicker));
    } catch(e) {}
    try {
      loadWatchlist();
      loadPortfolio();
      bindWatchlistAndPortfolioEvents();
    } catch(e) { console.warn('watchlist/portfolio init error:', e); }
    try { startLiveUpdates(); } catch(e) {}
  }).catch(e => console.warn('stocks fetch:', e));
  // ── Step 5: Refresh news every 2 min ─────────────────────────────────
  setInterval(loadNews, 120_000);
  setInterval(loadActiveIpoAlert, 120_000);

  // ── Step 6: Fallback Polling Loop (every 30s) when SSE is not Live ───
  setInterval(async () => {
    const badge = document.getElementById('live-update-badge');
    const isLive = badge && (badge.classList.contains('live') || badge.textContent.includes('LIVE'));
    if (!isLive) {
      console.log('[Dashboard] SSE stream offline. Polling backend for fresh stock data...');
      try {
        const data = await api.getStocks();
        if (data?.stocks?.length) {
          allStocks = data.stocks;
          updatePricesInPlace(data.stocks);
        }
      } catch (e) {
        console.warn('Polling stocks failed:', e);
      }
    }
  }, 30_000);
}

// ── Clock ─────────────────────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById('nav-time');
  const tick = () => {
    const now = new Date();
    el.textContent = now.toLocaleTimeString('en-KE', { timeZone:'Africa/Nairobi', hour12:false }) + ' EAT';
    updateMarketStatus();
  };
  tick();
  setInterval(tick, 1000);

  const dateEl = document.getElementById('market-date');
  if (dateEl) {
    dateEl.textContent = 'NSE · ' + new Date().toLocaleDateString('en-KE', { weekday:'long', year:'numeric', month:'long', day:'numeric', timeZone:'Africa/Nairobi' });
  }
}

function updateMarketStatus() {
  const statusDot = document.getElementById('market-status-dot');
  const statusText = document.getElementById('market-status-text');
  if (!statusDot || !statusText) return;

  const now = new Date();
  // Get current time in Nairobi (EAT)
  const nairobiTimeStr = now.toLocaleString('en-US', { timeZone: 'Africa/Nairobi' });
  const eatNow = new Date(nairobiTimeStr);

  const day = eatNow.getDay(); // 0 = Sunday, 6 = Saturday
  const hour = eatNow.getHours();
  const minute = eatNow.getMinutes();
  const totalMinutes = hour * 60 + minute;

  const isWeekend = (day === 0 || day === 6);
  
  let status = "CLOSED";
  let color = "#ff4d6d"; // Red for closed
  
  if (!isWeekend) {
    if (totalMinutes >= 540 && totalMinutes < 570) { // 09:00 AM to 09:30 AM EAT
      status = "PRE-OPEN";
      color = "#ffd700"; // Yellow for pre-open
    } else if (totalMinutes >= 570 && totalMinutes < 900) { // 09:30 AM to 03:00 PM EAT
      status = "OPEN";
      color = "#00e5a0"; // Green for open
    }
  }

  statusDot.style.background = color;
  statusDot.style.boxShadow = `0 0 8px ${color}80`;
  statusText.textContent = `Market ${status}`;
  statusText.style.color = color;
}

// ── Ticker Tape ───────────────────────────────────────────────────────────
async function loadTicker() {
  const data = await api.getStocks();
  const stocks = data?.stocks || MOCK.stocks;
  allStocks = stocks;
  renderTicker(stocks);
}

function renderTicker(stocks) {
  const tape = document.getElementById('ticker-tape');
  if (!tape) return;
  
  const doubled = [...stocks, ...stocks]; // Seamless loop
  
  // Update in-place if count matches to prevent marquee animation from resetting
  const existingItems = tape.querySelectorAll('.ticker-item');
  if (existingItems.length === doubled.length) {
    doubled.forEach((s, idx) => {
      const item = existingItems[idx];
      if (!item) return;
      
      const priceEl = item.querySelector('.ticker-price');
      const changeEl = item.querySelector('.ticker-change');
      
      if (priceEl) priceEl.textContent = `KES ${s.price.toFixed(2)}`;
      if (changeEl) {
        changeEl.className = `ticker-change ${s.change_pct >= 0 ? 'up' : 'down'}`;
        changeEl.innerHTML = `${s.change_pct >= 0 ? '▲' : '▼'} ${Math.abs(s.change_pct).toFixed(2)}%`;
      }
    });
    return;
  }
  
  tape.innerHTML = doubled.map(s => `
    <div class="ticker-item" onclick="jumpToStock('${s.ticker}')">
      <span class="ticker-symbol">${s.ticker}</span>
      <span class="ticker-price">KES ${s.price.toFixed(2)}</span>
      <span class="ticker-change ${s.change_pct >= 0 ? 'up' : 'down'}">
        ${s.change_pct >= 0 ? '▲' : '▼'} ${Math.abs(s.change_pct).toFixed(2)}%
      </span>
    </div>
  `).join('');
}

// ── Chart Dropdown ─────────────────────────────────────────────────────────
function populateChartSelect() {
  const select = document.getElementById('chart-ticker-select');
  if (!select || !allStocks.length) return;
  select.innerHTML = allStocks
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
    .map(s => `<option value="${s.ticker}">${s.name} (${s.ticker})</option>`)
    .join('');
  // Default to SCOM if available
  const scom = [...select.options].find(o => o.value === 'SCOM');
  if (scom) { select.value = 'SCOM'; currentTicker = 'SCOM'; }
  else if (select.options.length) { currentTicker = select.options[0].value; }
}

// ── Market Overview ───────────────────────────────────────────────────────
async function loadOverview() {
  const data   = await api.getStocks();
  const stocks = data?.stocks || MOCK.stocks;
  _renderOverviewFromStocks(stocks);
  loadMacroBenchmarks();
}

async function loadMacroBenchmarks() {
  const data = await api.getMacroBenchmarks();
  const b = data || MOCK.macroBenchmarks;
  if (!b) return;
  const t91 = document.getElementById('macro-tbill-91d');
  const n91 = document.getElementById('macro-net-91d');
  const t182 = document.getElementById('macro-tbill-182d');
  const t364 = document.getElementById('macro-tbill-364d');
  const cbr = document.getElementById('macro-cbr');
  const inf = document.getElementById('macro-inflation');
  const rrf = document.getElementById('macro-real-rf');

  if (t91) t91.textContent = b.tbill_91d.toFixed(2) + '%';
  if (n91) n91.textContent = (b.net_tbill_91d || (b.tbill_91d * 0.85)).toFixed(2) + '%';
  if (t182) t182.textContent = b.tbill_182d.toFixed(2) + '%';
  if (t364) t364.textContent = b.tbill_364d.toFixed(2) + '%';
  if (cbr) cbr.textContent = b.cbr_rate.toFixed(2) + '%';
  if (inf) inf.textContent = b.inflation_rate.toFixed(2) + '%';
  if (rrf) rrf.textContent = (b.real_risk_free_rate >= 0 ? '+' : '') + b.real_risk_free_rate.toFixed(2) + '%';
}

function _renderOverviewFromStocks(stocks) {
  const grid = document.getElementById('overview-grid');
  if (!grid) return;

  const gainers = stocks.filter(s => s.change_pct > 0).length;
  const losers  = stocks.filter(s => s.change_pct < 0).length;
  const avgChg  = stocks.reduce((a,s) => a + s.change_pct, 0) / stocks.length;
  
  const sortedGainers = [...stocks].filter(s => s.change_pct > 0).sort((a,b) => b.change_pct - a.change_pct);
  const sortedLosers  = [...stocks].filter(s => s.change_pct < 0).sort((a,b) => a.change_pct - b.change_pct);
  
  const topGainer = sortedGainers.length > 0 ? sortedGainers[0] : null;
  const topLoser  = sortedLosers.length > 0 ? sortedLosers[0] : null;

  grid.innerHTML = `
    <div class="overview-card">
      <div class="overview-label">Market Sentiment</div>
      <div class="overview-value ${avgChg >= 0 ? 'up' : 'down'}">${avgChg >= 0 ? 'BULLISH' : 'BEARISH'}</div>
      <div class="overview-change ${avgChg >= 0 ? 'up' : 'down'}">Avg ${avgChg >= 0 ? '+' : ''}${avgChg.toFixed(2)}% today</div>
    </div>
    <div class="overview-card" onclick="openGainersLosersModal()" style="cursor:pointer">
      <div class="overview-label">Gainers / Losers</div>
      <div class="overview-value up">${gainers}</div>
      <div class="overview-change down">↓ ${losers} stocks falling</div>
    </div>
    <div class="overview-card" ${topGainer ? `onclick="jumpToStock('${topGainer.ticker}')" style="cursor:pointer"` : ''}>
      <div class="overview-label">Top Gainer</div>
      <div class="overview-value up">${topGainer ? topGainer.ticker : 'None'}</div>
      <div class="overview-change up">${topGainer ? `▲ +${topGainer.change_pct.toFixed(2)}% · KES ${topGainer.price.toFixed(2)}` : '0.00% · KES —'}</div>
    </div>
    <div class="overview-card" ${topLoser ? `onclick="jumpToStock('${topLoser.ticker}')" style="cursor:pointer"` : ''}>
      <div class="overview-label">Top Loser</div>
      <div class="overview-value down">${topLoser ? topLoser.ticker : 'None'}</div>
      <div class="overview-change down">${topLoser ? `▼ ${topLoser.change_pct.toFixed(2)}% · KES ${topLoser.price.toFixed(2)}` : '0.00% · KES —'}</div>
    </div>
  `;
}

function openGainersLosersModal() {
  try {
    const modal = document.getElementById('gainers-losers-modal');
    if (!modal) return;

    const gainers = allStocks.filter(s => s.change_pct > 0).sort((a, b) => b.change_pct - a.change_pct);
    const losers  = allStocks.filter(s => s.change_pct < 0).sort((a, b) => a.change_pct - b.change_pct);

    document.getElementById('modal-gainers-count').textContent = gainers.length;
    document.getElementById('modal-losers-count').textContent = losers.length;

    const renderItem = (s) => {
      const isUp = s.change_pct >= 0;
      return `
        <div onclick="jumpToStock('${s.ticker}'); document.getElementById('gainers-losers-modal').style.display='none';" 
             style="display:flex; justify-content:space-between; align-items:center; padding:0.6rem 0.8rem; background:rgba(255,255,255,0.02); border:1px solid var(--border-color); border-radius:8px; cursor:pointer; transition:all 0.2s;"
             onmouseover="this.style.background='rgba(255,255,255,0.06)'; this.style.borderColor='var(--border-light)';"
             onmouseout="this.style.background='rgba(255,255,255,0.02)'; this.style.borderColor='var(--border-color)';">
          <div style="display:flex; flex-direction:column; min-width: 0;">
            <span style="font-weight:700; color:#fff; font-size:0.95rem;">${s.ticker}</span>
            <span style="font-size:0.75rem; color:var(--text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${s.name}">${s.name}</span>
          </div>
          <div style="text-align:right; flex-shrink: 0;">
            <div style="font-size:0.9rem; font-family:var(--font-mono); color:#fff; font-weight:600;">KES ${(s.price || 0).toFixed(2)}</div>
            <div style="font-size:0.8rem; font-weight:600; color:${isUp ? 'var(--accent)' : '#ff4d6d'};">
              ${isUp ? '▲' : '▼'} ${Math.abs(s.change_pct || 0).toFixed(2)}%
            </div>
          </div>
        </div>
      `;
    };

    document.getElementById('modal-gainers-list').innerHTML = gainers.length > 0
      ? gainers.map(renderItem).join('')
      : '<div style="text-align:center; color:var(--text-muted); padding:1rem; font-size:0.85rem;">No gainers today</div>';

    document.getElementById('modal-losers-list').innerHTML = losers.length > 0
      ? losers.map(renderItem).join('')
      : '<div style="text-align:center; color:var(--text-muted); padding:1rem; font-size:0.85rem;">No losers today</div>';

    modal.style.display = 'flex';
  } catch (err) {
    console.error("Error opening movers modal:", err);
    alert("Error opening movers modal: " + err.message);
  }
}

// ── AI Recommendations ────────────────────────────────────────────────────
async function loadRecommendations() {
  const data = await api.getRecommendations();
  const recs = data?.recommendations || MOCK.recommendations;
  if (data?.recommendations) {
    localStorage.setItem('nse_recs_cache', JSON.stringify(recs));
  }
  renderRecommendationsFromData(recs);
}

function renderRecommendationsFromData(recs) {
  const grid = document.getElementById('recs-grid');
  const noSig = document.getElementById('no-signal-notice');
  if (!grid || !noSig) return;

  if (recs.length === 0) {
    grid.innerHTML = '';
    noSig.style.display = 'block';
    return;
  }
  noSig.style.display = 'none';

  // Show alert banner for STRONG signals
  const strong = recs.find(r => r.signal_strength === 'STRONG');
  if (strong) {
    const banner = document.getElementById('alerts-banner');
    if (banner) {
      document.getElementById('alerts-text').textContent =
        `${strong.ticker} — ${strong.name} shows a ${strong.signal_strength} BUY signal at ${strong.confidence_pct} confidence. Target: KES ${strong.price_target}`;
      banner.style.display = 'flex';
    }
  }

  grid.innerHTML = recs.slice(0, 6).map(r => `
    <div class="rec-card" onclick="jumpToStock('${r.ticker}')">
      <div class="rec-header">
        <div>
          <div class="rec-ticker">${r.ticker}</div>
          <div class="rec-name">${r.name}</div>
        </div>
        <div class="rec-direction ${r.direction}">${r.direction}</div>
      </div>
      <div class="rec-price">KES ${r.price.toFixed(2)} <span>${r.change_pct >= 0 ? '+' : ''}${r.change_pct.toFixed(2)}%</span></div>
      <div class="confidence-bar-wrap">
        <div class="confidence-bar-label">
          <span>AI Confidence</span><span>${r.confidence_pct}</span>
        </div>
        <div class="confidence-bar-track">
          <div class="confidence-bar-fill ${r.signal_strength}" style="width:${r.confidence * 100}%"></div>
        </div>
      </div>
      <ul class="rec-reasoning">
        ${r.reasoning.slice(0,2).map(l => `<li>${l}</li>`).join('')}
      </ul>
      <div class="rec-target" style="display:flex; flex-direction:column; align-items:flex-start; gap:4px; border-top:1px dashed var(--border-color); padding-top:8px;">
        <div style="width:100%; display:flex; justify-content:space-between; align-items:baseline;">
          <span class="rec-target-label">Price Target</span>
          <span class="rec-target-value">KES ${r.price_target}</span>
        </div>
        ${r.breakeven_price ? `<div style="width:100%; display:flex; justify-content:space-between; font-size:11px; color:var(--text-muted);"><span>Statutory Breakeven:</span><b style="color:var(--accent);">KES ${r.breakeven_price.toFixed(2)} (+4.3%)</b></div>` : ''}
        ${r.timeframe ? `<span style="font-size:11px; color:var(--text-muted);">Est. Timeframe: <b>${r.timeframe}</b></span>` : ''}
      </div>
    </div>
  `).join('');
}

// ── AI Signal Panel ───────────────────────────────────────────────────────
async function loadSignal(ticker) {
  const card = document.getElementById('signal-card');
  if (!card) return;

  // Try loading from cache first
  const cachedSignal = localStorage.getItem(`nse_signal_cache_${ticker}`);
  if (cachedSignal) {
    try {
      card.innerHTML = renderSignalCard(JSON.parse(cachedSignal));
    } catch(e) {}
  } else {
    card.innerHTML = '<div class="signal-loading">Analysing ' + ticker + '…</div>';
  }

  const data = await api.getPrediction(ticker);

  if (!data) {
    if (!cachedSignal) {
      card.innerHTML = renderSignalCard({
        direction: 'NO_SIGNAL', confidence: 0, confidence_pct: '—',
        signal_strength: 'NONE', reasoning: ['Backend offline — using demo mode'],
        price_target: null, risk_level: 'UNKNOWN', current_price: 0,
      });
    }
    return;
  }
  localStorage.setItem(`nse_signal_cache_${ticker}`, JSON.stringify(data));
  card.innerHTML = renderSignalCard(data);
}

function renderSignalCard(d) {
  const isSignal = d.direction !== 'NO_SIGNAL';
  const isStarred = watchlistTickers.has(d.ticker);
  return `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
      <div class="signal-direction ${d.direction}">${
        d.direction === 'NO_SIGNAL' ? '⏸ No Signal' :
        d.direction === 'BUY'  ? '↑ BUY'  : '↓ SELL'
      }</div>
      <button class="star-btn" data-ticker="${d.ticker}" onclick="toggleWatchlist(event, '${d.ticker}')" style="background:rgba(255,255,255,0.05); border:1px solid var(--border-color); border-radius:8px; width:36px; height:36px; display:flex; align-items:center; justify-content:center; font-size:1.25rem; cursor:pointer; color:${isStarred ? '#ffd700' : 'var(--text-muted)'}; transition:all 0.2s;">
        ${isStarred ? '★' : '☆'}
      </button>
    </div>
    <div class="signal-strength-badge ${d.signal_strength}">${d.signal_strength}</div>
    <div class="signal-conf">Confidence: <b>${d.confidence_pct || '—'}</b></div>
    ${d.liquidity_rating ? `
      <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.03); padding:6px 10px; border-radius:6px; margin:8px 0; font-size:12px; border:1px solid var(--border-color);">
        <span><b style="color:${d.liquidity_rating === 'HIGH' ? 'var(--accent)' : d.liquidity_rating === 'MODERATE' ? '#ffd700' : 'var(--red)'};">${d.liquidity_rating === 'HIGH' ? '🟢 High Liquidity' : d.liquidity_rating === 'MODERATE' ? '🟡 Moderate' : '🔴 Illiquid Trap'}</b></span>
        <span style="color:var(--text-secondary);">Spread: <b style="font-family:var(--font-mono); color:var(--text-primary);">${d.spread_pct !== null && d.spread_pct !== undefined ? d.spread_pct.toFixed(1) + '%' : '—'}</b></span>
        <span style="color:var(--text-secondary);">Turnover: <b style="font-family:var(--font-mono); color:var(--text-primary);">${d.turnover_velocity_pct !== null && d.turnover_velocity_pct !== undefined ? d.turnover_velocity_pct.toFixed(2) + '%/mo' : '—'}</b></span>
      </div>
    ` : ''}
    ${d.tbill_91d_pct !== undefined && d.tbill_91d_pct !== null ? `
      <div style="background:rgba(124, 77, 255, 0.05); padding:8px 10px; border-radius:6px; margin:8px 0; font-size:12px; border:1px solid rgba(124, 77, 255, 0.25);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
          <span style="font-weight:600; color:var(--accent);">🏛️ CBK Benchmark (91d T-Bill: ${d.tbill_91d_pct.toFixed(1)}%)</span>
          <span style="font-size:11px; padding:1px 6px; border-radius:4px; background:rgba(255,255,255,0.06);">${d.macro_verdict || 'Macro Gauge'}</span>
        </div>
        <div style="display:flex; justify-content:space-between; color:var(--text-secondary); font-size:11.5px;">
          <span>Div Yield: <b style="color:${(d.dividend_yield_pct || 0) >= 6 ? 'var(--accent)' : 'var(--text-primary)'}; font-family:var(--font-mono);">${d.dividend_yield_pct !== null ? d.dividend_yield_pct.toFixed(1) + '%' : '0.0%'}</b></span>
          <span>Net Spread: <b style="font-family:var(--font-mono); color:${(d.net_yield_spread_pct || 0) >= 0 ? '#00e676' : '#ffb74d'};">${d.net_yield_spread_pct !== null ? (d.net_yield_spread_pct >= 0 ? '+' : '') + d.net_yield_spread_pct.toFixed(1) + '%' : '—'}</b></span>
          <span>Growth Hurdle: <b style="font-family:var(--font-mono); color:var(--text-primary);">+${d.required_growth_hurdle_pct !== null ? d.required_growth_hurdle_pct.toFixed(1) + '%/yr' : '15.7%/yr'}</b></span>
        </div>
      </div>
    ` : ''}
    <ul class="signal-reasons">
      ${(d.reasoning || []).map(r => `<li>${r}</li>`).join('')}
    </ul>
    ${isSignal && d.price_target ? `
      <div class="signal-target" style="display:flex; flex-direction:column; align-items:flex-start; gap:4px;">
        <div style="width:100%; display:flex; justify-content:space-between; align-items:baseline;">
          <div class="signal-target-label">Price Target</div>
          <div class="signal-target-val">KES ${d.price_target}</div>
        </div>
        ${d.breakeven_price ? `<div style="width:100%; display:flex; justify-content:space-between; font-size:12px; color:var(--text-muted);"><span>Statutory Breakeven:</span><b style="color:var(--accent);">KES ${d.breakeven_price.toFixed(2)} (+4.3%)</b></div>` : ''}
        ${d.timeframe ? `<div class="signal-timeframe" style="font-size:12px; color:var(--text-muted); width:100%; text-align:right;">Expected within: <b>${d.timeframe}</b></div>` : ''}
      </div>` : ''}
    <div class="signal-disclaimer">⚠️ Informational only. Not financial advice.</div>
  `;
}

// ── Chart Controls ────────────────────────────────────────────────────────
function bindChartControls() {
  const select = document.getElementById('chart-ticker-select');
  const btns   = document.querySelectorAll('.period-btn');

  select.addEventListener('change', async () => {
    currentTicker = select.value;
    await updateChart(currentTicker, currentPeriod);
    await loadSignal(currentTicker);
  });

  btns.forEach(btn => {
    btn.addEventListener('click', async () => {
      btns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentPeriod = btn.dataset.period;
      await updateChart(currentTicker, currentPeriod);
    });
  });
}

// ── News Feed ─────────────────────────────────────────────────────────────
async function loadNews() {
  const data = await api.getNews();
  const articles = data?.articles || MOCK.news;
  if (data?.articles) {
    localStorage.setItem('nse_news_cache', JSON.stringify(articles));
  }
  renderNewsFromData(articles);
}

function renderNewsFromData(articles) {
  const grid = document.getElementById('news-grid');
  if (!grid) return;

  grid.innerHTML = articles.slice(0, 6).map(a => {
    const sent = a.sentiment || { label:'NEUTRAL', score_pct:'—' };
    return `
      <div class="news-card">
        <div class="news-source-row">
          <span class="news-source">${a.source}</span>
          <span class="sentiment-badge ${sent.label}">${sent.label}</span>
        </div>
        <a href="${a.url}" target="_blank" rel="noopener" class="news-title">${a.title}</a>
        <div class="news-meta">
          <span>${formatDate(a.published)}</span>
          <div class="news-tickers">
            ${(a.related_tickers || []).map(t => `<span class="news-ticker-chip">${t}</span>`).join('')}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

// ── Stocks Table ──────────────────────────────────────────────────────────
async function loadStocksTable() {
  const data   = await api.getStocks();
  const stocks = data?.stocks || MOCK.stocks;
  allStocks = stocks;
  renderTable(stocks);
}

function renderTable(stocks) {
  const tbody = document.getElementById('stocks-tbody');
  if (!tbody) return;  // Not on a page with a stocks table
  tbody.innerHTML = stocks.map(s => {
    const up  = s.change_pct >= 0;
    const src = ['kwayisi_scrape', 'mystocks_scrape', 'investing_com'].includes(s.data_source) ? s.data_source : 'estimated';
    const srcBadge = _srcBadge(src, s.data_as_of);
    const isStarred = watchlistTickers.has(s.ticker);
    return `
      <tr onclick="jumpToStock('${s.ticker}')" data-ticker="${s.ticker}">
        <td class="table-ticker" style="display:flex; align-items:center; gap:0.5rem;">
          <span class="star-btn" data-ticker="${s.ticker}" onclick="toggleWatchlist(event, '${s.ticker}')" style="cursor:pointer; font-size:1.15rem; color:${isStarred ? '#ffd700' : 'var(--text-muted)'}; transition:all 0.2s;">
            ${isStarred ? '★' : '☆'}
          </span>
          ${s.ticker}
        </td>
        <td>${s.name}</td>
        <td>${s.sector}</td>
        <td class="table-price" id="price-${s.ticker}" data-value="${s.price}">
          KES ${s.price.toFixed(2)}
          <span id="src-${s.ticker}">${srcBadge}</span>
        </td>
        <td class="${up ? 'change-up' : 'change-down'}" id="change-${s.ticker}">
          ${up ? '▲' : '▼'} ${Math.abs(s.change_pct).toFixed(2)}%
        </td>
        <td class="table-volume" id="vol-${s.ticker}">${formatVolume(s.volume)}</td>
        <td style="font-family:var(--font-mono); font-size:0.85rem; color:${(s.dividend_yield || 0) >= 6.0 ? '#00e676' : (s.dividend_yield || 0) > 0 ? '#fff' : 'var(--text-muted)'}; font-weight:${(s.dividend_yield || 0) >= 6.0 ? '600' : 'normal'};">
          ${s.dividend_yield !== undefined && s.dividend_yield !== null ? s.dividend_yield.toFixed(1) + '%' : '0.0%'}
        </td>
        <td><span class="signal-pill NO_SIGNAL" id="sig-${s.ticker}">…</span></td>
      </tr>
    `;
  }).join('');

  // Fetch AI signals for every visible stock (non-blocking)
  stocks.forEach(s => fetchSignalBadge(s.ticker));
}

function _srcBadge(source, asOf) {
  if (source === 'kwayisi_scrape') {
    const tip = asOf ? `Kwayisi Live Scrape · as of ${asOf}` : 'Kwayisi Live Scrape';
    return `<span class="data-src-badge live" style="background:var(--success); color:#fff;" title="${tip}">LIVE</span>`;
  }
  if (source === 'mystocks_scrape') {
    const tip = asOf ? `myStocks Live Scrape · as of ${asOf}` : 'myStocks Live Scrape';
    return `<span class="data-src-badge live" style="background:var(--success); color:#fff;" title="${tip}">LIVE</span>`;
  }
  if (source === 'investing_com') {
    const tip = asOf ? `Investing.com · as of ${asOf}` : 'Investing.com';
    return `<span class="data-src-badge live" style="background:var(--success); color:#fff;" title="${tip}">LIVE</span>`;
  }
  return `<span class="data-src-badge est" title="Estimated · no live feed available">EST</span>`;
}


async function fetchSignalBadge(ticker) {
  const el = document.getElementById(`sig-${ticker}`);
  if (!el) return;
  const data = await api.getPrediction(ticker);
  if (!data) { el.textContent = '—'; return; }
  el.className = `signal-pill ${data.direction}`;
  if (data.direction === 'NO_SIGNAL') {
    el.textContent = '—';
  } else {
    el.textContent = `${data.direction} ${data.confidence_pct}`;
  }
}

function bindTableSearch() {
  const input = document.getElementById('stock-search');
  if (!input) return;
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    const filtered = allStocks.filter(s =>
      s.ticker.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)
    );
    renderTable(filtered);
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────
function jumpToStock(ticker) {
  const select = document.getElementById('chart-ticker-select');
  if (select && [...select.options].some(o => o.value === ticker)) {
    select.value = ticker;
    currentTicker = ticker;
    updateChart(ticker, currentPeriod);
    loadSignal(ticker);
    document.querySelector('.two-col')?.scrollIntoView({ behavior:'smooth' });
  }
}

function formatVolume(v) {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M';
  if (v >= 1_000)     return (v / 1_000).toFixed(0) + 'K';
  return v.toString();
}

function formatDate(dateStr) {
  try {
    const d = new Date(dateStr);
    if (isNaN(d)) return dateStr;
    return d.toLocaleDateString('en-KE', { day:'numeric', month:'short' });
  } catch { return dateStr; }
}

// ── Real-time Live Updates (SSE) ─────────────────────────────────────
let _sse = null;
let _sseFails = 0;

function startLiveUpdates() {
  _setBadge('connecting');
  _sse = new EventSource('http://localhost:8000/api/stocks/stream');

  _sse.onopen = () => {
    _sseFails = 0;
    _setBadge('live');
  };

  _sse.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === 'stocks_update' && payload.stocks) {
        allStocks = payload.stocks;
        updatePricesInPlace(payload.stocks);
        _setBadge('live', payload.timestamp);
      }
    } catch (_) {}
  };

  _sse.onerror = () => {
    _sseFails++;
    _setBadge('offline');
    _sse.close();
    // Exponential back-off: 10s, 20s, 40s … max 5 min
    const delay = Math.min(300_000, 10_000 * Math.pow(2, _sseFails - 1));
    setTimeout(startLiveUpdates, delay);
  };
}

function updatePricesInPlace(stocks) {
  stocks.forEach(s => {
    const priceEl  = document.getElementById(`price-${s.ticker}`);
    const changeEl = document.getElementById(`change-${s.ticker}`);
    const volEl    = document.getElementById(`vol-${s.ticker}`);
    if (!priceEl) return;

    const oldPrice = parseFloat(priceEl.dataset.value || '0');
    const newPrice = s.price;

    // Flash only when price actually changed
    if (oldPrice !== 0 && oldPrice !== newPrice) {
      const cls = newPrice > oldPrice ? 'flash-up' : 'flash-down';
      priceEl.classList.remove('flash-up', 'flash-down');
      void priceEl.offsetWidth;  // force reflow
      priceEl.classList.add(cls);
    }

    priceEl.textContent    = `KES ${newPrice.toFixed(2)}`;
    priceEl.dataset.value  = newPrice;

    if (changeEl) {
      const up = s.change_pct >= 0;
      changeEl.className   = up ? 'change-up' : 'change-down';
      changeEl.textContent = `${up ? '▲' : '▼'} ${Math.abs(s.change_pct).toFixed(2)}%`;
    }
    if (volEl) volEl.textContent = formatVolume(s.volume);
    // Update source badge
    const srcEl = document.getElementById(`src-${s.ticker}`);
    if (srcEl) srcEl.outerHTML = _srcBadge(s.data_source || 'estimated', s.data_as_of);
  });

  // Also refresh ticker tape and overview
  renderTicker(stocks);
  _refreshOverviewInPlace(stocks);

  // Refresh Watchlist, Portfolio, Recommendations, and active Stock Signal
  loadWatchlist().catch(e => console.warn('live update watchlist error:', e));
  loadPortfolio().catch(e => console.warn('live update portfolio error:', e));
  loadRecommendations().catch(e => console.warn('live update recs error:', e));
  if (currentTicker) {
    loadSignal(currentTicker).catch(e => console.warn('live update signal error:', e));
  }
}

function _refreshOverviewInPlace(stocks) {
  _renderOverviewFromStocks(stocks);
}

function _setBadge(state, timestamp) {
  const badge = document.getElementById('live-update-badge');
  if (!badge) return;
  badge.className = `live-badge ${state === 'live' ? '' : state}`;
  if (state === 'live') {
    const t = timestamp ? new Date(timestamp).toLocaleTimeString('en-KE', { timeZone:'Africa/Nairobi', hour12:false }) : '--';
    badge.textContent = `↻ LIVE  ${t}`;
  } else if (state === 'connecting') {
    badge.textContent = '↻ Connecting…';
  } else {
    badge.textContent = '↻ Offline — retrying';
  }
}

// ── Watchlist & Portfolio Functions ─────────────────────────────────────────

function populateWatchlistAndBuySelects() {
  const wSelect = document.getElementById('watchlist-select');
  const bSelect = document.getElementById('buy-ticker-select');
  if (!allStocks || !allStocks.length) return;
  
  const options = allStocks
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
    .map(s => `<option value="${s.ticker}">${s.ticker} - ${s.name}</option>`)
    .join('');
    
  if (wSelect) wSelect.innerHTML = `<option value="">Add stock…</option>` + options;
  if (bSelect) bSelect.innerHTML = options;
}

async function loadWatchlist() {
  const watchlist = await api.getWatchlist();
  if (watchlist) {
    localStorage.setItem('nse_watchlist_cache', JSON.stringify(watchlist));
  }
  renderWatchlistFromData(watchlist);
}

function renderWatchlistFromData(watchlist) {
  const tbody = document.getElementById('watchlist-tbody');
  if (!tbody) return;
  watchlistTickers.clear();
  
  if (!watchlist || !watchlist.length) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:1.5rem; color:var(--text-muted);">Your watchlist is empty.</td></tr>`;
    updateTableStars();
    updateSpotlightStar();
    return;
  }
  
  watchlist.forEach(w => watchlistTickers.add(w.ticker.toUpperCase()));
  
  tbody.innerHTML = watchlist.map(w => {
    const changePct = w.change_pct || 0.0;
    return `
      <tr>
        <td style="font-weight:600; cursor:pointer;" onclick="jumpToStock('${w.ticker}')">${w.ticker}</td>
        <td>KES ${(w.current_price || 0.0).toFixed(2)}</td>
        <td class="${changePct >= 0 ? 'up' : 'down'}">
          ${changePct >= 0 ? '▲' : '▼'} ${Math.abs(changePct).toFixed(2)}%
        </td>
        <td style="text-align:right;">
          <button class="nav-dropdown-item danger" onclick="removeWatchlist('${w.ticker}')" style="display:inline-block; padding:0.25rem 0.5rem; font-size:0.8rem; border-radius:4px; border:1px solid var(--border-color); background:transparent; color:#ff4f4f; cursor:pointer;">✕ Remove</button>
        </td>
      </tr>
    `;
  }).join('');
  
  updateTableStars();
  updateSpotlightStar();
}

async function loadPortfolio() {
  const data = await api.getPortfolio();
  if (data) {
    localStorage.setItem('nse_portfolio_cache', JSON.stringify(data));
  }
  renderPortfolioFromData(data);
  if (isDiversificationOpen) {
    api.getPortfolioDiversification().then(d => d && renderDiversificationAnalytics(d));
  }
  if (isPortfolioMacroOpen) {
    api.getPortfolioMacro().then(d => d && renderPortfolioMacroAnalytics(d));
  }
}

function renderPortfolioFromData(data) {
  const tbody = document.getElementById('portfolio-tbody');
  if (!tbody) return;
  
  if (!data || !data.holdings || !data.holdings.length) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:1.5rem; color:var(--text-muted);">No holdings recorded.</td></tr>`;
    document.getElementById('port-total-cost').textContent = 'KES 0.00';
    document.getElementById('port-market-value').textContent = 'KES 0.00';
    document.getElementById('port-profit-loss').textContent = 'KES 0.00 (0.00%)';
    const feeEl = document.getElementById('port-statutory-fees');
    if (feeEl) feeEl.textContent = 'KES 0.00';
    return;
  }
  
  tbody.innerHTML = data.holdings.map(h => {
    const netPl = (h.net_profit_loss !== undefined) ? h.net_profit_loss : (h.profit_loss || 0.0);
    const netPlPct = (h.net_profit_loss_pct !== undefined) ? h.net_profit_loss_pct : (h.profit_loss_pct || 0.0);
    const bePrice = h.breakeven_price || (h.buy_price * 1.04269);
    const netVal = (h.net_market_value !== undefined) ? h.net_market_value : (h.market_value || 0.0);
    const totalFees = h.total_statutory_fees || 0.0;

    return `
      <tr>
        <td style="font-weight:600; cursor:pointer;" onclick="jumpToStock('${h.ticker}')">${h.ticker}</td>
        <td>${h.quantity.toLocaleString()}</td>
        <td>KES ${h.buy_price.toFixed(2)}</td>
        <td style="color:var(--accent); font-weight:600;" title="Target price to clear buy & sell statutory fees">
          KES ${bePrice.toFixed(2)} <span style="font-size:0.75rem; color:var(--text-muted);">(+4.3%)</span>
        </td>
        <td>KES ${h.current_price.toFixed(2)}</td>
        <td title="Net liquidation value after exit fees">
          KES ${netVal.toLocaleString('en-KE', { minimumFractionDigits: 2 })}
        </td>
        <td class="${netPl >= 0 ? 'up' : 'down'}" title="True Net P&L (Total statutory fees: KES ${totalFees.toFixed(2)})">
          ${netPl >= 0 ? '+' : ''}KES ${netPl.toFixed(2)} (${netPlPct.toFixed(2)}%)
        </td>
        <td style="text-align:right;">
          <button onclick="removePortfolio('${h.id}')" style="display:inline-block; padding:0.25rem 0.5rem; font-size:0.8rem; border-radius:4px; border:1px solid var(--border-color); background:transparent; color:#ff4f4f; cursor:pointer;">✕ Sell</button>
        </td>
      </tr>
    `;
  }).join('');
  
  const sum = data.summary || {};
  const totalCost = sum.total_outlay !== undefined ? sum.total_outlay : (sum.total_cost || 0);
  const totalValue = sum.total_net_value !== undefined ? sum.total_net_value : (sum.total_value || 0);
  const netPl = sum.portfolio_net_profit_loss !== undefined ? sum.portfolio_net_profit_loss : (sum.portfolio_profit_loss || 0);
  const netPlPct = sum.portfolio_net_profit_loss_pct !== undefined ? sum.portfolio_net_profit_loss_pct : (sum.portfolio_profit_loss_pct || 0);
  const totalFees = sum.total_statutory_fees || 0;

  document.getElementById('port-total-cost').textContent = `KES ${totalCost.toLocaleString('en-KE', { minimumFractionDigits: 2 })}`;
  document.getElementById('port-market-value').textContent = `KES ${totalValue.toLocaleString('en-KE', { minimumFractionDigits: 2 })}`;
  
  const plEl = document.getElementById('port-profit-loss');
  plEl.textContent = `${netPl >= 0 ? '+' : ''}KES ${netPl.toLocaleString('en-KE', { minimumFractionDigits: 2 })} (${netPlPct.toFixed(2)}%)`;
  plEl.className = netPl >= 0 ? 'up' : 'down';

  const feeEl = document.getElementById('port-statutory-fees');
  if (feeEl) {
    feeEl.textContent = `KES ${totalFees.toLocaleString('en-KE', { minimumFractionDigits: 2 })}`;
  }
}

function updateBuyModalPreview() {
  const qtyInput = document.getElementById('buy-qty-input');
  const priceInput = document.getElementById('buy-price-input');
  const grossEl = document.getElementById('modal-fee-gross');
  const statutoryEl = document.getElementById('modal-fee-statutory');
  const outlayEl = document.getElementById('modal-fee-outlay');
  const beEl = document.getElementById('modal-fee-breakeven');

  if (!qtyInput || !priceInput || !grossEl || !statutoryEl || !outlayEl || !beEl) return;

  const qty = parseInt(qtyInput.value) || 0;
  const price = parseFloat(priceInput.value) || 0.0;

  const gross = qty * price;
  // Kenya statutory single-way rate: 2.09% (Broker 1.50% + VAT 0.24% + CMA 0.14% + NSE 0.12% + CDSC 0.08% + ICF 0.01%)
  const buyFees = gross * 0.0209;
  const totalOutlay = gross + buyFees;
  // Roundtrip breakeven multiplier: (1 + 0.0209) / (1 - 0.0209) ≈ 1.04269 (+4.27%)
  const breakeven = price > 0 ? (price * 1.04269) : 0.0;

  grossEl.textContent = `KES ${gross.toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  statutoryEl.textContent = `+ KES ${buyFees.toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  outlayEl.textContent = `KES ${totalOutlay.toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  beEl.textContent = price > 0 
    ? `KES ${breakeven.toFixed(2)} (+4.27%)`
    : `KES 0.00 (+4.27%)`;
}

function bindWatchlistAndPortfolioEvents() {
  const select = document.getElementById('watchlist-select');
  if (select) {
    select.onchange = async () => {
      const ticker = select.value;
      if (!ticker) return;
      const res = await api.addToWatchlist(ticker);
      if (res) {
        watchlistTickers.add(ticker.toUpperCase());
        loadWatchlist();
        select.value = '';
      }
    };
  }
  
  // Backwards compatibility for the Add button if it still exists
  const btnW = document.getElementById('btn-add-watchlist');
  if (btnW) {
    btnW.onclick = async () => {
      const select = document.getElementById('watchlist-select');
      const ticker = select.value;
      if (!ticker) return;
      const res = await api.addToWatchlist(ticker);
      if (res) {
        watchlistTickers.add(ticker.toUpperCase());
        loadWatchlist();
        select.value = '';
      }
    };
  }

  // Real-time calculation listeners for Buy Modal
  const qtyInput = document.getElementById('buy-qty-input');
  const priceInput = document.getElementById('buy-price-input');
  const tickerSelect = document.getElementById('buy-ticker-select');
  const btnShowBuy = document.getElementById('btn-show-buy-modal');

  if (qtyInput) qtyInput.addEventListener('input', updateBuyModalPreview);
  if (priceInput) priceInput.addEventListener('input', updateBuyModalPreview);
  
  if (tickerSelect) {
    tickerSelect.addEventListener('change', () => {
      const ticker = tickerSelect.value;
      if (ticker && allStocks && allStocks.length) {
        const found = allStocks.find(s => s.ticker === ticker);
        if (found && found.price) {
          priceInput.value = found.price;
        }
      }
      updateBuyModalPreview();
    });
  }

  if (btnShowBuy) {
    btnShowBuy.onclick = () => openBuyModal();
  }
  
  const btnB = document.getElementById('btn-submit-buy');
  if (btnB) {
    btnB.onclick = submitBuyHolding;
  }

  const buyModal = document.getElementById('buy-modal');
  if (buyModal && !buyModal.dataset.backdropBound) {
    buyModal.dataset.backdropBound = 'true';
    buyModal.addEventListener('click', (e) => {
      if (e.target === buyModal) closeBuyModal();
    });
  }
}

function openBuyModal(ticker = null) {
  const modal = document.getElementById('buy-modal');
  const tickerSelect = document.getElementById('buy-ticker-select');
  const priceInput = document.getElementById('buy-price-input');
  
  if (ticker && tickerSelect) {
    tickerSelect.value = ticker;
  }
  
  if (tickerSelect && tickerSelect.value && (!priceInput.value || parseFloat(priceInput.value) <= 0 || ticker)) {
    const selectedTicker = tickerSelect.value;
    const found = (allStocks || []).find(s => s.ticker === selectedTicker);
    if (found && found.price) {
      if (priceInput) priceInput.value = found.price;
    }
  }
  updateBuyModalPreview();
  if (modal) modal.style.display = 'flex';
}
window.openBuyModal = openBuyModal;

function closeBuyModal() {
  const modal = document.getElementById('buy-modal');
  if (modal) modal.style.display = 'none';
}
window.closeBuyModal = closeBuyModal;

async function submitBuyHolding() {
  const btnB = document.getElementById('btn-submit-buy');
  const tickerSelect = document.getElementById('buy-ticker-select');
  const qtyInput = document.getElementById('buy-qty-input');
  const priceInput = document.getElementById('buy-price-input');
  
  const ticker = tickerSelect ? tickerSelect.value.trim().toUpperCase() : '';
  const qty = qtyInput ? parseInt(qtyInput.value, 10) : NaN;
  const price = priceInput ? parseFloat(priceInput.value) : NaN;
  
  if (!ticker) {
    alert("Please select a stock ticker.");
    return;
  }
  if (isNaN(qty) || qty <= 0) {
    alert("Please specify a valid share quantity greater than 0.");
    if (qtyInput) qtyInput.focus();
    return;
  }
  if (isNaN(price) || price <= 0) {
    alert("Please specify a valid buy price greater than 0.");
    if (priceInput) priceInput.focus();
    return;
  }
  
  const originalText = btnB ? btnB.textContent : 'Save Holding';
  if (btnB) {
    btnB.disabled = true;
    btnB.textContent = 'Saving...';
  }
  
  try {
    const res = await api.addToPortfolio(ticker, price, qty);
    if (res) {
      closeBuyModal();
      if (qtyInput) qtyInput.value = '';
      if (priceInput) priceInput.value = '';
      updateBuyModalPreview();
      await loadPortfolio();
    }
  } catch (err) {
    console.error('Failed to add holding:', err);
    alert(`Error saving holding: ${err.message || 'Unknown error'}`);
  } finally {
    if (btnB) {
      btnB.disabled = false;
      btnB.textContent = originalText;
    }
  }
}
window.submitBuyHolding = submitBuyHolding;

async function removeWatchlist(ticker) {
  const res = await api.removeFromWatchlist(ticker);
  if (res) {
    watchlistTickers.delete(ticker.toUpperCase());
    loadWatchlist();
  }
}

async function removePortfolio(id) {
  if (confirm("Are you sure you want to sell/delete this portfolio holding?")) {
    const res = await api.removeFromPortfolio(id);
    if (res) loadPortfolio();
  }
}

// ── Toggle Watchlist Star Helpers ───────────────────────────────────────────

async function toggleWatchlist(event, ticker) {
  if (event) event.stopPropagation();
  ticker = ticker.toUpperCase();
  const isStarred = watchlistTickers.has(ticker);
  if (isStarred) {
    const res = await api.removeFromWatchlist(ticker);
    if (res) {
      watchlistTickers.delete(ticker);
      loadWatchlist();
    }
  } else {
    const res = await api.addToWatchlist(ticker);
    if (res) {
      watchlistTickers.add(ticker);
      loadWatchlist();
    }
  }
}

function updateTableStars() {
  document.querySelectorAll('.star-btn').forEach(btn => {
    const ticker = btn.getAttribute('data-ticker');
    if (!ticker) return;
    if (watchlistTickers.has(ticker.toUpperCase())) {
      btn.innerHTML = '★';
      btn.style.color = '#ffd700';
    } else {
      btn.innerHTML = '☆';
      btn.style.color = 'var(--text-muted)';
    }
  });
}

function updateSpotlightStar() {
  const btn = document.querySelector('#signal-card .star-btn');
  if (!btn) return;
  const ticker = btn.getAttribute('data-ticker');
  if (!ticker) return;
  if (watchlistTickers.has(ticker.toUpperCase())) {
    btn.innerHTML = '★';
    btn.style.color = '#ffd700';
  } else {
    btn.innerHTML = '☆';
    btn.style.color = 'var(--text-muted)';
  }
}

// ── AI Copilot & Portfolio Optimizer Functions ──────────────────────────────

function toggleCopilotDrawer() {
  const drawer = document.getElementById('copilot-drawer');
  if (drawer) {
    drawer.classList.toggle('open');
  }
}

async function sendCopilotMessage() {
  const input = document.getElementById('copilot-input');
  if (!input || !input.value.trim()) return;
  
  const msg = input.value.trim();
  input.value = '';
  
  const msgContainer = document.getElementById('copilot-messages');
  if (!msgContainer) return;
  
  // Append user bubble
  const userDiv = document.createElement('div');
  userDiv.className = 'copilot-msg user';
  userDiv.textContent = msg;
  msgContainer.appendChild(userDiv);
  msgContainer.scrollTop = msgContainer.scrollHeight;
  
  // Append temporary loading bubble
  const loadDiv = document.createElement('div');
  loadDiv.className = 'copilot-msg assistant';
  loadDiv.innerHTML = 'Thinking...';
  msgContainer.appendChild(loadDiv);
  msgContainer.scrollTop = msgContainer.scrollHeight;
  
  // Send POST to /api/copilot/chat
  const res = await api.post('/api/copilot/chat', { message: msg });
  
  // Remove loading bubble
  msgContainer.removeChild(loadDiv);
  
  const replyDiv = document.createElement('div');
  replyDiv.className = 'copilot-msg assistant';
  
  if (res && res.reply) {
    // Simple markdown formatting helper
    let formatted = res.reply
      .replace(/### (.*)/g, '<h3>$1</h3>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/\n\n/g, '<br><br>')
      .replace(/\n\* /g, '<br>• ');
    replyDiv.innerHTML = formatted;
  } else {
    replyDiv.textContent = "Sorry, I couldn't reach the Copilot service right now.";
  }
  
  msgContainer.appendChild(replyDiv);
  msgContainer.scrollTop = msgContainer.scrollHeight;
}

async function runPortfolioOptimization() {
  const resultsDiv = document.getElementById('portfolio-optimizer-results');
  const weightsGrid = document.getElementById('optimizer-weights-grid');
  const expectedReturn = document.getElementById('opt-expected-return');
  const expectedVol = document.getElementById('opt-expected-vol');
  const sharpeRatio = document.getElementById('opt-sharpe-ratio');
  
  if (!resultsDiv || !weightsGrid) return;
  
  // Show results pane with loading state
  resultsDiv.style.display = 'block';
  weightsGrid.innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem;">Solving Markowitz Efficient Frontier...</div>';
  expectedReturn.textContent = '--';
  expectedVol.textContent = '--';
  sharpeRatio.textContent = '--';
  
  // Call optimize endpoint
  const res = await api.post('/api/portfolio/optimize', {});
  
  if (res && res.status !== 'error') {
    // Render weights chips
    weightsGrid.innerHTML = Object.entries(res.weights)
      .map(([ticker, weight]) => {
        const pct = (weight * 100).toFixed(1);
        return `<div class="optimizer-chip">${ticker}: <span>${pct}%</span></div>`;
      })
      .join('');
      
    // Render metrics
    expectedReturn.textContent = `${(res.expected_return * 100).toFixed(2)}%`;
    expectedVol.textContent = `${(res.expected_volatility * 100).toFixed(2)}%`;
    sharpeRatio.textContent = res.sharpe_ratio.toFixed(2);
  } else {
    weightsGrid.innerHTML = `<div style="color:var(--red); font-size:0.85rem;">Optimization failed: ${res ? res.message : 'Unknown error'}</div>`;
  }
}

// ── Portfolio Diversification & Correlation Heatmap ─────────────────────────
let isDiversificationOpen = false;

async function toggleDiversificationAnalytics() {
  const panel = document.getElementById('portfolio-diversification-panel');
  if (!panel) return;

  if (isDiversificationOpen) {
    panel.style.display = 'none';
    isDiversificationOpen = false;
    return;
  }

  panel.style.display = 'block';
  isDiversificationOpen = true;

  const listEl = document.getElementById('div-insights-list');
  if (listEl) {
    listEl.innerHTML = '<li>Computing covariance, correlation matrices, and HHI across holdings…</li>';
  }

  const data = await api.getPortfolioDiversification();
  if (data) {
    renderDiversificationAnalytics(data);
  }
}

function renderDiversificationAnalytics(data) {
  const emptyStateEl = document.getElementById('div-empty-state');
  const activeContentEl = document.getElementById('div-active-content');
  const badgeEl = document.getElementById('div-hhi-badge');

  if (!data || data.has_holdings === false || !data.sector_allocations || data.sector_allocations.length === 0) {
    if (emptyStateEl) emptyStateEl.style.display = 'block';
    if (activeContentEl) activeContentEl.style.display = 'none';
    if (badgeEl) {
      badgeEl.textContent = '⚪ No Holdings Recorded';
      badgeEl.style.color = 'var(--text-muted)';
      badgeEl.style.borderColor = 'rgba(255,255,255,0.15)';
      badgeEl.style.background = 'rgba(255,255,255,0.04)';
    }
    return;
  }

  // Active holdings exist
  if (emptyStateEl) emptyStateEl.style.display = 'none';
  if (activeContentEl) activeContentEl.style.display = 'block';

  // 1. Badge & KPIs
  const hhiEl = document.getElementById('div-sector-hhi');
  const effSectorsEl = document.getElementById('div-eff-sectors');
  const effAssetsEl = document.getElementById('div-eff-assets');

  if (badgeEl) {
    const icon = data.status === 'DIVERSIFIED' ? '🟢' : (data.status === 'MODERATE' ? '🟡' : '🔴');
    badgeEl.textContent = `${icon} HHI: ${data.hhi_score.toFixed(4)} (${data.status})`;
    badgeEl.style.color = data.status_color || '#fff';
    badgeEl.style.borderColor = `${data.status_color}55`;
    badgeEl.style.background = `${data.status_color}22`;
  }

  if (hhiEl) hhiEl.textContent = data.hhi_score.toFixed(4);
  if (effSectorsEl) effSectorsEl.textContent = `${data.effective_sectors} sectors`;
  if (effAssetsEl) effAssetsEl.textContent = `${data.effective_assets} assets`;

  // 2. Sector Exposure Progress Bars
  const sectorBarsEl = document.getElementById('div-sector-bars');
  if (sectorBarsEl && data.sector_allocations) {
    sectorBarsEl.innerHTML = data.sector_allocations.map(s => {
      const color = s.color || 'var(--accent)';
      return `
        <div style="display:flex; flex-direction:column; gap:3px;">
          <div style="display:flex; justify-content:space-between; font-size:0.8rem;">
            <span style="font-weight:600; display:flex; align-items:center; gap:6px;">
              <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${color};"></span>
              ${s.sector} <span style="font-size:0.75rem; color:var(--text-muted); font-weight:normal;">(${s.tickers.join(', ')})</span>
            </span>
            <span><b>${s.weight_pct.toFixed(1)}%</b> <span style="font-size:0.75rem; color:var(--text-muted);">(KES ${s.value.toLocaleString('en-KE', {minimumFractionDigits: 2})})</span></span>
          </div>
          <div style="height:6px; background:rgba(255,255,255,0.06); border-radius:3px; overflow:hidden;">
            <div style="height:100%; width:${Math.min(100, Math.max(2, s.weight_pct))}%; background:${color}; border-radius:3px; transition:width 0.4s ease;"></div>
          </div>
        </div>
      `;
    }).join('');
  }

  // 3. Asset Correlation Heatmap
  const assetHeatmapWrap = document.getElementById('div-asset-heatmap-wrap');
  if (assetHeatmapWrap && data.asset_correlation) {
    assetHeatmapWrap.innerHTML = generateHeatmapTableHtml(
      data.asset_correlation.tickers,
      data.asset_correlation.matrix
    );
  }

  // 4. Sector Correlation Heatmap
  const sectorHeatmapWrap = document.getElementById('div-sector-heatmap-wrap');
  if (sectorHeatmapWrap && data.sector_correlation) {
    sectorHeatmapWrap.innerHTML = generateHeatmapTableHtml(
      data.sector_correlation.sectors,
      data.sector_correlation.matrix
    );
  }

  // 5. Macro & Risk Insights
  const listEl = document.getElementById('div-insights-list');
  if (listEl) {
    if (data.risk_insights && data.risk_insights.length > 0) {
      listEl.innerHTML = data.risk_insights.map(i => `<li>${i}</li>`).join('');
    } else {
      listEl.innerHTML = '<li>Portfolio exhibits standard market behavior with balanced diversification.</li>';
    }
  }
}

function generateHeatmapTableHtml(labels, matrix) {
  if (!labels || !labels.length || !matrix || !matrix.length) {
    return '<div style="color:var(--text-muted); font-size:0.8rem; padding:0.5rem;">Insufficient historical data for correlation matrix.</div>';
  }

  const thCols = labels.map(l => `<th style="padding:6px 10px; font-size:0.75rem; text-align:center; color:var(--text-muted); border-bottom:1px solid var(--border-color);">${l}</th>`).join('');

  const rows = labels.map((rowLabel, i) => {
    const cells = labels.map((colLabel, j) => {
      const val = matrix[i] && matrix[i][j] !== undefined ? matrix[i][j] : 0.0;
      let bg = 'rgba(255, 255, 255, 0.04)';
      let textColor = '#e0e0e0';

      if (i === j) {
        bg = 'rgba(124, 77, 255, 0.18)';
        textColor = 'var(--accent)';
      } else if (val >= 0.70) {
        bg = 'rgba(255, 82, 82, 0.35)';
        textColor = '#ff5252';
      } else if (val >= 0.30) {
        bg = 'rgba(255, 215, 0, 0.22)';
        textColor = '#ffd700';
      } else if (val <= 0.20) {
        bg = 'rgba(0, 230, 118, 0.22)';
        textColor = '#00e676';
      }

      const tooltip = `${rowLabel} vs ${colLabel}: Correlation = ${val.toFixed(2)}`;
      return `
        <td style="padding:6px 10px; text-align:center; font-size:0.75rem; font-family:var(--font-mono); background:${bg}; color:${textColor}; border:1px solid rgba(255,255,255,0.03);" title="${tooltip}">
          ${val.toFixed(2)}
        </td>
      `;
    }).join('');

    return `
      <tr>
        <td style="padding:6px 10px; font-size:0.75rem; font-weight:600; color:var(--text-muted); text-align:right; border-right:1px solid var(--border-color); white-space:nowrap;">
          ${rowLabel}
        </td>
        ${cells}
      </tr>
    `;
  }).join('');

  return `
    <table style="width:100%; border-collapse:collapse;">
      <thead>
        <tr>
          <th style="padding:6px 10px; font-size:0.72rem; color:var(--text-muted); border-bottom:1px solid var(--border-color); text-align:right;"></th>
          ${thCols}
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  `;
}

// ── Macro Yield Comparison Modal ──────────────────────────────────────────
async function openMacroYieldModal() {
  const modal = document.getElementById('macro-yield-modal');
  if (!modal) return;
  modal.style.display = 'flex';

  const tbody = document.getElementById('modal-macro-stocks-tbody');
  if (tbody) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:1.5rem; color:var(--text-muted);">Loading live yield comparison from CBK & NSE…</td></tr>';
  }

  const data = await api.getMacroYieldComparison();
  if (!data) {
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:1.5rem; color:#ff4f4f;">Failed to load macro benchmarks.</td></tr>';
    return;
  }

  // Populate KPIs
  const bm = data.benchmarks;
  if (bm) {
    const t91 = document.getElementById('modal-tbill-91d');
    const t182 = document.getElementById('modal-tbill-182d');
    const t364 = document.getElementById('modal-tbill-364d');
    if (t91) t91.textContent = bm.tbill_91d.toFixed(2) + '%';
    if (t182) t182.textContent = bm.tbill_182d.toFixed(2) + '%';
    if (t364) t364.textContent = bm.tbill_364d.toFixed(2) + '%';
  }

  const stats = data.market_stats;
  if (stats) {
    const avgDiv = document.getElementById('modal-avg-div-yield');
    const payerDiv = document.getElementById('modal-payer-div-yield');
    if (avgDiv) avgDiv.textContent = stats.average_market_dividend_yield.toFixed(2) + '%';
    if (payerDiv) payerDiv.textContent = `Payers: ${stats.average_payer_dividend_yield.toFixed(2)}% (${stats.dividend_paying_stocks} stocks)`;
  }

  // Populate Insights
  const insightsEl = document.getElementById('modal-macro-insights');
  if (insightsEl && data.macro_insights) {
    insightsEl.innerHTML = data.macro_insights.map(i => `<div style="margin-bottom:4px;">${i}</div>`).join('');
  }

  // Populate Table
  if (tbody && data.stocks) {
    tbody.innerHTML = data.stocks.map(s => {
      const isTop = s.gross_dividend_yield >= 10.0;
      const isHealthy = s.gross_dividend_yield >= 5.0;
      const yieldColor = isTop ? '#00e676' : (isHealthy ? 'var(--accent)' : (s.gross_dividend_yield > 0 ? '#fff' : 'var(--text-muted)'));
      const spreadColor = s.net_yield_spread >= 0 ? '#00e676' : (s.net_yield_spread >= -5.0 ? '#ffd700' : 'var(--text-muted)');
      
      return `
        <tr onclick="jumpToStock('${s.ticker}'); document.getElementById('macro-yield-modal').style.display='none';" style="cursor:pointer;">
          <td style="font-weight:700; color:#fff;">${s.ticker}</td>
          <td style="color:var(--text-muted); font-size:0.75rem;">${s.sector}</td>
          <td style="font-family:var(--font-mono);">KES ${s.current_price.toFixed(2)}</td>
          <td style="font-family:var(--font-mono);">${s.dividend_per_share > 0 ? 'KES ' + s.dividend_per_share.toFixed(2) : '—'}</td>
          <td style="font-family:var(--font-mono); font-weight:700; color:${yieldColor};">${s.gross_dividend_yield.toFixed(2)}%</td>
          <td style="font-family:var(--font-mono); color:${yieldColor};">${s.net_dividend_yield.toFixed(2)}%</td>
          <td style="font-family:var(--font-mono); color:${spreadColor}; font-weight:600;">${s.net_yield_spread >= 0 ? '+' : ''}${s.net_yield_spread.toFixed(2)}%</td>
          <td style="font-family:var(--font-mono); color:var(--text-primary);">+${s.required_growth_hurdle.toFixed(2)}%/yr</td>
          <td>
            <span style="font-size:0.72rem; padding:2px 8px; border-radius:10px; background:${s.verdict_color}22; color:${s.verdict_color}; border:1px solid ${s.verdict_color}55;">
              ${s.verdict_badge}
            </span>
          </td>
        </tr>
      `;
    }).join('');
  }
}

// ── Portfolio Macro Yield vs T-Bill ───────────────────────────────────────
let isPortfolioMacroOpen = false;

async function togglePortfolioMacroAnalytics() {
  const panel = document.getElementById('portfolio-macro-panel');
  if (!panel) return;

  if (isPortfolioMacroOpen) {
    panel.style.display = 'none';
    isPortfolioMacroOpen = false;
    return;
  }

  // Close diversification panel if open so they don't crowd the screen
  const divPanel = document.getElementById('portfolio-diversification-panel');
  if (divPanel) divPanel.style.display = 'none';
  isDiversificationOpen = false;

  panel.style.display = 'block';
  isPortfolioMacroOpen = true;

  const data = await api.getPortfolioMacro();
  if (data) {
    renderPortfolioMacroAnalytics(data);
  }
}

function renderPortfolioMacroAnalytics(data) {
  const emptyStateEl = document.getElementById('port-macro-empty-state');
  const activeContentEl = document.getElementById('port-macro-active-content');
  const badgeEl = document.getElementById('port-macro-badge');

  if (!data || data.has_holdings === false || !data.holding_breakdown || data.holding_breakdown.length === 0) {
    if (emptyStateEl) emptyStateEl.style.display = 'block';
    if (activeContentEl) activeContentEl.style.display = 'none';
    if (badgeEl) {
      badgeEl.textContent = '⚪ No Holdings Recorded';
      badgeEl.style.color = 'var(--text-muted)';
      badgeEl.style.borderColor = 'rgba(255,255,255,0.15)';
      badgeEl.style.background = 'rgba(255,255,255,0.04)';
    }
    return;
  }

  if (emptyStateEl) emptyStateEl.style.display = 'none';
  if (activeContentEl) activeContentEl.style.display = 'block';

  // Badge
  if (badgeEl) {
    badgeEl.textContent = data.macro_badge;
    badgeEl.style.color = data.macro_color || 'var(--accent)';
    badgeEl.style.borderColor = `${data.macro_color || 'var(--accent)'}55`;
    badgeEl.style.background = `${data.macro_color || 'var(--accent)'}22`;
  }

  // KPIs
  const yEl = document.getElementById('port-macro-weighted-yield');
  const nyEl = document.getElementById('port-macro-net-yield');
  const trEl = document.getElementById('port-macro-tbill-rate');
  const tnEl = document.getElementById('port-macro-tbill-net');
  const edEl = document.getElementById('port-macro-expected-divs');
  const ndEl = document.getElementById('port-macro-net-divs');
  const ghEl = document.getElementById('port-macro-growth-hurdle');
  const advEl = document.getElementById('port-macro-advisory-text');

  if (yEl) yEl.textContent = data.portfolio_dividend_yield.toFixed(2) + '%';
  if (nyEl) nyEl.textContent = `Net (5% WHT): ${data.portfolio_net_dividend_yield.toFixed(2)}%`;
  if (trEl) trEl.textContent = data.tbill_91d_rate.toFixed(2) + '%';
  if (tnEl) tnEl.textContent = `Net (15% WHT): ${data.net_tbill_91d_rate.toFixed(2)}%`;
  if (edEl) edEl.textContent = 'KES ' + data.expected_annual_dividends.toLocaleString('en-KE', {minimumFractionDigits: 2});
  if (ndEl) ndEl.textContent = 'Net cash: KES ' + data.expected_net_annual_dividends.toLocaleString('en-KE', {minimumFractionDigits: 2});
  if (ghEl) ghEl.textContent = '+' + data.required_portfolio_growth.toFixed(2) + '%/yr';
  if (advEl) advEl.innerHTML = data.macro_advisory;

  // Breakdown Table
  const tbody = document.getElementById('port-macro-holdings-tbody');
  if (tbody && data.holding_breakdown) {
    tbody.innerHTML = data.holding_breakdown.map(h => `
      <tr>
        <td style="font-weight:700; color:#fff; cursor:pointer;" onclick="jumpToStock('${h.ticker}')">${h.ticker}</td>
        <td>${h.weight_pct.toFixed(1)}%</td>
        <td style="font-family:var(--font-mono);">KES ${h.market_value.toLocaleString('en-KE', {minimumFractionDigits: 2})}</td>
        <td style="font-family:var(--font-mono);">${h.dividend_per_share > 0 ? 'KES ' + h.dividend_per_share.toFixed(2) : '—'}</td>
        <td style="font-family:var(--font-mono); font-weight:600; color:${h.dividend_yield >= 6 ? 'var(--accent)' : 'inherit'};">${h.dividend_yield.toFixed(2)}%</td>
        <td style="font-family:var(--font-mono);">${h.net_dividend_yield.toFixed(2)}%</td>
        <td style="font-family:var(--font-mono); font-weight:600; color:#00e676;">KES ${h.annual_dividends.toLocaleString('en-KE', {minimumFractionDigits: 2})}</td>
      </tr>
    `).join('');
  }
}

// ── IPO Pipeline & Alert Center ─────────────────────────────────────────────
let _ipoPipelineData = [];
let _activeIpoFilter = 'ALL';

async function loadActiveIpoAlert() {
  const banner = document.getElementById('ipo-alert-banner');
  const titleEl = document.getElementById('ipo-banner-title');
  const subEl = document.getElementById('ipo-banner-sub');
  const navBtnText = document.getElementById('nav-ipo-btn-text');

  try {
    const res = await api.getActiveIpoAlert();
    if (res && res.has_active_alert && res.alert) {
      const a = res.alert;
      if (titleEl) {
        titleEl.textContent = `${a.company_name} (${a.proposed_ticker || 'NSE'}) · ${a.listing_type || 'IPO'}`;
      }
      if (subEl) {
        const priceStr = a.offer_price ? `KES ${a.offer_price.toFixed(2)}` : (a.offer_price_range || 'Price TBD');
        let countdownStr = '';
        if (a.status === 'OFFER_OPEN') {
          countdownStr = a.days_to_close !== null ? `⏰ Closes in ${a.days_to_close} days (${a.offer_close_date})` : 'Offer Active';
        } else {
          countdownStr = a.days_to_open !== null && a.days_to_open > 0 ? `⏰ Opens in ${a.days_to_open} days (${a.offer_open_date})` : 'CMA Approved';
        }
        subEl.textContent = `${a.status === 'OFFER_OPEN' ? '🟢 OFFER IS OPEN' : '🟣 UPCOMING'} · Offer: ${priceStr} · ${countdownStr}`;
      }
      if (banner) banner.style.display = 'flex';
      if (navBtnText) {
        navBtnText.textContent = a.status === 'OFFER_OPEN' ? 'IPO Alerts (Offer Open!)' : 'IPO Alerts (1 Active)';
      }
    } else {
      if (banner) banner.style.display = 'none';
      if (navBtnText) navBtnText.textContent = 'IPO Alerts';
    }
  } catch (err) {
    console.warn('Failed to load active IPO alert:', err);
  }
}

async function openIpoModal(focusSms = false) {
  const modal = document.getElementById('ipo-modal');
  if (!modal) return;
  modal.style.display = 'flex';

  if (focusSms) {
    const input = document.getElementById('ipo-phone-input');
    if (input) {
      input.focus();
      input.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  await refreshIpoData();
}

function closeIpoModal() {
  const modal = document.getElementById('ipo-modal');
  if (modal) modal.style.display = 'none';
}

async function refreshIpoData() {
  const listEl = document.getElementById('ipo-pipeline-list');
  if (listEl) {
    listEl.innerHTML = '<div style="text-align:center; padding:2rem; color:var(--text-muted);">Fetching live CMA & NSE IPO pipeline…</div>';
  }

  try {
    const res = await api.getIpos();
    if (res && res.pipeline) {
      _ipoPipelineData = res.pipeline;
      
      // Update counts
      const allCount = document.getElementById('ipo-count-all');
      const openCount = document.getElementById('ipo-count-open');
      const upCount = document.getElementById('ipo-count-upcoming');
      if (allCount) allCount.textContent = res.stats.total || _ipoPipelineData.length;
      if (openCount) openCount.textContent = res.stats.offer_open_count || 0;
      if (upCount) upCount.textContent = res.stats.upcoming_count || 0;

      renderIpoPipelineList();
    } else {
      if (listEl) listEl.innerHTML = '<div style="text-align:center; padding:2rem; color:#ff4d6d;">Failed to load IPO pipeline.</div>';
    }
  } catch (err) {
    console.error('Error loading IPO pipeline:', err);
    if (listEl) listEl.innerHTML = `<div style="text-align:center; padding:2rem; color:#ff4d6d;">Error: ${err.message}</div>`;
  }
}

function filterIpoList(filter) {
  _activeIpoFilter = filter;
  ['all', 'open', 'upcoming'].forEach(t => {
    const el = document.getElementById(`ipo-tab-${t}`);
    if (el) el.classList.remove('active');
  });
  if (filter === 'ALL') document.getElementById('ipo-tab-all')?.classList.add('active');
  if (filter === 'OFFER_OPEN') document.getElementById('ipo-tab-open')?.classList.add('active');
  if (filter === 'UPCOMING') document.getElementById('ipo-tab-upcoming')?.classList.add('active');

  renderIpoPipelineList();
}

function renderIpoPipelineList() {
  const listEl = document.getElementById('ipo-pipeline-list');
  if (!listEl) return;

  let items = _ipoPipelineData;
  if (_activeIpoFilter !== 'ALL') {
    items = items.filter(x => x.status === _activeIpoFilter);
  }

  if (items.length === 0) {
    listEl.innerHTML = '<div style="text-align:center; padding:2.5rem; color:var(--text-muted); font-size:0.9rem;">No IPO listings found matching the selected filter.</div>';
    return;
  }

  listEl.innerHTML = items.map(ipo => {
    const isOfferOpen = ipo.status === 'OFFER_OPEN';
    const statusClass = ipo.status;
    const statusText = isOfferOpen ? '🟢 OFFER IS OPEN FOR SUBSCRIPTION' : (ipo.status === 'UPCOMING' ? '🟣 CMA APPROVED / UPCOMING' : ipo.status);
    const priceDisplay = ipo.offer_price ? `KES ${ipo.offer_price.toFixed(2)}` : (ipo.offer_price_range || 'To Be Announced');
    const minInvestment = ipo.offer_price && ipo.min_application_shares 
      ? `KES ${(ipo.offer_price * ipo.min_application_shares).toLocaleString('en-KE', {minimumFractionDigits: 2})}` 
      : '—';

    // Step tracker
    const step1Class = 'completed'; // Announcement
    const step2Class = ipo.cma_approval ? 'completed' : 'active'; // CMA Approval
    const step3Class = isOfferOpen ? 'active' : (ipo.status === 'UPCOMING' ? '' : 'completed'); // Offer Open
    const step4Class = ipo.status === 'LISTED' ? 'completed' : ''; // Listing day

    const verdictColor = ipo.ai_verdict === 'ATTRACTIVE' ? '#00e676' : (ipo.ai_verdict === 'FAIR_VALUE' ? '#ffd700' : '#ff4d6d');

    return `
      <div class="ipo-pipeline-card">
        <!-- Card Header -->
        <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px;">
          <div>
            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
              <span style="font-size:1.15rem; font-weight:800; color:#fff;">${ipo.company_name}</span>
              <span style="font-size:0.8rem; font-family:var(--font-mono); color:var(--accent); font-weight:700; background:rgba(0,229,160,0.1); padding:2px 6px; border-radius:4px;">
                ${ipo.proposed_ticker || 'NSE'}
              </span>
              <span style="font-size:0.75rem; color:var(--text-muted);">${ipo.sector} · ${ipo.listing_type}</span>
            </div>
            <div style="margin-top:4px;">
              <span class="ipo-status-badge ${statusClass}">${statusText}</span>
            </div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:0.75rem; color:var(--text-muted);">Offer Price</div>
            <div style="font-size:1.25rem; font-weight:800; font-family:var(--font-mono); color:#fff;">${priceDisplay}</div>
          </div>
        </div>

        <!-- Timetable Progress Tracker -->
        <div class="ipo-timeline-tracker">
          <div class="ipo-step ${step1Class}">
            <div class="ipo-step-node">✓</div>
            <div class="ipo-step-label">Announcement</div>
            <div class="ipo-step-date">${ipo.announcement_date || 'Approved'}</div>
          </div>
          <div class="ipo-step ${step2Class}">
            <div class="ipo-step-node">2</div>
            <div class="ipo-step-label">CMA Approval</div>
            <div class="ipo-step-date">Approved ✓</div>
          </div>
          <div class="ipo-step ${step3Class}">
            <div class="ipo-step-node">3</div>
            <div class="ipo-step-label">Offer Opens</div>
            <div class="ipo-step-date">${ipo.offer_open_date || 'Pending'}</div>
          </div>
          <div class="ipo-step">
            <div class="ipo-step-node">4</div>
            <div class="ipo-step-label">Offer Closes</div>
            <div class="ipo-step-date">${ipo.offer_close_date || 'Pending'}</div>
          </div>
          <div class="ipo-step ${step4Class}">
            <div class="ipo-step-node">5</div>
            <div class="ipo-step-label">First Trading Day</div>
            <div class="ipo-step-date">${ipo.listing_date || 'Pending'}</div>
          </div>
        </div>

        <!-- Offering Specs KPI Grid -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:8px; background:rgba(0,0,0,0.25); padding:0.7rem; border-radius:6px; border:1px solid rgba(255,255,255,0.03);">
          <div>
            <div style="font-size:0.7rem; color:var(--text-muted);">Target Capital</div>
            <div style="font-size:0.88rem; font-weight:700; color:#fff; font-family:var(--font-mono);">${ipo.target_capital || 'TBD'}</div>
          </div>
          <div>
            <div style="font-size:0.7rem; color:var(--text-muted);">Shares Offered</div>
            <div style="font-size:0.88rem; font-weight:700; color:#fff; font-family:var(--font-mono);">${ipo.shares_offered ? ipo.shares_offered.toLocaleString() : 'TBD'}</div>
          </div>
          <div>
            <div style="font-size:0.7rem; color:var(--text-muted);">Minimum Application Lot</div>
            <div style="font-size:0.88rem; font-weight:700; color:#fff; font-family:var(--font-mono);">${ipo.min_application_shares} shares</div>
          </div>
          <div>
            <div style="font-size:0.7rem; color:var(--text-muted);">Min. Capital Outlay</div>
            <div style="font-size:0.88rem; font-weight:700; color:var(--accent); font-family:var(--font-mono);">${minInvestment}</div>
          </div>
        </div>

        <!-- AI Prospectus Analysis Section -->
        <div style="background:rgba(124, 77, 255, 0.05); border:1px solid rgba(124, 77, 255, 0.2); border-radius:8px; padding:0.8rem 1rem;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="font-size:0.8rem; font-weight:700; color:#fff; display:flex; align-items:center; gap:6px;">
              <span>🤖</span> AI Prospectus Analysis & Intelligence
            </span>
            <span style="font-size:0.72rem; padding:2px 8px; border-radius:10px; font-weight:700; background:${verdictColor}22; color:${verdictColor}; border:1px solid ${verdictColor}55;">
              ${ipo.ai_verdict} (Score: ${Math.round(ipo.ai_verdict_score * 100)}%)
            </span>
          </div>
          <p style="font-size:0.8rem; line-height:1.45; color:var(--text-secondary); margin:0 0 8px 0;">
            ${ipo.ai_summary || 'Evaluating regulatory disclosures and business prospectus…'}
          </p>

          ${ipo.highlights && ipo.highlights.length > 0 ? `
            <div style="margin-bottom:6px;">
              <span style="font-size:0.72rem; font-weight:700; color:#00e676; text-transform:uppercase; letter-spacing:0.5px;">Key Catalysts:</span>
              <ul style="margin:3px 0 0 0; padding-left:1.2rem; font-size:0.75rem; color:var(--text-secondary);">
                ${ipo.highlights.map(h => `<li>${h}</li>`).join('')}
              </ul>
            </div>
          ` : ''}

          ${ipo.risk_factors && ipo.risk_factors.length > 0 ? `
            <div>
              <span style="font-size:0.72rem; font-weight:700; color:#ff4d6d; text-transform:uppercase; letter-spacing:0.5px;">Key Risk Factors:</span>
              <ul style="margin:3px 0 0 0; padding-left:1.2rem; font-size:0.75rem; color:var(--text-secondary);">
                ${ipo.risk_factors.map(r => `<li>${r}</li>`).join('')}
              </ul>
            </div>
          ` : ''}
          
          ${ipo.prospectus_url ? `
            <div style="margin-top:8px; text-align:right;">
              <a href="${ipo.prospectus_url}" target="_blank" rel="noopener" style="font-size:0.75rem; color:var(--accent); text-decoration:none; font-weight:600;">
                📄 View Full CMA Prospectus PDF ↗
              </a>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }).join('');
}

async function submitIpoSubscription() {
  const input = document.getElementById('ipo-phone-input');
  const btn = document.getElementById('btn-subscribe-ipo');
  const statusEl = document.getElementById('ipo-sub-status');
  if (!input) return;

  let phone = input.value.trim();
  if (!phone) {
    alert('Please enter your mobile phone number.');
    input.focus();
    return;
  }

  // Format local 07... or 01... numbers to Kenyan E.164 +254...
  if (phone.startsWith('07') || phone.startsWith('01')) {
    phone = '+254' + phone.substring(1);
    input.value = phone;
  } else if (!phone.startsWith('+')) {
    phone = '+' + phone;
    input.value = phone;
  }

  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Subscribing…';

  try {
    const res = await api.subscribeIpoAlerts(phone);
    if (res && res.message) {
      if (statusEl) {
        statusEl.style.display = 'block';
        statusEl.style.color = '#00e676';
        statusEl.textContent = `✓ ${res.message} on ${phone}. Confirmation SMS dispatched!`;
      }
      btn.textContent = 'Subscribed ✓';
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = origText;
      }, 3000);
    }
  } catch (err) {
    if (statusEl) {
      statusEl.style.display = 'block';
      statusEl.style.color = '#ff4d6d';
      statusEl.textContent = `Error: ${err.message || 'Failed to subscribe'}`;
    }
    btn.disabled = false;
    btn.textContent = origText;
  }
}

async function triggerSimulateIpoAlert() {
  const statusEl = document.getElementById('ipo-sub-status');
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.style.color = 'var(--accent)';
    statusEl.textContent = 'Broadcasting simulated IPO announcement alert…';
  }

  try {
    const res = await api.simulateIpoAlert({});
    if (res && res.status === 'simulation_dispatched') {
      if (statusEl) {
        statusEl.style.color = '#00e676';
        statusEl.textContent = `✓ Simulation Alert sent to ${res.recipients_count} subscriber(s): "${res.simulated_ipo}". Check SMS outbox!`;
      }
      // Reload banner and list
      loadActiveIpoAlert();
      refreshIpoData();
    }
  } catch (err) {
    if (statusEl) {
      statusEl.style.color = '#ff4d6d';
      statusEl.textContent = `Simulation error: ${err.message}`;
    }
  }
}

// ── Global Window Exports ───────────────────────────────────────────────────
window.bootDashboard = bootDashboard;
window.jumpToStock = jumpToStock;
window.openGainersLosersModal = openGainersLosersModal;
window.openMacroYieldModal = openMacroYieldModal;
window.removeWatchlist = removeWatchlist;
window.removePortfolio = removePortfolio;
window.toggleWatchlist = toggleWatchlist;
window.runPortfolioOptimization = runPortfolioOptimization;
window.toggleDiversificationAnalytics = toggleDiversificationAnalytics;
window.togglePortfolioMacroAnalytics = togglePortfolioMacroAnalytics;
window.toggleCopilotDrawer = toggleCopilotDrawer;
window.sendCopilotMessage = sendCopilotMessage;

// IPO Exports
window.loadActiveIpoAlert = loadActiveIpoAlert;
window.openIpoModal = openIpoModal;
window.closeIpoModal = closeIpoModal;
window.refreshIpoData = refreshIpoData;
window.filterIpoList = filterIpoList;
window.submitIpoSubscription = submitIpoSubscription;
window.triggerSimulateIpoAlert = triggerSimulateIpoAlert;

// ── Global Modal Backdrop & Escape Key Handlers ─────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const buyModal = document.getElementById('buy-modal');
    if (buyModal && buyModal.style.display !== 'none') closeBuyModal();
    const moversModal = document.getElementById('gainers-losers-modal');
    if (moversModal && moversModal.style.display !== 'none') moversModal.style.display = 'none';
    const macroModal = document.getElementById('macro-yield-modal');
    if (macroModal && macroModal.style.display !== 'none') macroModal.style.display = 'none';
    const ipoModal = document.getElementById('ipo-modal');
    if (ipoModal && ipoModal.style.display !== 'none') closeIpoModal();
  }
});

['gainers-losers-modal', 'macro-yield-modal', 'ipo-modal'].forEach(id => {
  const el = document.getElementById(id);
  if (el) {
    el.addEventListener('click', (e) => {
      if (e.target === el) el.style.display = 'none';
    });
  }
});

