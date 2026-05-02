/**
 * NSE AI Platform — Main App Logic
 * Dashboard orchestration: ticker, recommendations, chart, news, stocks table.
 */

// ── State ─────────────────────────────────────────────────────────────────
let allStocks   = [];
let currentTicker  = 'SCOM';
let currentPeriod  = '3mo';

// ── Boot ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  startClock();
  await Promise.all([
    loadTicker(),
    loadOverview(),
    loadRecommendations(),
    loadNews(),
    loadStocksTable(),
  ]);
  populateChartSelect();
  initChart();
  await updateChart(currentTicker, currentPeriod);
  await loadSignal(currentTicker);
  bindChartControls();
  bindTableSearch();
  setInterval(loadTicker, 60_000);
  setInterval(loadNews,   120_000);
});

// ── Clock ─────────────────────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById('nav-time');
  const tick = () => {
    const now = new Date();
    el.textContent = now.toLocaleTimeString('en-KE', { timeZone:'Africa/Nairobi', hour12:false }) + ' EAT';
  };
  tick();
  setInterval(tick, 1000);

  const dateEl = document.getElementById('market-date');
  if (dateEl) {
    dateEl.textContent = 'NSE · ' + new Date().toLocaleDateString('en-KE', { weekday:'long', year:'numeric', month:'long', day:'numeric', timeZone:'Africa/Nairobi' });
  }
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
  const doubled = [...stocks, ...stocks]; // Seamless loop
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
  const gainers = stocks.filter(s => s.change_pct > 0).length;
  const losers  = stocks.filter(s => s.change_pct < 0).length;
  const avgChg  = stocks.reduce((a,s) => a + s.change_pct, 0) / stocks.length;
  const topGainer = [...stocks].sort((a,b) => b.change_pct - a.change_pct)[0];
  const topLoser  = [...stocks].sort((a,b) => a.change_pct - b.change_pct)[0];

  document.getElementById('overview-grid').innerHTML = `
    <div class="overview-card">
      <div class="overview-label">Market Sentiment</div>
      <div class="overview-value ${avgChg >= 0 ? 'up' : 'down'}">${avgChg >= 0 ? 'BULLISH' : 'BEARISH'}</div>
      <div class="overview-change ${avgChg >= 0 ? 'up' : 'down'}">Avg ${avgChg >= 0 ? '+' : ''}${avgChg.toFixed(2)}% today</div>
    </div>
    <div class="overview-card">
      <div class="overview-label">Gainers / Losers</div>
      <div class="overview-value up">${gainers}</div>
      <div class="overview-change down">↓ ${losers} stocks falling</div>
    </div>
    <div class="overview-card" onclick="jumpToStock('${topGainer.ticker}')" style="cursor:pointer">
      <div class="overview-label">Top Gainer</div>
      <div class="overview-value up">${topGainer.ticker}</div>
      <div class="overview-change up">▲ +${topGainer.change_pct.toFixed(2)}% · KES ${topGainer.price.toFixed(2)}</div>
    </div>
    <div class="overview-card" onclick="jumpToStock('${topLoser.ticker}')" style="cursor:pointer">
      <div class="overview-label">Top Loser</div>
      <div class="overview-value down">${topLoser.ticker}</div>
      <div class="overview-change down">▼ ${topLoser.change_pct.toFixed(2)}% · KES ${topLoser.price.toFixed(2)}</div>
    </div>
  `;
}

// ── AI Recommendations ────────────────────────────────────────────────────
async function loadRecommendations() {
  const data = await api.getRecommendations();
  const recs = data?.recommendations || MOCK.recommendations;
  const grid = document.getElementById('recs-grid');
  const noSig = document.getElementById('no-signal-notice');

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
    document.getElementById('alerts-text').textContent =
      `${strong.ticker} — ${strong.name} shows a ${strong.signal_strength} BUY signal at ${strong.confidence_pct} confidence. Target: KES ${strong.price_target}`;
    banner.style.display = 'flex';
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
      <div class="rec-target">
        <span class="rec-target-label">Price Target</span>
        <span class="rec-target-value">KES ${r.price_target}</span>
      </div>
    </div>
  `).join('');
}

// ── AI Signal Panel ───────────────────────────────────────────────────────
async function loadSignal(ticker) {
  const card = document.getElementById('signal-card');
  card.innerHTML = '<div class="signal-loading">Analysing ' + ticker + '…</div>';
  const data = await api.getPrediction(ticker);

  if (!data) {
    card.innerHTML = renderSignalCard({
      direction: 'NO_SIGNAL', confidence: 0, confidence_pct: '—',
      signal_strength: 'NONE', reasoning: ['Backend offline — using demo mode'],
      price_target: null, risk_level: 'UNKNOWN', current_price: 0,
    });
    return;
  }
  card.innerHTML = renderSignalCard(data);
}

function renderSignalCard(d) {
  const isSignal = d.direction !== 'NO_SIGNAL';
  return `
    <div class="signal-direction ${d.direction}">${
      d.direction === 'NO_SIGNAL' ? '⏸ No Signal' :
      d.direction === 'BUY'  ? '↑ BUY'  : '↓ SELL'
    }</div>
    <div class="signal-strength-badge ${d.signal_strength}">${d.signal_strength}</div>
    <div class="signal-conf">Confidence: <b>${d.confidence_pct || '—'}</b></div>
    <ul class="signal-reasons">
      ${(d.reasoning || []).map(r => `<li>${r}</li>`).join('')}
    </ul>
    ${isSignal && d.price_target ? `
      <div class="signal-target">
        <div class="signal-target-label">Price Target</div>
        <div class="signal-target-val">KES ${d.price_target}</div>
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
  tbody.innerHTML = stocks.map(s => {
    const up = s.change_pct >= 0;
    return `
      <tr onclick="jumpToStock('${s.ticker}')">
        <td class="table-ticker">${s.ticker}</td>
        <td>${s.name}</td>
        <td>${s.sector}</td>
        <td class="table-price">KES ${s.price.toFixed(2)}</td>
        <td class="${up ? 'change-up' : 'change-down'}">
          ${up ? '▲' : '▼'} ${Math.abs(s.change_pct).toFixed(2)}%
        </td>
        <td class="table-volume">${formatVolume(s.volume)}</td>
        <td><span class="signal-pill NO_SIGNAL" id="sig-${s.ticker}">…</span></td>
      </tr>
    `;
  }).join('');

  // Fetch AI signals for every visible stock (non-blocking)
  stocks.forEach(s => fetchSignalBadge(s.ticker));
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
