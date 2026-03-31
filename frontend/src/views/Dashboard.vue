<template>
  <div class="dashboard">
    <!-- Live Session Banner -->
    <div v-if="liveSession" class="live-banner">
      <div class="live-banner-info">
        <span class="live-pulse"></span>
        <span class="live-banner-text">Live session active: {{ liveSession.session_id }}</span>
        <span class="badge badge-green">{{ liveSession.state }}</span>
        <span class="live-banner-bars">{{ liveSession.bars_received || 0 }} bars</span>
      </div>
      <div class="live-banner-actions">
        <button class="btn" @click="$router.push('/live')">View Live →</button>
        <button class="btn btn-danger-sm" @click="stopLiveSession">■ Stop</button>
      </div>
    </div>

    <!-- LEFT: Control Panel -->
    <div class="panel-left">
      <div class="card">
        <div class="card-title">▸ New Simulation</div>

        <!-- Source selector -->
        <div class="field">
          <label class="field-label">Data Source</label>
          <div class="source-tabs">
            <button
              v-for="s in sources" :key="s.id"
              :class="['source-tab', { active: source === s.id }]"
              @click="source = s.id"
            >{{ s.label }}</button>
          </div>
        </div>

        <!-- Databento options -->
        <template v-if="source === 'databento'">
          <div class="field">
            <label class="field-label">Date</label>
            <input class="input" type="date" v-model="dbDate" />
          </div>
          <div class="field-row">
            <div class="field">
              <label class="field-label">Start</label>
              <input class="input" type="time" v-model="dbStart" />
            </div>
            <div class="field">
              <label class="field-label">End</label>
              <input class="input" type="time" v-model="dbEnd" />
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label class="field-label">Seed Bars</label>
              <input class="input" type="number" v-model.number="seedBars" min="5" max="60" />
            </div>
            <div class="field">
              <label class="field-label">Free-Run</label>
              <input class="input" type="number" v-model.number="freeRunBars" min="5" max="30" />
            </div>
          </div>
        </template>

        <!-- Synthetic options -->
        <template v-else>
          <div class="field">
            <label class="field-label">Scenario</label>
            <select class="select" v-model="scenario">
              <option value="scenario_a">A: Bull Trend + Buy Climax</option>
              <option value="scenario_b">B: Gap-Up + Overnight Divergence</option>
            </select>
          </div>
          <div class="field">
            <label class="field-label">Random Seed</label>
            <input class="input" type="number" v-model.number="seed" />
          </div>
        </template>

        <!-- Agent config -->
        <div class="card-title" style="margin-top: 20px">▸ Agent Configuration</div>
        <div class="agent-grid">
          <div class="agent-input" v-for="a in agentTypes" :key="a.key">
            <label class="agent-label">
              <span class="agent-dot" :style="{ background: a.color }"></span>
              {{ a.label }}
            </label>
            <input class="input input-sm" type="number" v-model.number="agents[a.key]" :min="0" />
          </div>
        </div>

        <!-- Cost estimate -->
        <div class="cost-estimate" v-if="estimatedCost">
          <span class="cost-label">Est. cost:</span>
          <span class="cost-value">~${{ estimatedCost }}</span>
        </div>

        <!-- Launch button -->
        <button
          class="btn btn-primary btn-launch"
          :disabled="running"
          @click="launchSimulation"
        >
          <template v-if="running">
            <span class="spinner"></span> Running...
          </template>
          <template v-else>
            ▶ Launch Simulation
          </template>
        </button>

        <!-- Error display -->
        <div class="error-msg" v-if="error">{{ error }}</div>
      </div>
    </div>

    <!-- RIGHT: Results -->
    <div class="panel-right">
      <!-- Active result -->
      <div v-if="activeResult" class="card result-card">
        <div class="result-header">
          <div>
            <div class="card-title">▸ Results: {{ activeResult.sim_id }}</div>
            <div class="result-meta">
              <span class="badge badge-blue">{{ activeResult.source || 'synthetic' }}</span>
              <span class="result-stat">{{ activeResult.total_bars }} bars</span>
              <span class="result-stat">{{ activeResult.total_decisions }} decisions</span>
            </div>
          </div>
          <button class="btn" @click="viewDetail(activeResult.sim_id)">Full Detail →</button>
        </div>

        <!-- P&L Table -->
        <div class="pnl-table">
          <div class="pnl-header">
            <span>Agent Type</span><span>N</span><span>Realized</span><span>W/L</span>
          </div>
          <div
            v-for="(stats, type) in activeResult.pnl_by_type" :key="type"
            class="pnl-row"
          >
            <span class="pnl-type">
              <span class="agent-dot" :style="{ background: agentColor(type) }"></span>
              {{ type }}
            </span>
            <span class="pnl-n">{{ stats.agents }}</span>
            <span :class="['pnl-val', stats.total_realized >= 0 ? 'positive' : 'negative']">
              ${{ formatNum(stats.total_realized) }}
            </span>
            <span class="pnl-wl">{{ stats.winners }}/{{ stats.losers }}</span>
          </div>
        </div>

        <!-- Validation (Databento only) -->
        <div v-if="activeResult.validation?.comparison_available" class="validation-card">
          <div class="card-title">▸ Prediction vs Actual</div>
          <div class="validation-grid">
            <div class="val-item">
              <span class="val-label">Predicted</span>
              <span :class="['val-dir', activeResult.validation.predicted_direction === 'UP' ? 'up' : 'down']">
                {{ activeResult.validation.predicted_direction }}
              </span>
            </div>
            <div class="val-item">
              <span class="val-label">Actual</span>
              <span :class="['val-dir', activeResult.validation.actual_direction === 'UP' ? 'up' : 'down']">
                {{ activeResult.validation.actual_direction }}
              </span>
            </div>
            <div class="val-item">
              <span class="val-label">Correct?</span>
              <span :class="['badge', activeResult.validation.direction_correct ? 'badge-green' : 'badge-red']">
                {{ activeResult.validation.direction_correct ? 'YES' : 'NO' }}
              </span>
            </div>
            <div class="val-item">
              <span class="val-label">Error</span>
              <span class="val-num">{{ activeResult.validation.price_error_points }} pts</span>
            </div>
            <div class="val-item">
              <span class="val-label">Inst. Consensus</span>
              <span class="val-num">{{ activeResult.validation.institutional_consensus }}</span>
            </div>
          </div>
        </div>

        <!-- LLM Stats -->
        <div class="llm-stats" v-if="activeResult.llm_stats">
          <span class="stat-item" v-for="(s, tier) in activeResult.llm_stats" :key="tier">
            <span class="stat-tier">{{ tier }}:</span>
            {{ s.total_calls }} calls · {{ formatNum(s.total_tokens) }} tokens
            <span v-if="s.errors" class="stat-err">· {{ s.errors }} errors</span>
          </span>
        </div>
      </div>

      <!-- Simulation History -->
      <div class="card history-card">
        <div class="card-title">▸ Simulation History</div>
        <div v-if="loading" class="loading">Loading...</div>
        <div v-else-if="simulations.length === 0" class="empty">No simulations yet. Launch one above.</div>
        <div v-else class="history-list">
          <div
            v-for="sim in simulations" :key="sim.sim_id"
            :class="['history-item', { active: activeResult?.sim_id === sim.sim_id }]"
            @click="loadResult(sim.sim_id)"
          >
            <div class="hist-top">
              <span class="hist-id">{{ sim.sim_id }}</span>
              <span class="badge" :class="sim.source === 'databento' ? 'badge-orange' : 'badge-blue'">
                {{ sim.source || 'synthetic' }}
              </span>
            </div>
            <div class="hist-bottom">
              <span>{{ sim.scenario || 'Unknown' }}</span>
              <span v-if="sim.validation?.direction_correct !== undefined">
                <span :class="['badge', sim.validation.direction_correct ? 'badge-green' : 'badge-red']">
                  {{ sim.validation.direction_correct ? '✓ correct' : '✗ wrong' }}
                </span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../services/api.js'

const router = useRouter()

// Live session state
const liveSession = ref(null)
let liveCheckInterval = null

// State
const source = ref('synthetic')
const scenario = ref('scenario_a')
const seed = ref(42)
const dbDate = ref('')
const dbStart = ref('09:30')
const dbEnd = ref('10:30')
const seedBars = ref(15)
const freeRunBars = ref(12)
const agents = ref({ institutional: 3, retail: 5, market_maker: 1, noise: 5 })
const running = ref(false)
const error = ref('')
const activeResult = ref(null)
const simulations = ref([])
const loading = ref(true)

const sources = [
  { id: 'synthetic', label: 'Synthetic' },
  { id: 'databento', label: 'Databento (Real ES)' },
]

const agentTypes = [
  { key: 'institutional', label: 'Institutional', color: '#3b82f6' },
  { key: 'retail', label: 'Retail', color: '#f59e0b' },
  { key: 'market_maker', label: 'Market Maker', color: '#22c55e' },
  { key: 'noise', label: 'Noise', color: '#64748b' },
]

const estimatedCost = computed(() => {
  const total = agents.value.institutional + agents.value.retail +
                agents.value.market_maker + agents.value.noise
  const llmAgents = total - agents.value.noise
  const bars = source.value === 'databento' ? seedBars.value + freeRunBars.value : 27
  const calls = llmAgents * bars
  // Rough estimate: $0.003 per GPT-4o call, $0.0005 per 4o-mini call
  const instCost = (agents.value.institutional + agents.value.market_maker) * bars * 0.003
  const retailCost = agents.value.retail * bars * 0.0005
  return (instCost + retailCost).toFixed(2)
})

function agentColor(type) {
  const colors = { INSTITUTIONAL: '#3b82f6', RETAIL: '#f59e0b', MARKET_MAKER: '#22c55e', NOISE: '#64748b' }
  return colors[type] || '#64748b'
}

function formatNum(n) {
  if (n === undefined || n === null) return '0'
  return Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })
}

async function launchSimulation() {
  running.value = true
  error.value = ''
  activeResult.value = null

  const params = { agents: agents.value }

  if (source.value === 'databento') {
    if (!dbDate.value) { error.value = 'Date is required for Databento'; running.value = false; return }
    // Check for weekend
    const d = new Date(dbDate.value + 'T12:00:00')
    const day = d.getDay()
    if (day === 0 || day === 6) { error.value = 'That\'s a weekend — ES doesn\'t trade on weekends'; running.value = false; return }
    params.source = 'databento'
    params.date = dbDate.value
    params.start_time = dbStart.value
    params.end_time = dbEnd.value
    params.seed_bars = seedBars.value
    params.free_run_bars = freeRunBars.value
  } else {
    params.scenario = scenario.value
    params.seed = seed.value
  }

  try {
    const { data } = await api.createSimulation(params)
    activeResult.value = data
    await loadHistory()
  } catch (e) {
    error.value = e.response?.data?.error || e.message || 'Simulation failed'
  } finally {
    running.value = false
  }
}

async function loadResult(simId) {
  try {
    const { data } = await api.getSimulation(simId)
    // Normalize: live sessions use session_id instead of sim_id
    if (!data.sim_id && data.session_id) data.sim_id = data.session_id
    activeResult.value = data
  } catch {
    error.value = 'Failed to load simulation'
  }
}

async function loadHistory() {
  try {
    const { data } = await api.listSimulations()
    simulations.value = data.simulations || []
  } catch {
    simulations.value = []
  } finally {
    loading.value = false
  }
}

function viewDetail(simId) {
  // For active live sessions, redirect to the live dashboard instead
  if (liveSession.value && liveSession.value.session_id === simId) {
    router.push('/live')
  } else {
    router.push(`/sim/${simId}`)
  }
}

onMounted(() => {
  loadHistory()
  checkLiveSession()
  liveCheckInterval = setInterval(checkLiveSession, 10000)
  // Default date to last weekday
  const today = new Date()
  let d = new Date(today)
  d.setDate(d.getDate() - 1)
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() - 1)
  dbDate.value = d.toISOString().split('T')[0]
})

onUnmounted(() => {
  if (liveCheckInterval) clearInterval(liveCheckInterval)
})

async function checkLiveSession() {
  try {
    const { data } = await api.liveStatus()
    liveSession.value = data.active ? data : null
  } catch {
    liveSession.value = null
  }
}

async function stopLiveSession() {
  try {
    await api.stopLive()
    liveSession.value = null
    await loadHistory()
  } catch (e) {
    error.value = e.response?.data?.error || 'Failed to stop live session'
  }
}
</script>

<style scoped>
.dashboard {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 24px;
  max-width: 1440px;
  margin: 0 auto;
}

.live-banner {
  grid-column: 1 / -1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: rgba(34, 197, 94, 0.08);
  border: 1px solid rgba(34, 197, 94, 0.25);
  border-radius: var(--radius-lg);
  font-family: var(--font-mono);
  font-size: 12px;
}
.live-banner-info { display: flex; align-items: center; gap: 10px; }
.live-banner-text { color: var(--text-primary); font-weight: 500; }
.live-banner-bars { color: var(--text-muted); }
.live-banner-actions { display: flex; gap: 6px; }
.live-pulse {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--green); box-shadow: 0 0 6px var(--green);
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.btn-danger-sm {
  background: var(--red); border-color: var(--red); color: white;
  padding: 6px 12px; font-size: 11px;
}
.btn-danger-sm:hover { background: #dc2626; }

.panel-left { display: flex; flex-direction: column; gap: 16px; }
.panel-right { display: flex; flex-direction: column; gap: 16px; }

.field { margin-bottom: 14px; }
.field-label {
  display: block;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }

.source-tabs { display: flex; gap: 4px; }
.source-tab {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-input);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}
.source-tab.active {
  background: var(--accent-glow);
  border-color: var(--accent);
  color: var(--accent);
}

.agent-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.agent-input { display: flex; flex-direction: column; gap: 4px; }
.agent-label {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-secondary);
}
.agent-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.input-sm { padding: 8px 10px; font-size: 12px; }

.cost-estimate {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; margin-top: 16px;
  background: var(--bg-input); border-radius: var(--radius);
  font-family: var(--font-mono); font-size: 12px;
}
.cost-label { color: var(--text-muted); }
.cost-value { color: var(--orange); font-weight: 600; }

.btn-launch {
  width: 100%; margin-top: 16px; padding: 14px;
  font-size: 14px; font-weight: 600; letter-spacing: 0.5px;
}

.error-msg {
  margin-top: 12px; padding: 10px 14px;
  background: var(--red-dim); border: 1px solid rgba(239,68,68,0.3);
  border-radius: var(--radius); color: var(--red);
  font-family: var(--font-mono); font-size: 12px;
}

.spinner {
  display: inline-block; width: 14px; height: 14px;
  border: 2px solid rgba(255,255,255,0.3); border-top-color: white;
  border-radius: 50%; animation: spin 0.6s linear infinite;
  vertical-align: middle; margin-right: 6px;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Results */
.result-card { }
.result-header { display: flex; justify-content: space-between; align-items: flex-start; }
.result-meta { display: flex; gap: 12px; align-items: center; margin-top: 6px; }
.result-stat { font-family: var(--font-mono); font-size: 12px; color: var(--text-muted); }

.pnl-table { margin-top: 16px; }
.pnl-header, .pnl-row {
  display: grid; grid-template-columns: 2fr 0.5fr 1.5fr 0.8fr;
  gap: 8px; padding: 8px 0; align-items: center;
  font-family: var(--font-mono); font-size: 13px;
}
.pnl-header {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;
  color: var(--text-muted); border-bottom: 1px solid var(--border);
}
.pnl-row { border-bottom: 1px solid var(--border); }
.pnl-row:last-child { border-bottom: none; }
.pnl-type { display: flex; align-items: center; gap: 8px; color: var(--text-primary); }
.pnl-n { color: var(--text-secondary); text-align: center; }
.pnl-val { font-weight: 600; }
.pnl-val.positive { color: var(--green); }
.pnl-val.negative { color: var(--red); }
.pnl-wl { color: var(--text-secondary); text-align: center; }

/* Validation */
.validation-card {
  margin-top: 16px; padding: 16px;
  background: var(--bg-input); border-radius: var(--radius);
}
.validation-grid {
  display: grid; grid-template-columns: repeat(5, 1fr);
  gap: 12px; text-align: center;
}
.val-item { display: flex; flex-direction: column; gap: 4px; }
.val-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); }
.val-dir { font-family: var(--font-mono); font-size: 16px; font-weight: 700; }
.val-dir.up { color: var(--green); }
.val-dir.down { color: var(--red); }
.val-num { font-family: var(--font-mono); font-size: 14px; color: var(--text-primary); }

/* LLM Stats */
.llm-stats {
  display: flex; flex-wrap: wrap; gap: 16px; margin-top: 16px;
  padding-top: 12px; border-top: 1px solid var(--border);
}
.stat-item {
  font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);
}
.stat-tier { color: var(--text-secondary); font-weight: 600; }
.stat-err { color: var(--red); }

/* History */
.history-card { }
.history-list { display: flex; flex-direction: column; gap: 4px; }
.history-item {
  padding: 12px 14px; border-radius: var(--radius);
  background: var(--bg-input); cursor: pointer;
  border: 1px solid transparent; transition: all 0.15s;
}
.history-item:hover { border-color: var(--border); }
.history-item.active { border-color: var(--accent); background: var(--accent-glow); }
.hist-top {
  display: flex; justify-content: space-between; align-items: center;
}
.hist-id {
  font-family: var(--font-mono); font-size: 12px; font-weight: 500;
  color: var(--text-primary);
}
.hist-bottom {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 4px; font-size: 12px; color: var(--text-muted);
}

.loading, .empty {
  padding: 24px; text-align: center;
  font-family: var(--font-mono); font-size: 13px; color: var(--text-muted);
}

@media (max-width: 900px) {
  .dashboard { grid-template-columns: 1fr; }
}
</style>
