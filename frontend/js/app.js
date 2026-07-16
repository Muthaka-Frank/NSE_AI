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
  try { bindChartControls(); bindTableSearch(); } catch(e) { console.warn('controls:', e); }

  // ── Step 1b: Render cached watchlist and portfolio instantly if available ────
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
    <ul class="signal-reasons">
      ${(d.reasoning || []).map(r => `<li>${r}</li>`).join('')}
    </ul>
    ${isSignal && d.price_target ? `
      <div class="signal-target" style="display:flex; flex-direction:column; align-items:flex-start; gap:4px;">
        <div style="width:100%; display:flex; justify-content:space-between; align-items:baseline;">
          <div class="signal-target-label">Price Target</div>
          <div class="signal-target-val">KES ${d.price_target}</div>
        </div>
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
}

function renderPortfolioFromData(data) {
  const tbody = document.getElementById('portfolio-tbody');
  if (!tbody) return;
  
  if (!data || !data.holdings || !data.holdings.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:1.5rem; color:var(--text-muted);">No holdings recorded.</td></tr>`;
    document.getElementById('port-total-cost').textContent = 'KES 0.00';
    document.getElementById('port-market-value').textContent = 'KES 0.00';
    document.getElementById('port-profit-loss').textContent = 'KES 0.00 (0.00%)';
    return;
  }
  
  tbody.innerHTML = data.holdings.map(h => {
    const pl = h.profit_loss || 0.0;
    const plPct = h.profit_loss_pct || 0.0;
    return `
      <tr>
        <td style="font-weight:600; cursor:pointer;" onclick="jumpToStock('${h.ticker}')">${h.ticker}</td>
        <td>${h.quantity}</td>
        <td>KES ${h.buy_price.toFixed(2)}</td>
        <td>KES ${h.current_price.toFixed(2)}</td>
        <td>KES ${h.market_value.toFixed(2)}</td>
        <td class="${pl >= 0 ? 'up' : 'down'}">
          ${pl >= 0 ? '+' : ''}${pl.toFixed(2)} (${plPct.toFixed(2)}%)
        </td>
        <td style="text-align:right;">
          <button onclick="removePortfolio('${h.id}')" style="display:inline-block; padding:0.25rem 0.5rem; font-size:0.8rem; border-radius:4px; border:1px solid var(--border-color); background:transparent; color:#ff4f4f; cursor:pointer;">✕ Sell</button>
        </td>
      </tr>
    `;
  }).join('');
  
  const sum = data.summary || { total_cost: 0, total_value: 0, portfolio_profit_loss: 0, portfolio_profit_loss_pct: 0 };
  document.getElementById('port-total-cost').textContent = `KES ${sum.total_cost.toLocaleString('en-KE', { minimumFractionDigits: 2 })}`;
  document.getElementById('port-market-value').textContent = `KES ${sum.total_value.toLocaleString('en-KE', { minimumFractionDigits: 2 })}`;
  
  const plEl = document.getElementById('port-profit-loss');
  plEl.textContent = `${sum.portfolio_profit_loss >= 0 ? '+' : ''}${sum.portfolio_profit_loss.toLocaleString('en-KE', { minimumFractionDigits: 2 })} (${sum.portfolio_profit_loss_pct.toFixed(2)}%)`;
  plEl.className = sum.portfolio_profit_loss >= 0 ? 'up' : 'down';
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
  
  const btnB = document.getElementById('btn-submit-buy');
  if (btnB) {
    btnB.onclick = async () => {
      const ticker = document.getElementById('buy-ticker-select').value;
      const qty = parseInt(document.getElementById('buy-qty-input').value);
      const price = parseFloat(document.getElementById('buy-price-input').value);
      
      if (!ticker || isNaN(qty) || qty <= 0 || isNaN(price) || price <= 0) {
        alert("Please specify valid quantity and buy price.");
        return;
      }
      
      const res = await api.addToPortfolio(ticker, price, qty);
      if (res) {
        document.getElementById('buy-modal').style.display = 'none';
        document.getElementById('buy-qty-input').value = '';
        document.getElementById('buy-price-input').value = '';
        loadPortfolio();
      }
    };
  }
}

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


