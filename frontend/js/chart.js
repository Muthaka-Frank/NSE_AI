/**
 * NSE AI Platform — Chart Module
 * TradingView Lightweight Charts candlestick renderer.
 */

let chartInstance = null;
let candleSeries  = null;
let volumeSeries  = null;

function initChart(containerId = 'main-chart') {
  const container = document.getElementById(containerId);
  if (!container) return;

  chartInstance = LightweightCharts.createChart(container, {
    layout: {
      background:  { type: 'solid', color: '#111c2b' },
      textColor:   '#7a9abf',
    },
    grid: {
      vertLines:   { color: '#1e2f45' },
      horzLines:   { color: '#1e2f45' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: '#00e5a050', labelBackgroundColor: '#0e1520' },
      horzLine: { color: '#00e5a050', labelBackgroundColor: '#0e1520' },
    },
    rightPriceScale: {
      borderColor: '#1e2f45',
      scaleMargins: { top: 0.1, bottom: 0.25 },
    },
    timeScale: {
      borderColor:     '#1e2f45',
      timeVisible:     true,
      secondsVisible:  false,
    },
    handleScroll:  true,
    handleScale:   true,
  });

  candleSeries = chartInstance.addCandlestickSeries({
    upColor:        '#00e5a0',
    downColor:      '#ff4d6d',
    borderUpColor:  '#00e5a0',
    borderDownColor:'#ff4d6d',
    wickUpColor:    '#00b87f',
    wickDownColor:  '#cc3d57',
  });

  volumeSeries = chartInstance.addHistogramSeries({
    color:       '#243650',
    priceFormat: { type: 'volume' },
    priceScaleId:'',
    scaleMargins:{ top: 0.8, bottom: 0 },
  });

  // Responsive resize
  const ro = new ResizeObserver(() => {
    if (chartInstance && container) {
      chartInstance.applyOptions({ width: container.clientWidth });
    }
  });
  ro.observe(container);

  return chartInstance;
}

function loadChartData(history) {
  if (!candleSeries || !history || history.length === 0) return;

  const candles = history.map(d => ({
    time:  d.date,
    open:  d.open,
    high:  d.high,
    low:   d.low,
    close: d.close,
  }));

  const volumes = history.map(d => ({
    time:  d.date,
    value: d.volume,
    color: d.close >= d.open ? 'rgba(0,229,160,0.25)' : 'rgba(255,77,109,0.25)',
  }));

  candleSeries.setData(candles);
  volumeSeries.setData(volumes);
  chartInstance.timeScale().fitContent();
}

async function updateChart(ticker, period) {
  const cacheKey = `nse_chart_cache_${ticker}_${period}`;
  
  // Try rendering cached history data first if available
  const cachedData = localStorage.getItem(cacheKey);
  if (cachedData) {
    try {
      loadChartData(JSON.parse(cachedData));
    } catch(e) {
      console.warn("Cached chart load failed", e);
    }
  }

  let data = await api.getHistory(ticker, period);
  if (!data || !data.data) {
    if (!cachedData) {
      data = { data: MOCK.generateHistory(ticker, period === '1mo' ? 30 : period === '3mo' ? 90 : period === '6mo' ? 180 : 365) };
      loadChartData(data.data);
    }
    return;
  }
  
  localStorage.setItem(cacheKey, JSON.stringify(data.data));
  loadChartData(data.data);
}
