<template>
  <div class="sim-detail" v-if="result">
    <div class="detail-header">
      <button class="btn" @click="$router.push('/')">← Back</button>
      <div>
        <h2 class="detail-title">{{ result.scenario }}</h2>
        <div class="detail-meta">
          <span class="badge badge-blue">{{ result.source || 'synthetic' }}</span>
          <span class="detail-id">{{ id }}</span>
          <span>{{ result.total_bars }} bars · {{ result.total_decisions }} decisions</span>
        </div>
      </div>
    </div>

    <div class="detail-grid">
      <!-- P&L Summary -->
      <div class="card">
        <div class="card-title">▸ P&L Summary</div>
        <div class="pnl-bars">
          <div v-for="(stats, type) in result.pnl_by_type" :key="type" class="pnl-bar-row">
            <span class="pnl-bar-label">
              <span class="agent-dot" :style="{ background: agentColor(type) }"></span>
              {{ type }}
            </span>
            <div class="pnl-bar-track">
              <div
                class="pnl-bar-fill"
                :style="{
                  width: barWidth(stats.total_realized) + '%',
                  background: stats.total_realized >= 0 ? 'var(--green)' : 'var(--red)',
                }"
              ></div>
            </div>
            <span :class="['pnl-bar-value', stats.total_realized >= 0 ? 'positive' : 'negative']">
              ${{ formatNum(stats.total_realized) }}
            </span>
          </div>
        </div>
      </div>

      <!-- Validation -->
      <div class="card" v-if="result.validation?.comparison_available">
        <div class="card-title">▸ Prediction vs Actual</div>
        <div class="val-big">
          <div class="val-block">
            <span class="val-label">Predicted</span>
            <span :class="['val-arrow', result.validation.predicted_direction === 'UP' ? 'up' : 'down']">
              {{ result.validation.predicted_direction === 'UP' ? '▲' : '▼' }}
            </span>
          </div>
          <div class="val-block">
            <span class="val-label">Actual</span>
            <span :class="['val-arrow', result.validation.actual_direction === 'UP' ? 'up' : 'down']">
              {{ result.validation.actual_direction === 'UP' ? '▲' : '▼' }}
            </span>
          </div>
          <div class="val-block">
            <span class="val-label">Result</span>
            <span :class="['val-result', result.validation.direction_correct ? 'correct' : 'wrong']">
              {{ result.validation.direction_correct ? '✓ CORRECT' : '✗ WRONG' }}
            </span>
          </div>
          <div class="val-block">
            <span class="val-label">Error</span>
            <span class="val-num-big">{{ result.validation.price_error_points }} pts</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Price Action Chart -->
    <div class="card" style="margin-top: 16px; margin-bottom: 16px" v-if="bars.length">
      <div class="card-title">▸ Price Action</div>
      <CandlestickChart
        :bars="bars"
        :decisions="allDecisions"
        :height="380"
        :showVolume="true"
        :showMarkers="true"
      />
    </div>

    <!-- Agent Flow -->
    <div class="card" style="margin-bottom: 16px" v-if="allDecisions.length">
      <div class="card-title">▸ Agent Order Flow — Buy ↑ vs Sell ↓ by Type</div>
      <AgentFlowChart
        :decisions="allDecisions"
        :barCount="bars.length"
        :height="200"
      />
    </div>

    <!-- Decision Feed -->
    <div class="card decisions-card">
      <div class="decisions-header">
        <div class="card-title">▸ Agent Decisions</div>
        <div class="decision-filters">
          <button
            v-for="t in filterTypes" :key="t.key"
            :class="['btn', { 'btn-primary': agentFilter === t.key }]"
            @click="setFilter(t.key)"
            style="padding: 6px 12px; font-size: 11px;"
          >{{ t.label }}</button>
        </div>
      </div>

      <div v-if="loadingDecisions" class="loading">Loading decisions...</div>
      <div v-else class="decision-list">
        <div
          v-for="d in filteredDecisions" :key="`${d.agent_id}-${d.timestamp}`"
          class="decision-item"
          :class="{ hold: d.action === 'HOLD' }"
        >
          <div class="dec-header">
            <span class="dec-bar">Bar {{ d.timestamp }}</span>
            <span class="dec-agent">
              <span class="agent-dot" :style="{ background: agentColor(d.agent_type) }"></span>
              {{ d.agent_id }}
            </span>
            <span :class="['dec-action', actionClass(d.action)]">{{ d.action }}</span>
            <span v-if="d.qty" class="dec-qty">×{{ d.qty }}</span>
            <span v-if="d.conviction" class="dec-conviction">
              {{ Math.round(d.conviction * 100) }}%
            </span>
          </div>
          <div class="dec-reasoning" v-if="d.reasoning && d.action !== 'HOLD'">
            {{ d.reasoning }}
          </div>
          <div class="dec-footer" v-if="d.action !== 'HOLD'">
            <span>{{ d.market_read }}</span>
            <span>pos: {{ d.position_side }}×{{ d.position_size }}</span>
            <span :class="d.realized_pnl >= 0 ? 'positive' : 'negative'">
              PnL: ${{ formatNum(d.realized_pnl) }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div v-else class="loading" style="padding: 60px; text-align: center;">
    Loading simulation...
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../services/api.js'
import CandlestickChart from '../components/CandlestickChart.vue'
import AgentFlowChart from '../components/AgentFlowChart.vue'

const router = useRouter()
const props = defineProps({ id: String })

const result = ref(null)
const decisions = ref([])
const loadingDecisions = ref(true)
const agentFilter = ref('ALL')
const bars = ref([])
const allDecisions = ref([])  // All decisions (for charts), separate from filtered

const filterTypes = [
  { key: 'ALL', label: 'All' },
  { key: 'INSTITUTIONAL', label: 'Institutional' },
  { key: 'RETAIL', label: 'Retail' },
  { key: 'MARKET_MAKER', label: 'Market Maker' },
  { key: 'ACTIVE', label: 'Active Only' },
]

const filteredDecisions = computed(() => {
  let d = decisions.value
  if (agentFilter.value === 'ACTIVE') {
    d = d.filter(x => x.action !== 'HOLD')
  } else if (agentFilter.value !== 'ALL') {
    d = d.filter(x => x.agent_type === agentFilter.value)
  }
  return d.slice(0, 500) // Cap for performance
})

function agentColor(type) {
  const colors = { INSTITUTIONAL: '#3b82f6', RETAIL: '#f59e0b', MARKET_MAKER: '#22c55e', NOISE: '#64748b' }
  return colors[type] || '#64748b'
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

function barWidth(val) {
  if (!result.value) return 0
  const vals = Object.values(result.value.pnl_by_type).map(s => Math.abs(s.total_realized))
  const max = Math.max(...vals, 1)
  return Math.min(100, (Math.abs(val) / max) * 100)
}

async function setFilter(key) {
  agentFilter.value = key
  loadingDecisions.value = true
  try {
    const params = {}
    if (key !== 'ALL' && key !== 'ACTIVE') params.agentType = key
    const { data } = await api.getDecisions(props.id, params)
    decisions.value = data.decisions || []
  } catch (e) {
    decisions.value = []
  } finally {
    loadingDecisions.value = false
  }
}

onMounted(async () => {
  // If this is a live session ID and a live session is currently running, redirect to /live
  if (props.id?.startsWith('live_')) {
    try {
      const { data: status } = await api.liveStatus()
      if (status.active && status.session_id === props.id) {
        router.replace('/live')
        return
      }
    } catch {
      // No live session running, continue loading normally
    }
  }

  try {
    const { data } = await api.getSimulation(props.id)
    result.value = data
    bars.value = data.bars || []
    allDecisions.value = data.decisions || []
  } catch {
    result.value = null
  }
  await setFilter('ACTIVE')
})
</script>

<style scoped>
.sim-detail { max-width: 1200px; margin: 0 auto; }

.detail-header {
  display: flex; gap: 16px; align-items: flex-start; margin-bottom: 24px;
}
.detail-title {
  font-family: var(--font-mono); font-size: 16px; font-weight: 600;
}
.detail-meta {
  display: flex; gap: 12px; align-items: center; margin-top: 4px;
  font-family: var(--font-mono); font-size: 12px; color: var(--text-muted);
}
.detail-id { color: var(--text-secondary); }

.detail-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;
}

/* P&L Bars */
.pnl-bars { display: flex; flex-direction: column; gap: 12px; }
.pnl-bar-row { display: flex; align-items: center; gap: 12px; }
.pnl-bar-label {
  display: flex; align-items: center; gap: 6px;
  font-family: var(--font-mono); font-size: 12px; color: var(--text-secondary);
  width: 130px; flex-shrink: 0;
}
.agent-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.pnl-bar-track {
  flex: 1; height: 20px; background: var(--bg-input);
  border-radius: 4px; overflow: hidden;
}
.pnl-bar-fill {
  height: 100%; border-radius: 4px; transition: width 0.5s ease;
  min-width: 2px;
}
.pnl-bar-value {
  font-family: var(--font-mono); font-size: 13px; font-weight: 600;
  width: 90px; text-align: right; flex-shrink: 0;
}
.positive { color: var(--green); }
.negative { color: var(--red); }

/* Validation */
.val-big {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 16px; text-align: center;
}
.val-block { display: flex; flex-direction: column; gap: 8px; }
.val-label {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;
  color: var(--text-muted);
}
.val-arrow { font-size: 32px; }
.val-arrow.up { color: var(--green); }
.val-arrow.down { color: var(--red); }
.val-result { font-family: var(--font-mono); font-size: 16px; font-weight: 700; }
.val-result.correct { color: var(--green); }
.val-result.wrong { color: var(--red); }
.val-num-big { font-family: var(--font-mono); font-size: 20px; color: var(--text-primary); }

/* Decisions */
.decisions-card { }
.decisions-header {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 8px;
}
.decision-filters { display: flex; gap: 4px; flex-wrap: wrap; }

.decision-list {
  max-height: 600px; overflow-y: auto; margin-top: 12px;
  display: flex; flex-direction: column; gap: 4px;
}

.decision-item {
  padding: 10px 14px; background: var(--bg-input);
  border-radius: var(--radius); border-left: 3px solid transparent;
}
.decision-item.hold { opacity: 0.4; }

.dec-header {
  display: flex; align-items: center; gap: 10px;
  font-family: var(--font-mono); font-size: 12px;
}
.dec-bar { color: var(--text-muted); width: 50px; }
.dec-agent { display: flex; align-items: center; gap: 4px; color: var(--text-secondary); width: 100px; }
.dec-action { font-weight: 600; }
.dec-action.buy { color: var(--green); }
.dec-action.sell { color: var(--red); }
.dec-action.exit { color: var(--orange); }
.dec-qty { color: var(--text-secondary); }
.dec-conviction {
  padding: 1px 6px; border-radius: 3px;
  background: var(--accent-glow); color: var(--accent); font-size: 10px;
}

.dec-reasoning {
  margin-top: 6px; font-size: 12px; color: var(--text-secondary);
  line-height: 1.5; padding-left: 60px;
}

.dec-footer {
  margin-top: 4px; padding-left: 60px;
  display: flex; gap: 16px;
  font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);
}

.loading {
  padding: 24px; text-align: center;
  font-family: var(--font-mono); font-size: 13px; color: var(--text-muted);
}

@media (max-width: 900px) {
  .detail-grid { grid-template-columns: 1fr; }
  .val-big { grid-template-columns: repeat(2, 1fr); }
}
</style>
