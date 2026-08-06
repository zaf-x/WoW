<script setup>
import { computed } from 'vue'
import { store, formatBytes } from '../store'
import { t } from '../i18n'

// chart geometry
const W = 620
const H = 240
const PAD_L = 56
const PAD_R = 12
const PAD_T = 12
const PAD_B = 24
const N = 60 // seconds shown

const plotW = W - PAD_L - PAD_R
const plotH = H - PAD_T - PAD_B

const yMax = computed(() => {
  let m = 0
  for (const p of store.rateHistory) m = Math.max(m, p.up, p.down)
  if (m <= 0) return 1024
  // round up to a nice magnitude
  const pow = Math.pow(10, Math.floor(Math.log10(m)))
  return Math.ceil(m / pow) * pow * 1.1
})

function y(v) {
  return PAD_T + plotH - (v / yMax.value) * plotH
}
// index 0 = oldest shown sample (left); newest at right edge
function x(i, len) {
  return PAD_L + ((N - len + i) / (N - 1)) * plotW
}

function pathFor(key) {
  const h = store.rateHistory
  if (!h.length) return ''
  return h
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i, h.length).toFixed(1)},${y(p[key]).toFixed(1)}`)
    .join(' ')
}

const upPath = computed(() => pathFor('up'))
const downPath = computed(() => pathFor('down'))

const gridLines = computed(() => {
  const lines = []
  for (let i = 0; i <= 4; i++) {
    const v = (yMax.value * i) / 4
    lines.push({ v, y: y(v) })
  }
  return lines
})
</script>

<template>
  <div>
    <h2>{{ t('traffic.title') }}</h2>
    <div class="cards">
      <div class="card">
        <div class="label">{{ t('traffic.upTotal') }}</div>
        <div class="value">{{ formatBytes(store.upBytes) }}</div>
        <div class="rate up">{{ formatBytes(store.upRate) }}/s</div>
      </div>
      <div class="card">
        <div class="label">{{ t('traffic.downTotal') }}</div>
        <div class="value">{{ formatBytes(store.downBytes) }}</div>
        <div class="rate down">{{ formatBytes(store.downRate) }}/s</div>
      </div>
    </div>

    <div class="chart-box">
      <div class="chart-head">
        <span class="chart-title">{{ t('traffic.rate') }} · {{ t('traffic.lastMinute') }}</span>
        <span class="legend">
          <span class="swatch up"></span>{{ t('traffic.up') }}
          <span class="swatch down"></span>{{ t('traffic.down') }}
        </span>
      </div>
      <svg :viewBox="`0 0 ${W} ${H}`" class="chart">
        <!-- horizontal grid + y labels -->
        <g v-for="(g, i) in gridLines" :key="i">
          <line
            :x1="PAD_L" :x2="W - PAD_R" :y1="g.y" :y2="g.y"
            stroke="#22262f" stroke-width="1"
          />
          <text
            :x="PAD_L - 8" :y="g.y + 4" text-anchor="end"
            fill="#8a919e" font-size="10"
          >{{ formatBytes(g.v) }}</text>
        </g>
        <!-- x axis labels -->
        <text :x="PAD_L" :y="H - 8" fill="#8a919e" font-size="10">-60s</text>
        <text :x="PAD_L + plotW / 2" :y="H - 8" text-anchor="middle" fill="#8a919e" font-size="10">-30s</text>
        <text :x="W - PAD_R" :y="H - 8" text-anchor="end" fill="#8a919e" font-size="10">0</text>
        <!-- series -->
        <path :d="upPath" fill="none" stroke="#58a6ff" stroke-width="2" stroke-linejoin="round" />
        <path :d="downPath" fill="none" stroke="#3fb950" stroke-width="2" stroke-linejoin="round" />
      </svg>
    </div>
  </div>
</template>

<style scoped>
.cards { display: flex; gap: 16px; margin-bottom: 22px; }
.card {
  flex: 1;
  max-width: 260px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
}
.label { color: var(--text-dim); font-size: 12px; margin-bottom: 8px; }
.value { font-size: 26px; font-weight: 700; }
.rate { margin-top: 6px; font-family: ui-monospace, monospace; font-size: 13px; }
.rate.up { color: var(--accent-light); }
.rate.down { color: var(--green); }

.chart-box {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
}
.chart-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.chart-title { color: var(--text-dim); font-size: 12px; }
.legend { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-dim); }
.swatch { display: inline-block; width: 14px; height: 3px; border-radius: 2px; margin-left: 10px; }
.swatch.up { background: var(--accent-light); }
.swatch.down { background: var(--green); }
.chart { width: 100%; height: auto; display: block; }
</style>
