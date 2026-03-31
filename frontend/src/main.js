import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Dashboard from './views/Dashboard.vue'
import SimDetail from './views/SimDetail.vue'
import LiveDashboard from './views/LiveDashboard.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Dashboard },
    { path: '/sim/:id', component: SimDetail, props: true },
    { path: '/live', component: LiveDashboard },
  ]
})

const app = createApp(App)
app.use(router)
app.mount('#app')
