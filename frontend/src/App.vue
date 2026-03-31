<template>
  <div class="app">
    <header class="app-header">
      <div class="logo-group">
        <div class="logo-icon">◈</div>
        <div>
          <h1 class="logo-text">MiroFish</h1>
          <span class="logo-sub">ES Futures Trading Simulation</span>
        </div>
      </div>
      <nav class="header-nav">
        <router-link to="/" class="nav-link">Simulations</router-link>
        <router-link to="/live" class="nav-link nav-live">◈ Live</router-link>
      </nav>
      <div class="header-status">
        <span class="status-dot" :class="healthOk ? 'ok' : 'err'"></span>
        <span class="status-label">{{ healthOk ? 'Connected' : 'Offline' }}</span>
        <span v-if="storageType" class="status-badge">{{ storageType }}</span>
      </div>
    </header>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from './services/api.js'

const healthOk = ref(false)
const storageType = ref('')

onMounted(async () => {
  try {
    const { data } = await api.health()
    healthOk.value = data.status === 'ok'
    storageType.value = data.storage || ''
  } catch {
    healthOk.value = false
  }
})
</script>

<style>
:root {
  --bg-primary: #0a0e17;
  --bg-secondary: #111827;
  --bg-card: #151d2e;
  --bg-input: #1a2236;
  --border: #1e293b;
  --border-focus: #3b82f6;
  --text-primary: #e2e8f0;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
  --accent: #3b82f6;
  --accent-glow: rgba(59, 130, 246, 0.15);
  --green: #22c55e;
  --green-dim: rgba(34, 197, 94, 0.15);
  --red: #ef4444;
  --red-dim: rgba(239, 68, 68, 0.15);
  --orange: #f59e0b;
  --orange-dim: rgba(245, 158, 11, 0.15);
  --purple: #a855f7;
  --font-mono: 'JetBrains Mono', monospace;
  --font-sans: 'DM Sans', sans-serif;
  --radius: 8px;
  --radius-lg: 12px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: var(--font-sans);
  background: var(--bg-primary);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
}

.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 32px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.logo-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  font-size: 28px;
  color: var(--accent);
  filter: drop-shadow(0 0 8px var(--accent-glow));
}

.logo-text {
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.5px;
  color: var(--text-primary);
}

.logo-sub {
  font-size: 11px;
  color: var(--text-muted);
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.header-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
}
.status-dot.ok { background: var(--green); box-shadow: 0 0 6px var(--green); }
.status-dot.err { background: var(--red); }

.status-badge {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--accent-glow);
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.app-main {
  flex: 1;
  padding: 24px 32px;
}

/* Shared component styles */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
}

.card-title {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  margin-bottom: 16px;
}

.btn {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 500;
  padding: 10px 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-input);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.15s;
}
.btn:hover { border-color: var(--accent); background: var(--accent-glow); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-primary {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
}
.btn-primary:hover { background: #2563eb; }

.input {
  font-family: var(--font-mono);
  font-size: 13px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-input);
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.15s;
  width: 100%;
}
.input:focus { border-color: var(--border-focus); }

.select {
  font-family: var(--font-mono);
  font-size: 13px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-input);
  color: var(--text-primary);
  outline: none;
  width: 100%;
  cursor: pointer;
}

.badge {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 4px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.badge-green { background: var(--green-dim); color: var(--green); }
.badge-red { background: var(--red-dim); color: var(--red); }
.badge-orange { background: var(--orange-dim); color: var(--orange); }
.badge-blue { background: var(--accent-glow); color: var(--accent); }

.header-nav {
  display: flex;
  gap: 4px;
}

.nav-link {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 6px 14px;
  border-radius: var(--radius);
  color: var(--text-secondary);
  text-decoration: none;
  transition: all 0.15s;
}
.nav-link:hover { color: var(--text-primary); background: var(--bg-card); }
.nav-link.router-link-active { color: var(--accent); background: var(--accent-glow); }

.nav-live {
  color: var(--accent);
  border: 1px solid var(--border);
}
.nav-live:hover { border-color: var(--accent); }
.nav-live.router-link-active { border-color: var(--accent); }
</style>
