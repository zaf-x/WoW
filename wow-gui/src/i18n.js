import { reactive } from 'vue'

const dicts = {
  zh: {
    appName: 'WoW VPN',
    nav: { connection: '连接', settings: '设置', traffic: '流量' },
    daemon: { online: 'daemon 已连接', offline: 'daemon 离线' },
    state: {
      disconnected: '未连接',
      connecting: '正在连接…',
      connected: '已连接',
      error: '连接异常',
    },
    conn: {
      server: '服务器',
      tunnelIp: '隧道 IP',
      error: '错误',
      needConfig: '请先在设置中配置服务器地址和令牌',
      mgmtOffline: '未连接到 daemon（管理端口），正在重试…',
      logTitle: '日志',
    },
    settings: {
      title: '设置',
      host: '服务器地址',
      hostPlaceholder: 'vpn.example.com',
      port: '端口',
      token: '令牌',
      mgmtPort: '管理端口',
      pythonPath: 'Python 路径',
      save: '保存',
      saved: '已保存',
      daemonSection: '守护进程',
      shutdown: '停止 daemon',
      shutdownSent: 'shutdown 命令已发送',
      failed: '失败',
    },
    traffic: {
      title: '流量',
      upTotal: '上行累计',
      downTotal: '下行累计',
      up: '上行',
      down: '下行',
      rate: '速率',
      lastMinute: '最近 60 秒',
    },
  },
  en: {
    appName: 'WoW VPN',
    nav: { connection: 'Connection', settings: 'Settings', traffic: 'Traffic' },
    daemon: { online: 'daemon connected', offline: 'daemon offline' },
    state: {
      disconnected: 'Disconnected',
      connecting: 'Connecting…',
      connected: 'Connected',
      error: 'Error',
    },
    conn: {
      server: 'Server',
      tunnelIp: 'Tunnel IP',
      error: 'Error',
      needConfig: 'Set host and token in Settings first',
      mgmtOffline: 'Not connected to daemon (mgmt port), retrying…',
      logTitle: 'Log',
    },
    settings: {
      title: 'Settings',
      host: 'Host',
      hostPlaceholder: 'vpn.example.com',
      port: 'Port',
      token: 'Token',
      mgmtPort: 'Management Port',
      pythonPath: 'Python Path',
      save: 'Save',
      saved: 'Saved',
      daemonSection: 'Daemon',
      shutdown: 'Stop daemon',
      shutdownSent: 'shutdown command sent',
      failed: 'Failed',
    },
    traffic: {
      title: 'Traffic',
      upTotal: 'Total Upload',
      downTotal: 'Total Download',
      up: 'Upload',
      down: 'Download',
      rate: 'Rate',
      lastMinute: 'Last 60s',
    },
  },
}

export const i18n = reactive({
  locale: localStorage.getItem('wow-locale') === 'en' ? 'en' : 'zh',
})

export function t(path) {
  const parts = path.split('.')
  let node = dicts[i18n.locale]
  for (const p of parts) {
    node = node && node[p]
  }
  return node !== undefined ? node : path
}

export function toggleLocale() {
  i18n.locale = i18n.locale === 'zh' ? 'en' : 'zh'
  localStorage.setItem('wow-locale', i18n.locale)
}
