<template>
  <div class="chart-wrapper">
    <div ref="chartContainer" class="chart-container"></div>
    <div class="chart-legend" v-if="currentBar">
      <span class="legend-item">O: {{ currentBar.open?.toFixed(2) }}</span>
      <span class="legend-item">H: {{ currentBar.high?.toFixed(2) }}</span>
      <span class="legend-item">L: {{ currentBar.low?.toFixed(2) }}</span>
      <span class="legend-item" :class="currentBar.close >= currentBar.open ? 'positive' : 'negative'">
        C: {{ currentBar.close?.toFixed(2) }}
      </span>
      <span class="legend-item dim">Vol: {{ currentBar.volume?.toLocaleString() }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { createChart, CrosshairMode, ColorType } from 'lightweight-charts'

const props = defineProps({
  bars: { type: Array, default: () => [] },
  decisions: { type: Array, default: () => [] },
  height: { type: Number, default: 400 },
  showVolume: { type: Boolean, default: true },
  showMarkers: { type: Boolean, default: true },
})

const chartContainer = ref(null)
const currentBar = ref(null)
let chart = null
let candleSeries = null
let volumeSeries = null

function initChart() {
  if (!chartContainer.value) return

  chart = createChart(chartContainer.value, {
    width: chartContainer.value.clientWidth,
    height: props.height,
    layout: {
      background: { type: ColorType.Solid, color: '#0a0e17' },
      textColor: '#64748b',
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: 11,
    },
    grid: {
      vertLines: { color: '#1e293b' },
      horzLines: { color: '#1e293b' },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: '#3b82f640', width: 1, style: 2 },
      horzLine: { color: '#3b82f640', width: 1, style: 2 },
    },
    rightPriceScale: {
      borderColor: '#1e293b',
      scaleMargins: { top: 0.1, bottom: props.showVolume ? 0.25 : 0.05 },
    },
    timeScale: {
      borderColor: '#1e293b',
      timeVisible: true,
      secondsVisible: false,
      barSpacing: 12,
    },
  })

  // Candlestick series
  candleSeries = chart.addCandlestickSeries({
    upColor: '#22c55e',
    downColor: '#ef4444',
    borderUpColor: '#22c55e',
    borderDownColor: '#ef4444',
    wickUpColor: '#22c55e80',
    wickDownColor: '#ef444480',
  })

  // Volume series (histogram overlay)
  if (props.showVolume) {
    volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })

    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
      drawTicks: false,
    })
  }

  // Crosshair tracking for legend
  chart.subscribeCrosshairMove((param) => {
    if (param.time && param.seriesData.has(candleSeries)) {
      currentBar.value = param.seriesData.get(candleSeries)
      // Add volume from volume series if available
      if (volumeSeries && param.seriesData.has(volumeSeries)) {
        currentBar.value.volume = param.seriesData.get(volumeSeries).value
      }
    }
  })

  // Resize handler
  const ro = new ResizeObserver(() => {
    if (chart && chartContainer.value) {
      chart.applyOptions({ width: chartContainer.value.clientWidth })
    }
  })
  ro.observe(chartContainer.value)
}

/**
 * Get the time value for a bar.
 * Uses real Unix timestamp (b.time) from Databento ts_event if available,
 * otherwise falls back to bar index with synthetic spacing (60s apart).
 */
function getBarTime(bar, index) {
  // If real timestamp exists and is a reasonable value (> year 2000)
  if (bar.time && bar.time > 946684800) {
    return bar.time
  }
  // Fallback: use synthetic timestamps spaced 60s apart
  // starting from a recent base time so the chart shows readable dates
  const baseTime = Math.floor(Date.now() / 1000) - (props.bars.length * 60)
  return baseTime + (index * 60)
}

function updateData() {
  if (!candleSeries || !props.bars.length) return

  // Build a mapping from bar index → chart time value
  const barTimeMap = {}

  // Convert bars to lightweight-charts format using real timestamps
  const candleData = props.bars.map((b, i) => {
    const time = getBarTime(b, i)
    barTimeMap[b.timestamp !== undefined ? b.timestamp : i] = time
    return {
      time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }
  })
  candleSeries.setData(candleData)

  // Volume
  if (volumeSeries) {
    const volData = props.bars.map((b, i) => ({
      time: getBarTime(b, i),
      value: b.volume,
      color: b.close >= b.open ? '#22c55e30' : '#ef444430',
    }))
    volumeSeries.setData(volData)
  }

  // Decision markers on candlestick chart
  if (props.showMarkers && props.decisions.length) {
    const markers = buildMarkers(props.decisions, props.bars, barTimeMap)
    candleSeries.setMarkers(markers)
  }

  chart.timeScale().fitContent()

  // Set current bar to last bar
  if (props.bars.length) {
    const last = props.bars[props.bars.length - 1]
    currentBar.value = { ...last }
  }
}

function buildMarkers(decisions, bars, barTimeMap) {
  // Group decisions by bar timestamp and summarize
  const byBar = {}
  for (const d of decisions) {
    if (d.action === 'HOLD' || d.agent_type === 'NOISE') continue
    const t = d.timestamp
    if (!byBar[t]) byBar[t] = {
      buys: 0, sells: 0,
      inst_buys: 0, inst_sells: 0,
      buy_qty: 0, sell_qty: 0,
      inst_buy_qty: 0, inst_sell_qty: 0,
      has_exit_long: false, has_exit_short: false,
    }
    const isBuy = d.action.includes('BUY') && !d.action.includes('EXIT')
    const isSell = d.action.includes('SELL') || d.action.includes('EXIT_LONG')
    const isCover = d.action.includes('EXIT_SHORT') || d.action.includes('COVER')
    const isInst = d.agent_type === 'INSTITUTIONAL'
    const qty = d.qty || 1

    if (isBuy || isCover) {
      byBar[t].buys++
      byBar[t].buy_qty += qty
      if (isInst) { byBar[t].inst_buys++; byBar[t].inst_buy_qty += qty }
    }
    if (isSell) {
      byBar[t].sells++
      byBar[t].sell_qty += qty
      if (isInst) { byBar[t].inst_sells++; byBar[t].inst_sell_qty += qty }
    }
    if (d.action.includes('EXIT_LONG')) byBar[t].has_exit_long = true
    if (d.action.includes('EXIT_SHORT') || d.action.includes('COVER')) byBar[t].has_exit_short = true
  }

  const markers = []
  for (const [t, s] of Object.entries(byBar)) {
    const barIdx = parseInt(t)
    if (barIdx >= bars.length) continue

    // Look up the real chart time for this bar index
    const chartTime = barTimeMap[barIdx]
    if (!chartTime) continue

    // Buy marker (below bar)
    if (s.buy_qty > 0) {
      let label = ''
      let color = '#22c55e'
      if (s.inst_buy_qty > 0) {
        label = s.has_exit_short
          ? `INST COVER ${s.inst_buy_qty}`
          : `INST BUY ${s.inst_buy_qty}`
        if (s.buys > s.inst_buys) label += ` +${s.buys - s.inst_buys}`
      } else {
        label = `BUY ×${s.buys}`
        color = '#22c55e80'
      }
      markers.push({
        time: chartTime,
        position: 'belowBar',
        color,
        shape: s.inst_buy_qty > 0 ? 'arrowUp' : 'circle',
        text: label,
      })
    }

    // Sell marker (above bar)
    if (s.sell_qty > 0) {
      let label = ''
      let color = '#ef4444'
      if (s.inst_sell_qty > 0) {
        label = s.has_exit_long
          ? `INST EXIT ${s.inst_sell_qty}`
          : `INST SELL ${s.inst_sell_qty}`
        if (s.sells > s.inst_sells) label += ` +${s.sells - s.inst_sells}`
      } else {
        label = `SELL ×${s.sells}`
        color = '#ef444480'
      }
      markers.push({
        time: chartTime,
        position: 'aboveBar',
        color,
        shape: s.inst_sell_qty > 0 ? 'arrowDown' : 'circle',
        text: label,
      })
    }
  }

  // Sort by time (required by lightweight-charts)
  markers.sort((a, b) => a.time - b.time)
  return markers
}

onMounted(() => {
  nextTick(() => {
    initChart()
    updateData()
  })
})

watch(() => props.bars, () => {
  nextTick(() => updateData())
}, { deep: true })

watch(() => props.decisions, () => {
  nextTick(() => updateData())
}, { deep: true })

onUnmounted(() => {
  if (chart) {
    chart.remove()
    chart = null
  }
})
</script>

<style scoped>
.chart-wrapper {
  position: relative;
}
.chart-container {
  width: 100%;
  border-radius: 6px;
  overflow: hidden;
}
.chart-legend {
  display: flex;
  gap: 16px;
  padding: 8px 4px 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
}
.legend-item.positive { color: var(--green); }
.legend-item.negative { color: var(--red); }
.legend-item.dim { color: var(--text-muted); }
</style>
