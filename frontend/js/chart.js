/**
 * NSE AI Platform — Chart Module
 * TradingView Lightweight Charts candlestick & intraday live area renderer.
 */

let chartInstance = null;
let candleSeries  = null;
let areaSeries    = null;
let volumeSeries  = null;
let currentChartMode = 'candles'; // 'candles' | 'area'

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

  areaSeries = chartInstance.addAreaSeries({
    topColor:       'rgba(0, 229, 160, 0.35)',
    bottomColor:    'rgba(0, 229, 160, 0.02)',
    lineColor:      '#00e5a0',
    lineWidth:      2,
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

  // Switch to candlestick mode
  if (areaSeries) areaSeries.setData([]);
  
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

function loadIntradayData(intradayResponse) {
  if (!areaSeries || !intradayResponse || !intradayResponse.ticks || intradayResponse.ticks.length === 0) return;

  // Switch to area mode for intraday
  if (candleSeries) candleSeries.setData([]);

  const isPositive = (intradayResponse.change >= 0);
  areaSeries.applyOptions({
    topColor:    isPositive ? 'rgba(0, 229, 160, 0.40)' : 'rgba(255, 77, 109, 0.40)',
    bottomColor: isPositive ? 'rgba(0, 229, 160, 0.02)' : 'rgba(255, 77, 109, 0.02)',
    lineColor:   isPositive ? '#00e5a0' : '#ff4d6d',
  });

  const areaData = intradayResponse.ticks.map(t => ({
    time:  t.time,
    value: t.price,
  }));

  const volumeData = intradayResponse.ticks.map(t => ({
    time:  t.time,
    value: t.volume,
    color: isPositive ? 'rgba(0,229,160,0.3)' : 'rgba(255,77,109,0.3)',
  }));

  areaSeries.setData(areaData);
  volumeSeries.setData(volumeData);
  chartInstance.timeScale().fitContent();
}

async function updateChart(ticker, period) {
  if (period === '1d') {
    const cacheKey = `nse_intraday_${ticker}`;
    const cached = localStorage.getItem(cacheKey);
    if (cached) {
      try { loadIntradayData(JSON.parse(cached)); } catch(e) {}
    }

    const data = await api.getIntraday(ticker);
    if (data && data.ticks && data.ticks.length > 0) {
      localStorage.setItem(cacheKey, JSON.stringify(data));
      loadIntradayData(data);
    }
    return;
  }

  const cacheKey = `nse_chart_cache_${ticker}_${period}`;
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
