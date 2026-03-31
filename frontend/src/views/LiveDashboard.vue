<template>
  <div class="live-dash">
    <!-- Header -->
    <div class="live-header">
      <div>
        <h2 class="live-title">◈ Live Simulation</h2>
        <div class="live-meta">
          <span class="badge" :class="stateBadge">{{ sessionState }}</span>
          <span v-if="sessionId" class="session-id">{{ sessionId }}</span>
          <span v-if="barsReceived" class="bar-counter">{{ barsReceived }} bars</span>
        </div>
      </div>
      <div class="live-controls">
        <button class="btn btn-primary" @click="startSession" :disabled="isActive" v-if="!isActive">
          ▶ Start Live
        </button>
        <button class="btn btn-danger" @click="stopSession" v-if="isActive">
          ■ Stop
        </button>
        <button class="btn" @click="$router.push('/')">← Dashboard</button>
      </div>
    </div>

    <!-- Config (shown when not active) -->
    <div class="card config-card" v-if="!isActive && !finalResults">
      <div class="card-title">▸ Session Configuration</div>
      <div class="config-grid">
        <div class="field">
          <label class="field-label">Seed Bars</label>
          <input class="input input-sm" type="number" v-model.number="seedBars" min="3" max="15" />
        </div>
        <div class="field">
          <label class="field-label">Max Bars</label>
          <input class="input input-sm" type="number" v-model.number="maxBars" min="10" max="120" />
        </div>
        <div class="field">
          <label class="field-label">Institutional</label>
          <input class="input input-sm" type="number" v-model.number="agents.institutional" min="1" max="7" />
        </div>
        <div class="field">
          <label class="field-label">Retail</label>
          <input class="input input-sm" type="number" v-model.number="agents.retail" min="1" max="20" />
        </div>
      </div>
      <div class="config-note">
        ES futures must be trading (CME Globex: Sun 5pm – Fri 4pm CT).
        Estimated cost: ~${{ estCost }}/bar in LLM tokens.
      </div>
    </div>

    <!-- Live Charts -->
    <div v-if="bars.length > 0" class="charts-section">
      <div class="card">
        <div class="card-title">▸ ES Futures — Live Price Action</div>
        <CandlestickChart
          :bars="bars"
          :decisions="allDecisions"
          :height="360"
          :showVolume="true"
          :showMarkers="true"
        />
      </div>

      <div class="card" style="margin-top: 16px">
        <div class="card-title">▸ Agent Order Flow</div>
        <AgentFlowChart
          :decisions="allDecisions"
          :barCount="bars.length"
          :height="180"
        />
      </div>
    </div>

    <!-- Seeding indicator -->
    <div v-if="sessionState === 'waiting_for_data'" class="card seeding-card">
      <div class="seeding-text">
        <div class="spinner-lg"></div>
        <div>
          <div class="seeding-title">Waiting for market data...</div>
          <div class="seeding-sub">
            Databento Live connected. Collecting seed bars: {{ barsReceived }} / {{ seedBars }}
          </div>
        </div>
      </div>
    </div>

    <!-- Live P&L -->
    <div v-if="pnl && Object.keys(pnl).length" class="card" style="margin-top: 16px">
      <div class="card-title">▸ Live P&L</div>
      <div class="pnl-live-grid">
        <div v-for="(stats, type) in pnl" :key="type" class="pnl-live-item">
          <span class="pnl-live-type">
            <span class="agent-dot" :style="{ background: agentColor(type) }"></span>
            {{ type }}
          </span>
          <span :class="['pnl-live-val', (stats.total_realized + stats.total_unrealized) >= 0 ? 'positive' : 'negative']">
            ${{ formatNum(stats.total_realized + stats.total_unrealized) }}
          </span>
          <span class="pnl-live-detail">
            R: ${{ formatNum(stats.total_realized) }} / U: ${{ formatNum(stats.total_unrealized) }}
          </span>
        </div>
      </div>
    </div>

    <!-- Live Decision Feed -->
    <div v-if="recentDecisions.length" class="card" style="margin-top: 16px">
      <div class="card-title">▸ Recent Decisions (last 5 bars)</div>
      <div class="live-decisions">
        <div v-for="d in recentDecisions" :key="`${d.agent_id}-${d.timestamp}`"
             class="live-dec-item-wrap"
             @click="toggleDecision(`${d.agent_id}-${d.timestamp}`)">
          <div class="live-dec-item">
            <span class="dec-bar">Bar {{ d.timestamp }}</span>
            <span class="dec-agent">
              <span class="agent-dot" :style="{ background: agentColor(d.agent_type) }"></span>
              {{ d.agent_id }}
            </span>
            <span :class="['dec-action', actionClass(d.action)]">{{ d.action }}</span>
            <span v-if="d.price" class="dec-price">@{{ d.price.toFixed(2) }}</span>
            <span v-if="d.qty" class="dec-qty">×{{ d.qty }}</span>
            <span class="dec-reasoning-short" v-if="!expandedDecisions.has(`${d.agent_id}-${d.timestamp}`)">
              {{ d.reasoning?.substring(0, 80) }}{{ (d.reasoning?.length || 0) > 80 ? '…' : '' }}
            </span>
            <span class="dec-expand-icon">{{ expandedDecisions.has(`${d.agent_id}-${d.timestamp}`) ? '▾' : '▸' }}</span>
          </div>
          <div v-if="expandedDecisions.has(`${d.agent_id}-${d.timestamp}`)" class="dec-expanded">
            <div class="dec-reasoning-full">{{ d.reasoning }}</div>
            <div class="dec-details">
              <span v-if="d.current_price" class="dec-detail">Market: <em>{{ d.current_price.toFixed(2) }}</em></span>
              <span v-if="d.conviction" class="dec-detail">Conviction: <em>{{ (d.conviction * 100).toFixed(0) }}%</em></span>
              <span v-if="d.market_read" class="dec-detail">Read: <em>{{ d.market_read }}</em></span>
              <span v-if="d.position_side && d.position_side !== 'FLAT'" class="dec-detail">
                Position: <em>{{ d.position_side }} ×{{ d.position_size }}</em>
              </span>
              <span v-if="d.realized_pnl" :class="['dec-detail', d.realized_pnl >= 0 ? 'positive' : 'negative']">
                R P&L: <em>${{ d.realized_pnl.toFixed(0) }}</em>
              </span>
              <span v-if="d.unrealized_pnl" :class="['dec-detail', d.unrealized_pnl >= 0 ? 'positive' : 'negative']">
                U P&L: <em>${{ d.unrealized_pnl.toFixed(0) }}</em>
              </span>
              <span v-if="d.llm_latency_ms" class="dec-detail dim">Latency: <em>{{ d.llm_latency_ms.toFixed(0) }}ms</em></span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Final Results (after stop) -->
    <div v-if="finalResults" class="card" style="margin-top: 16px">
      <div class="card-title">▸ Session Complete</div>
      <div class="final-stats">
        <span>Duration: {{ finalResults.duration_seconds?.toFixed(0) }}s</span>
        <span>Bars: {{ finalResults.total_bars }}</span>
        <span>Decisions: {{ finalResults.total_decisions }}</span>
      </div>
    </div>

    <!-- Error -->
    <div v-if="error" class="error-msg" style="margin-top: 16px">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api from '../services/api.js'
import CandlestickChart from '../components/CandlestickChart.vue'
import AgentFlowChart from '../components/AgentFlowChart.vue'

// Config
const seedBars = ref(5)
const maxBars = ref(60)
const agents = ref({ institutional: 3, retail: 5, market_maker: 1, noise: 5 })

// Session state
const sessionId = ref(null)
const sessionState = ref('idle')
const barsReceived = ref(0)
const error = ref('')
const finalResults = ref(null)

// Live data
const bars = ref([])
const allDecisions = ref([])
const pnl = ref({})
const expandedDecisions = ref(new Set())
let eventSource = null
let pollInterval = null

function toggleDecision(key) {
  const next = new Set(expandedDecisions.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedDecisions.value = next
}

const isActive = computed(() =>
  ['running', 'waiting_for_data', 'initializing'].includes(sessionState.value)
)

const stateBadge = computed(() => {
  const map = {
    idle: 'badge-blue',
    initializing: 'badge-orange',
    waiting_for_data: 'badge-orange',
    running: 'badge-green',
    stopped: 'badge-blue',
    error: 'badge-red',
  }
  return map[sessionState.value] || 'badge-blue'
})

const estCost = computed(() => {
  const instCost = (agents.value.institutional + agents.value.market_maker) * 0.003
  const retailCost = agents.value.retail * 0.0005
  return (instCost + retailCost).toFixed(3)
})

const recentDecisions = computed(() => {
  if (!allDecisions.value.length) return []
  const maxBar = Math.max(...allDecisions.value.map(d => d.timestamp))
  return allDecisions.value
    .filter(d => d.timestamp >= maxBar - 4 && d.action !== 'HOLD' && d.agent_type !== 'NOISE')
    .sort((a, b) => b.timestamp - a.timestamp || (a.agent_id || '').localeCompare(b.agent_id || ''))
    .slice(-30)
})

function agentColor(type) {
  const c = { INSTITUTIONAL: '#3b82f6', RETAIL: '#f59e0b', MARKET_MAKER: '#22c55e', NOISE: '#64748b' }
  return c[type] || '#64748b'
}

function actionClass(action) {
  if (action.includes('BUY')) return 'buy'
  if (action.includes('SELL') || action.includes('EXIT_SHORT')) return 'sell'
  if (action.includes('EXIT')) return 'exit'
  return ''
}

function formatNum(n) {
  if (n === undefined || n === null) return '0'
  return Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })
}

async function startSession() {
  error.value = ''
  finalResults.value = null
  bars.value = []
  allDecisions.value = []
  pnl.value = {}
  seenBarTimestamps.clear()
  seenDecisionKeys.clear()

  try {
    const { data } = await api.startLive({
      seed_bars: seedBars.value,
      max_bars: maxBars.value,
      agents: agents.value,
    })
    sessionId.value = data.session_id
    sessionState.value = data.state || 'waiting_for_data'

    // Connect SSE stream
    connectSSE(data.session_id)

    // Also start polling as fallback
    startPolling()
  } catch (e) {
    // Handle 409 — session already running: recover it instead of showing error
    if (e.response?.status === 409 && e.response?.data?.session_id) {
      sessionId.value = e.response.data.session_id
      sessionState.value = e.response.data.state || 'running'
      connectSSE(e.response.data.session_id)
      startPolling()
    } else {
      error.value = e.response?.data?.error || e.message || 'Failed to start'
    }
  }
}

async function stopSession() {
  try {
    const { data } = await api.stopLive()
    finalResults.value = data.results || data
    sessionState.value = 'stopped'
  } catch (e) {
    error.value = e.response?.data?.error || e.message || 'Failed to stop'
  }
  disconnectSSE()
  stopPolling()
}

function connectSSE(sid) {
  disconnectSSE()
  try {
    eventSource = new EventSource(`/ws/live/${sid}`)
    eventSource.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        handleEvent(msg)
      } catch (e) {
        console.error('SSE parse error:', e)
      }
    }
    eventSource.onerror = () => {
      console.warn('SSE connection lost, falling back to polling')
      disconnectSSE()
    }
  } catch (e) {
    console.warn('SSE not available, using polling')
  }
}

function disconnectSSE() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

function startPolling() {
  stopPolling()
  let afterIdx = 0
  pollInterval = setInterval(async () => {
    if (!isActive.value) { stopPolling(); return }
    try {
      const { data } = await api.pollLiveEvents(afterIdx)
      if (data.events) {
        for (const event of data.events) {
          handleEvent(event)
        }
        afterIdx += data.events.length
      }
      if (!data.active) {
        sessionState.value = 'stopped'
        stopPolling()
      }
    } catch (e) {
      // Ignore polling errors
    }
  }, 2000)
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

// Track seen events to prevent SSE + polling duplication
const seenBarTimestamps = new Set()
const seenDecisionKeys = new Set()

function handleEvent(msg) {
  const { type, data } = msg

  if (type === 'session_started') {
    sessionState.value = 'waiting_for_data'
  } else if (type === 'seeding') {
    barsReceived.value = data.bars_received
    sessionState.value = 'waiting_for_data'
  } else if (type === 'bar') {
    // Deduplicate: skip if we already have this bar
    const barKey = data.time || data.timestamp
    if (seenBarTimestamps.has(barKey)) return
    seenBarTimestamps.add(barKey)
    bars.value = [...bars.value, data]
    barsReceived.value = bars.value.length
    sessionState.value = 'running'
  } else if (type === 'decisions') {
    if (data.decisions) {
      // Deduplicate decisions by agent_id + timestamp
      const newDecs = data.decisions.filter(d => {
        const key = `${d.agent_id}_${d.timestamp}`
        if (seenDecisionKeys.has(key)) return false
        seenDecisionKeys.add(key)
        return true
      })
      if (newDecs.length) {
        allDecisions.value = [...allDecisions.value, ...newDecs]
      }
    }
  } else if (type === 'pnl') {
    pnl.value = data
  } else if (type === 'session_stopped') {
    finalResults.value = data
    sessionState.value = 'stopped'
    disconnectSSE()
    stopPolling()
  } else if (type === 'session_ended') {
    sessionState.value = 'stopped'
    disconnectSSE()
    stopPolling()
  } else if (type === 'error') {
    error.value = data.message || 'Unknown error'
    sessionState.value = 'error'
  }
}

// Check for existing active session on mount (recovery after page refresh)
async function checkExistingSession() {
  try {
    const { data } = await api.liveStatus()
    if (data.active && data.session_id) {
      sessionId.value = data.session_id
      sessionState.value = data.state || 'running'
      barsReceived.value = data.bars_received || data.total_bars || 0
      // Reconnect SSE + polling to pick up where we left off
      connectSSE(data.session_id)
      startPolling()
    }
  } catch (e) {
    // No active session, that's fine
  }
}

onMounted(() => {
  checkExistingSession()
})

onUnmounted(() => {
  disconnectSSE()
  stopPolling()
})
</script>

<style scoped>
.live-dash { max-width: 1200px; margin: 0 auto; }

.live-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 20px;
}
.live-title {
  font-family: var(--font-mono); font-size: 18px; font-weight: 600;
  color: var(--accent);
}
.live-meta {
  display: flex; gap: 10px; align-items: center; margin-top: 4px;
  font-family: var(--font-mono); font-size: 12px; color: var(--text-muted);
}
.session-id { color: var(--text-secondary); }
.bar-counter { color: var(--text-primary); font-weight: 500; }

.live-controls { display: flex; gap: 8px; }

.btn-danger {
  background: var(--red); border-color: var(--red); color: white;
}
.btn-danger:hover { background: #dc2626; }

/* Config */
.config-card { margin-bottom: 20px; }
.config-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
}
.field-label {
  display: block; font-family: var(--font-mono); font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted);
  margin-bottom: 4px;
}
.input-sm { padding: 8px 10px; font-size: 12px; }
.config-note {
  margin-top: 12px; font-size: 12px; color: var(--text-muted);
  font-family: var(--font-mono);
}

/* Charts */
.charts-section { margin-top: 16px; }

/* Seeding */
.seeding-card { margin-top: 16px; }
.seeding-text { display: flex; gap: 16px; align-items: center; }
.seeding-title { font-family: var(--font-mono); font-size: 14px; font-weight: 500; }
.seeding-sub { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
.spinner-lg {
  width: 24px; height: 24px; border: 3px solid var(--border);
  border-top-color: var(--accent); border-radius: 50%;
  animation: spin 0.8s linear infinite; flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* P&L */
.pnl-live-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
}
.pnl-live-item {
  display: flex; flex-direction: column; gap: 4px;
  padding: 12px; background: var(--bg-input); border-radius: var(--radius);
}
.pnl-live-type {
  display: flex; align-items: center; gap: 6px;
  font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);
}
.agent-dot { width: 8px; height: 8px; border-radius: 50%; }
.pnl-live-val {
  font-family: var(--font-mono); font-size: 18px; font-weight: 700;
}
.pnl-live-detail {
  font-family: var(--font-mono); font-size: 10px; color: var(--text-muted);
}
.positive { color: var(--green); }
.negative { color: var(--red); }

/* Decisions */
.live-decisions {
  max-height: 400px; overflow-y: auto; display: flex; flex-direction: column; gap: 3px;
}
.live-dec-item-wrap {
  background: var(--bg-input); border-radius: 4px;
  cursor: pointer; transition: background 0.15s;
}
.live-dec-item-wrap:hover { background: #1a2332; }
.live-dec-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 10px;
  font-family: var(--font-mono); font-size: 11px;
}
.dec-bar { color: var(--text-muted); width: 50px; flex-shrink: 0; }
.dec-agent { display: flex; align-items: center; gap: 4px; color: var(--text-secondary); width: 80px; flex-shrink: 0; }
.dec-action { font-weight: 600; flex-shrink: 0; }
.dec-action.buy { color: var(--green); }
.dec-action.sell { color: var(--red); }
.dec-action.exit { color: var(--orange); }
.dec-price {
  color: var(--accent); font-size: 10px; flex-shrink: 0;
}
.dec-qty { color: var(--text-secondary); flex-shrink: 0; }
.dec-reasoning-short {
  flex: 1; color: var(--text-muted); font-size: 10px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.dec-expand-icon {
  color: var(--text-muted); font-size: 9px; flex-shrink: 0; width: 12px; text-align: center;
}
.dec-expanded {
  padding: 6px 10px 10px 60px;
  border-top: 1px solid #1e293b;
}
.dec-reasoning-full {
  color: var(--text-secondary); font-size: 11px; font-family: var(--font-mono);
  line-height: 1.5; white-space: pre-wrap; word-break: break-word;
  margin-bottom: 8px;
}
.dec-details {
  display: flex; flex-wrap: wrap; gap: 12px;
  font-family: var(--font-mono); font-size: 10px; color: var(--text-muted);
}
.dec-detail em {
  font-style: normal; color: var(--text-secondary); font-weight: 500;
}
.dec-detail.dim em { color: var(--text-muted); }

/* Final */
.final-stats {
  display: flex; gap: 24px; font-family: var(--font-mono); font-size: 13px;
  color: var(--text-secondary);
}

.error-msg {
  padding: 10px 14px; background: var(--red-dim);
  border: 1px solid rgba(239,68,68,0.3); border-radius: var(--radius);
  color: var(--red); font-family: var(--font-mono); font-size: 12px;
}

@media (max-width: 900px) {
  .config-grid { grid-template-columns: 1fr 1fr; }
  .pnl-live-grid { grid-template-columns: 1fr 1fr; }
}
</style>
