<template>
  <div class="flow-wrapper">
    <canvas ref="canvas" :height="height"></canvas>
    <div class="flow-legend">
      <span class="flow-leg"><span class="dot" style="background:#3b82f6"></span> Institutional</span>
      <span class="flow-leg"><span class="dot" style="background:#f59e0b"></span> Retail</span>
      <span class="flow-leg"><span class="dot" style="background:#a855f7"></span> Market Maker</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'

const props = defineProps({
  decisions: { type: Array, default: () => [] },
  barCount: { type: Number, default: 0 },
  height: { type: Number, default: 200 },
})

const canvas = ref(null)

function computeFlow() {
  const flow = {}
  for (const d of props.decisions) {
    if (d.agent_type === 'NOISE') continue
    const t = d.timestamp
    if (!flow[t]) flow[t] = {}
    const atype = d.agent_type
    if (!flow[t][atype]) flow[t][atype] = { buy: 0, sell: 0 }

    if (d.action.includes('BUY') && !d.action.includes('EXIT')) {
      flow[t][atype].buy += d.qty || 0
    } else if (d.action.includes('SELL') || d.action.includes('EXIT')) {
      flow[t][atype].sell += d.qty || 0
    }
  }
  return flow
}

function draw() {
  if (!canvas.value) return
  const ctx = canvas.value.getContext('2d')
  const dpr = window.devicePixelRatio || 1
  const W = canvas.value.parentElement.clientWidth
  const H = props.height

  canvas.value.width = W * dpr
  canvas.value.height = H * dpr
  canvas.value.style.width = W + 'px'
  canvas.value.style.height = H + 'px'
  ctx.scale(dpr, dpr)

  const pad = { t: 16, b: 24, l: 50, r: 12 }
  const cw = W - pad.l - pad.r
  const ch = H - pad.t - pad.b
  const mid = pad.t + ch / 2
  const halfH = ch / 2

  const flow = computeFlow()
  const count = props.barCount || Math.max(...Object.keys(flow).map(Number), 0) + 1
  if (count === 0) return

  const barW = cw / count
  const types = [
    { key: 'INSTITUTIONAL', color: 'rgba(59,130,246,0.7)' },
    { key: 'RETAIL', color: 'rgba(245,158,11,0.7)' },
    { key: 'MARKET_MAKER', color: 'rgba(168,85,247,0.7)' },
  ]

  // Find max for scaling
  let maxQ = 1
  for (const t of Object.keys(flow)) {
    let buyTotal = 0, sellTotal = 0
    for (const atype of types) {
      if (flow[t][atype.key]) {
        buyTotal += flow[t][atype.key].buy
        sellTotal += flow[t][atype.key].sell
      }
    }
    maxQ = Math.max(maxQ, buyTotal, sellTotal)
  }

  // Clear
  ctx.clearRect(0, 0, W, H)

  // Center line
  ctx.strokeStyle = '#334155'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(pad.l, mid)
  ctx.lineTo(W - pad.r, mid)
  ctx.stroke()

  // Labels
  ctx.fillStyle = '#64748b'
  ctx.font = '10px JetBrains Mono, monospace'
  ctx.textAlign = 'right'
  ctx.fillText('BUY ↑', pad.l - 6, pad.t + 10)
  ctx.fillText('SELL ↓', pad.l - 6, H - pad.b - 4)

  // Draw stacked bars
  for (let i = 0; i < count; i++) {
    const f = flow[i] || {}
    const x = pad.l + i * barW
    const bw = Math.max(barW * 0.65, 3)

    // Buys (stacked upward)
    let yOff = 0
    for (const atype of types) {
      const val = f[atype.key]?.buy || 0
      const h = (val / maxQ) * halfH
      if (h > 0) {
        ctx.fillStyle = atype.color
        ctx.fillRect(x + (barW - bw) / 2, mid - yOff - h, bw, h)
        yOff += h
      }
    }

    // Sells (stacked downward)
    yOff = 0
    for (const atype of types) {
      const val = f[atype.key]?.sell || 0
      const h = (val / maxQ) * halfH
      if (h > 0) {
        ctx.fillStyle = atype.color
        ctx.fillRect(x + (barW - bw) / 2, mid + yOff, bw, h)
        yOff += h
      }
    }

    // Bar labels
    if (i % Math.max(1, Math.floor(count / 20)) === 0) {
      ctx.fillStyle = '#64748b'
      ctx.font = '9px JetBrains Mono, monospace'
      ctx.textAlign = 'center'
      ctx.fillText(i, x + barW / 2, H - pad.b + 14)
    }
  }
}

onMounted(() => nextTick(() => draw()))
watch(() => [props.decisions, props.barCount], () => nextTick(() => draw()), { deep: true })
</script>

<style scoped>
.flow-wrapper { position: relative; }
canvas { width: 100%; display: block; }
.flow-legend {
  display: flex;
  gap: 16px;
  padding: 8px 4px 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}
.flow-leg { display: flex; align-items: center; gap: 6px; }
.dot { width: 8px; height: 8px; border-radius: 2px; }
</style>
