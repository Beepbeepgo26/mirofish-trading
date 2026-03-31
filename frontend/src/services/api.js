import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 600000, // 10 min — simulations can take a while
})

export default {
  // Health
  health() {
    return api.get('/health')
  },

  // Scenarios
  listScenarios() {
    return api.get('/scenarios')
  },

  // Simulations
  createSimulation(params) {
    return api.post('/simulations', params)
  },

  listSimulations(limit = 50) {
    return api.get('/simulations', { params: { limit } })
  },

  getSimulation(simId) {
    return api.get(`/simulations/${simId}`)
  },

  getDecisions(simId, { agentType, bar } = {}) {
    const params = {}
    if (agentType) params.agent_type = agentType
    if (bar !== undefined) params.bar = bar
    return api.get(`/simulations/${simId}/decisions`, { params })
  },

  getBars(simId) {
    return api.get(`/simulations/${simId}/bars`)
  },

  getValidation(simId) {
    return api.get(`/simulations/${simId}/validation`)
  },

  getSummary(simId) {
    return api.get(`/simulations/${simId}/summary`, { responseType: 'text' })
  },

  deleteSimulation(simId) {
    return api.delete(`/simulations/${simId}`)
  },

  // Databento
  checkCost(params) {
    return api.post('/databento/cost', params)
  },

  previewBars(params) {
    return api.post('/databento/bars', params)
  },

  // Live streaming
  startLive(params) {
    return api.post('/live/start', params)
  },

  stopLive() {
    return api.post('/live/stop')
  },

  liveStatus() {
    return api.get('/live/status')
  },

  pollLiveEvents(after = 0) {
    return api.get('/live/events', { params: { after } })
  },

  // SSE connection for real-time updates
  connectLiveStream(sessionId, onEvent) {
    const source = new EventSource(`/ws/live/${sessionId}`)
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onEvent(data)
      } catch (e) {
        console.error('SSE parse error:', e)
      }
    }
    source.onerror = (err) => {
      console.error('SSE error:', err)
      source.close()
    }
    return source  // Caller should store this and call .close() when done
  },
}
