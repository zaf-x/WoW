import { reactive } from 'vue'

// shared reactive state fed by daemon events; safe to import from any view
export const store = reactive({
  mgmtConnected: false,
  state: 'disconnected', // disconnected | connecting | connected
  tunnelIp: '',
  server: '',
  error: '',
  upBytes: 0,
  downBytes: 0,
  upRate: 0, // B/s
  downRate: 0, // B/s
  // ring buffer of per-second rates, one entry per stats event, newest last
  rateHistory: [], // [{up, down}] max 60 entries
  logs: [],
})

const HISTORY_LEN = 60
let lastStats = null // {ts, up, down}

export function handleEvent(obj) {
  if (obj.event === 'state') {
    const wasConnected = store.state === 'connected'
    store.state = obj.state || 'disconnected'
    store.tunnelIp = obj.tunnel_ip || ''
    store.server = obj.server || ''
    store.error = obj.error || ''
    if (store.state !== 'connected') {
      store.upRate = 0
      store.downRate = 0
      lastStats = null
      if (!wasConnected && store.state === 'disconnected') {
        // fresh disconnect: keep history visible until a new session starts
      }
    } else if (!wasConnected) {
      // new session: restart the chart
      store.rateHistory = []
      store.upBytes = 0
      store.downBytes = 0
      lastStats = null
    }
  } else if (obj.event === 'stats') {
    const now = Date.now()
    if (lastStats) {
      const dt = (now - lastStats.ts) / 1000
      if (dt > 0) {
        store.upRate = Math.max(0, (obj.up_bytes - lastStats.up) / dt)
        store.downRate = Math.max(0, (obj.down_bytes - lastStats.down) / dt)
      }
    }
    lastStats = { ts: now, up: obj.up_bytes, down: obj.down_bytes }
    store.upBytes = obj.up_bytes
    store.downBytes = obj.down_bytes
    store.rateHistory.push({ up: store.upRate, down: store.downRate })
    if (store.rateHistory.length > HISTORY_LEN) {
      store.rateHistory.splice(0, store.rateHistory.length - HISTORY_LEN)
    }
  } else if (obj.event === 'log') {
    store.logs.push(obj.line)
    if (store.logs.length > 200) store.logs.splice(0, store.logs.length - 200)
  } else if (obj.event === 'mgmt') {
    store.mgmtConnected = !!obj.connected
  }
}

export function formatBytes(n) {
  if (!n || n < 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}
