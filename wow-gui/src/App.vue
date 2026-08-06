<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import Connection from './views/Connection.vue'
import Settings from './views/Settings.vue'
import Traffic from './views/Traffic.vue'
import { store, handleEvent } from './store'
import { i18n, t, toggleLocale } from './i18n'
import logoUrl from './assets/logo.svg'

const views = [
  { key: 'connection' },
  { key: 'settings' },
  { key: 'traffic' },
]
const current = ref('connection')

let off = null
onMounted(() => {
  off = window.wow.onEvent(handleEvent)
})
onUnmounted(() => {
  if (off) off()
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <img :src="logoUrl" class="logo" alt="logo" />
        <span>{{ t('appName') }}</span>
      </div>
      <nav>
        <button
          v-for="v in views"
          :key="v.key"
          :class="['nav-btn', { active: current === v.key }]"
          @click="current = v.key"
        >
          {{ t('nav.' + v.key) }}
        </button>
      </nav>
      <button class="lang-btn" @click="toggleLocale">
        {{ i18n.locale === 'zh' ? 'EN' : '中' }}
      </button>
      <div class="mgmt" :class="{ ok: store.mgmtConnected }">
        <span class="dot"></span>
        {{ store.mgmtConnected ? t('daemon.online') : t('daemon.offline') }}
      </div>
    </aside>
    <main class="content">
      <Connection v-show="current === 'connection'" />
      <Settings v-show="current === 'settings'" />
      <Traffic v-show="current === 'traffic'" />
    </main>
  </div>
</template>

<style>
:root {
  --bg: #0b0d12;
  --bg-panel: #12151c;
  --bg-inset: #08090d;
  --border: #22262f;
  --text: #d7dae0;
  --text-dim: #8a919e;
  --accent: #2f6feb;
  --accent-light: #58a6ff;
  --green: #3fb950;
  --red: #f85149;
  --radius: 8px;
}
* { box-sizing: border-box; }
html, body, #app { height: 100%; margin: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 14px;
}
.layout { display: flex; height: 100%; }
.sidebar {
  width: 190px;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 18px 12px;
  gap: 6px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  font-size: 16px;
  padding: 0 8px 16px;
  letter-spacing: 0.5px;
}
.logo { width: 30px; height: 30px; }
nav { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.nav-btn {
  background: none;
  border: none;
  color: var(--text-dim);
  text-align: left;
  padding: 9px 12px;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 14px;
  transition: background 0.15s, color 0.15s;
}
.nav-btn:hover { background: #1a1e27; color: var(--text); }
.nav-btn.active { background: var(--accent); color: #fff; }
.lang-btn {
  align-self: flex-start;
  margin: 0 8px 6px;
  background: none;
  border: 1px solid var(--border);
  color: var(--text-dim);
  border-radius: 6px;
  padding: 3px 10px;
  cursor: pointer;
  font-size: 12px;
  transition: border-color 0.15s, color 0.15s;
}
.lang-btn:hover { border-color: var(--accent-light); color: var(--accent-light); }
.mgmt {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px 0;
  color: var(--text-dim);
  font-size: 12px;
}
.mgmt .dot { width: 8px; height: 8px; border-radius: 50%; background: #666; flex-shrink: 0; }
.mgmt.ok .dot { background: var(--green); box-shadow: 0 0 6px var(--green); }
.content { flex: 1; padding: 24px 28px; overflow-y: auto; }
h2 { margin: 0 0 18px; font-size: 18px; font-weight: 600; }
</style>
