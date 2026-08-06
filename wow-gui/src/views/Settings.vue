<script setup>
import { ref, onMounted } from 'vue'
import { t } from '../i18n'

const form = ref({
  host: '',
  port: 443,
  token: '',
  mgmtPort: 7891,
  pythonPath: '/home/baosh/Projects/Web/WoW/venv/bin/python',
})
const savedMsg = ref('')
const shutdownMsg = ref('')

onMounted(async () => {
  const cfg = await window.wow.getConfig()
  form.value = { ...form.value, ...cfg }
})

async function save() {
  await window.wow.setConfig({
    host: form.value.host,
    port: Number(form.value.port) || 443,
    token: form.value.token,
    mgmtPort: Number(form.value.mgmtPort) || 7891,
    pythonPath: form.value.pythonPath,
  })
  savedMsg.value = t('settings.saved')
  setTimeout(() => (savedMsg.value = ''), 2000)
}

async function shutdown() {
  shutdownMsg.value = ''
  try {
    const resp = await window.wow.send({ cmd: 'shutdown' })
    shutdownMsg.value = resp.ok
      ? t('settings.shutdownSent')
      : `${t('settings.failed')}: ${resp.error || 'unknown'}`
  } catch (e) {
    shutdownMsg.value = `${t('settings.failed')}: ${e.message}`
  }
}
</script>

<template>
  <div>
    <h2>{{ t('settings.title') }}</h2>
    <form class="form" @submit.prevent="save">
      <div class="field">
        <label>{{ t('settings.host') }}</label>
        <input v-model="form.host" :placeholder="t('settings.hostPlaceholder')" />
      </div>
      <div class="field">
        <label>{{ t('settings.port') }}</label>
        <input v-model.number="form.port" type="number" min="1" max="65535" />
      </div>
      <div class="field">
        <label>{{ t('settings.token') }}</label>
        <input v-model="form.token" type="password" autocomplete="off" />
      </div>
      <div class="field">
        <label>{{ t('settings.mgmtPort') }}</label>
        <input v-model.number="form.mgmtPort" type="number" min="1" max="65535" />
      </div>
      <div class="field">
        <label>{{ t('settings.pythonPath') }}</label>
        <input v-model="form.pythonPath" />
      </div>
      <div class="actions">
        <button type="submit" class="btn primary">{{ t('settings.save') }}</button>
        <span class="msg ok">{{ savedMsg }}</span>
      </div>
    </form>

    <hr />
    <h3>{{ t('settings.daemonSection') }}</h3>
    <div class="actions">
      <button class="btn danger" @click="shutdown">{{ t('settings.shutdown') }}</button>
      <span class="msg">{{ shutdownMsg }}</span>
    </div>
  </div>
</template>

<style scoped>
.form { max-width: 440px; }
.field { margin-bottom: 14px; }
.field label { display: block; color: var(--text-dim); margin-bottom: 5px; font-size: 12px; }
.field input {
  width: 100%;
  background: var(--bg-inset);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  padding: 9px 12px;
  font-size: 14px;
  transition: border-color 0.15s;
}
.field input:focus { outline: none; border-color: var(--accent); }
.actions { display: flex; align-items: center; gap: 12px; }
.btn {
  border: none;
  border-radius: var(--radius);
  padding: 9px 22px;
  cursor: pointer;
  color: #fff;
  font-size: 14px;
  transition: background 0.15s;
}
.btn.primary { background: var(--accent); }
.btn.primary:hover { background: #4484f5; }
.btn.danger { background: #b62324; }
.btn.danger:hover { background: var(--red); }
.msg { color: var(--text-dim); font-size: 13px; }
.msg.ok { color: var(--green); }
hr { border: none; border-top: 1px solid var(--border); margin: 26px 0; }
h3 { font-size: 15px; margin: 0 0 12px; }
</style>
