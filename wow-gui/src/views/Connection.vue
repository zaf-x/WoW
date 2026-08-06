<script setup>
import { computed, ref } from 'vue'
import { store } from '../store'
import { t } from '../i18n'

const busy = ref(false)
const actionError = ref('')
const logOpen = ref(true)

// error state takes priority: a state event carrying error means 连接异常
const visual = computed(() => {
  if (store.error) return 'error'
  return store.state // disconnected | connecting | connected
})

const stateText = computed(() => t('state.' + visual.value))

const clickable = computed(() =>
  store.mgmtConnected && !busy.value && store.state !== 'connecting'
)

async function send(cmd) {
  busy.value = true
  actionError.value = ''
  try {
    const resp = await window.wow.send(cmd)
    if (!resp.ok) actionError.value = resp.error || 'unknown error'
  } catch (e) {
    actionError.value = e.message
  } finally {
    busy.value = false
  }
}

async function onCircleClick() {
  if (!clickable.value) return
  if (visual.value === 'disconnected' || visual.value === 'error') {
    const cfg = await window.wow.getConfig()
    if (!cfg.host || !cfg.token) {
      actionError.value = t('conn.needConfig')
      return
    }
    await send({ cmd: 'connect', host: cfg.host, port: Number(cfg.port) || 443, token: cfg.token })
  } else if (visual.value === 'connected') {
    await send({ cmd: 'disconnect' })
  }
}
</script>

<template>
  <div class="page">
    <div class="center">
      <div
        class="circle"
        :class="[visual, { clickable }]"
        @click="onCircleClick"
      >
        <span class="circle-text">{{ stateText }}</span>
      </div>

      <div class="info">
        <div v-if="store.server" class="info-row">
          <label>{{ t('conn.server') }}</label><span>{{ store.server }}</span>
        </div>
        <div v-if="store.tunnelIp" class="info-row">
          <label>{{ t('conn.tunnelIp') }}</label><span>{{ store.tunnelIp }}</span>
        </div>
        <div v-if="store.error" class="info-row err">
          <label>{{ t('conn.error') }}</label><span>{{ store.error }}</span>
        </div>
        <div v-if="actionError" class="info-row err"><span>{{ actionError }}</span></div>
        <div v-if="!store.mgmtConnected" class="hint">{{ t('conn.mgmtOffline') }}</div>
      </div>
    </div>

    <div class="log-section">
      <button class="log-toggle" @click="logOpen = !logOpen">
        {{ t('conn.logTitle') }} {{ logOpen ? '▾' : '▸' }}
      </button>
      <div v-show="logOpen" class="log-box">
        <div v-for="(line, i) in store.logs" :key="i" class="log-line">{{ line }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; align-items: center; }
.center {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 12px;
}
.circle {
  width: 220px;
  height: 220px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 20px;
  user-select: none;
  transition: box-shadow 0.25s, background 0.25s, border-color 0.25s;
}
.circle.clickable { cursor: pointer; }
.circle-text { font-size: 20px; font-weight: 600; }

.circle.disconnected {
  border: 3px solid #3a404c;
  background: #171a21;
  color: var(--text-dim);
}
.circle.disconnected.clickable:hover { border-color: var(--accent-light); color: var(--text); }

.circle.connecting {
  border: 3px solid var(--accent);
  background: rgba(47, 111, 235, 0.12);
  color: var(--accent-light);
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; box-shadow: 0 0 0 0 rgba(47, 111, 235, 0.4); }
  50% { transform: scale(1.04); opacity: 0.75; box-shadow: 0 0 32px 6px rgba(47, 111, 235, 0.35); }
}

.circle.connected {
  border: 3px solid var(--accent);
  background: radial-gradient(circle at 50% 40%, rgba(88, 166, 255, 0.28), rgba(47, 111, 235, 0.10) 70%);
  color: var(--accent-light);
  box-shadow: 0 0 36px 4px rgba(47, 111, 235, 0.45);
}
.circle.connected.clickable:hover { box-shadow: 0 0 48px 8px rgba(47, 111, 235, 0.6); }

.circle.error {
  border: 3px solid var(--red);
  background: rgba(248, 81, 73, 0.10);
  color: var(--red);
}
.circle.error.clickable:hover { box-shadow: 0 0 24px 2px rgba(248, 81, 73, 0.4); }

.info { margin-top: 20px; min-height: 24px; text-align: center; }
.info-row { display: flex; gap: 10px; justify-content: center; line-height: 1.9; }
.info-row label { color: var(--text-dim); min-width: 70px; text-align: right; }
.info-row.err span, .info-row.err label { color: var(--red); }
.hint { color: #d29922; font-size: 12px; margin-top: 6px; }

.log-section { width: 100%; max-width: 640px; margin-top: 26px; }
.log-toggle {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 13px;
  padding: 4px 0;
  margin-bottom: 6px;
}
.log-toggle:hover { color: var(--accent-light); }
.log-box {
  background: var(--bg-inset);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  height: 160px;
  overflow-y: auto;
  padding: 8px 12px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.log-line { white-space: pre-wrap; color: #9aa1ad; line-height: 1.6; }
</style>
