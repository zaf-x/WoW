const { app, BrowserWindow, ipcMain } = require('electron')
const path = require('path')
const fs = require('fs')
const net = require('net')
const { spawn } = require('child_process')

const DEFAULTS = {
  host: '',
  port: 443,
  token: '',
  mgmtPort: 7891,
  pythonPath: '/home/baosh/Projects/Web/WoW/venv/bin/python',
}

const isDev = !app.isPackaged
let win = null
let config = { ...DEFAULTS }

// ---------- config ----------

function configPath() {
  return path.join(app.getPath('userData'), 'config.json')
}

function loadConfig() {
  try {
    const raw = fs.readFileSync(configPath(), 'utf8')
    config = { ...DEFAULTS, ...JSON.parse(raw) }
  } catch {
    config = { ...DEFAULTS }
  }
  return config
}

function saveConfig(cfg) {
  config = { ...DEFAULTS, ...cfg }
  fs.mkdirSync(path.dirname(configPath()), { recursive: true })
  fs.writeFileSync(configPath(), JSON.stringify(config, null, 2))
  return config
}

// ---------- management TCP client ----------

let socket = null
let lineBuf = ''
let reconnectTimer = null
let consecutiveFailures = 0
let daemonSpawnAttempted = false
let mgmtConnected = false
let lastState = { event: 'state', state: 'disconnected' } // cached for late-joining renderers
const pending = [] // FIFO of {resolve, reject} waiting for the next non-event response

function broadcast(obj) {
  if (obj.event === 'state') lastState = obj
  if (win && !win.isDestroyed()) win.webContents.send('vpn:event', obj)
}

function flushPending(err) {
  while (pending.length) pending.shift().reject(err)
}

function handleLine(line) {
  let obj
  try {
    obj = JSON.parse(line)
  } catch {
    return
  }
  if (obj.event) {
    broadcast(obj)
    return
  }
  // protocol is one-request-one-response; events may be interleaved
  const waiter = pending.shift()
  if (waiter) waiter.resolve(obj)
  else broadcast({ event: 'log', line: '[mgmt] unsolicited response: ' + line })
}

function connectMgmt() {
  if (socket) return
  const port = Number(config.mgmtPort) || 7891
  socket = new net.Socket()
  lineBuf = ''

  socket.on('connect', () => {
    consecutiveFailures = 0
    daemonSpawnAttempted = false
    mgmtConnected = true
    broadcast({ event: 'log', line: `[mgmt] connected to 127.0.0.1:${port}` })
    broadcast({ event: 'mgmt', connected: true })
  })

  socket.on('data', (chunk) => {
    lineBuf += chunk.toString('utf8')
    let idx
    while ((idx = lineBuf.indexOf('\n')) >= 0) {
      const line = lineBuf.slice(0, idx).trim()
      lineBuf = lineBuf.slice(idx + 1)
      if (line) handleLine(line)
    }
  })

  const onDown = (reason) => {
    if (socket) {
      socket.destroy()
      socket = null
    }
    mgmtConnected = false
    flushPending(new Error('management socket closed: ' + reason))
    broadcast({ event: 'mgmt', connected: false })
    scheduleReconnect()
  }
  socket.on('error', (err) => {
    consecutiveFailures++
    broadcast({ event: 'log', line: `[mgmt] socket error: ${err.message}` })
    if (consecutiveFailures >= 3) maybeSpawnDaemon()
  })
  socket.on('close', () => onDown('close'))

  socket.connect(port, '127.0.0.1')
}

function scheduleReconnect() {
  if (reconnectTimer) return
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connectMgmt()
  }, 2000)
}

function maybeSpawnDaemon() {
  if (daemonSpawnAttempted) return
  daemonSpawnAttempted = true
  const python = config.pythonPath || DEFAULTS.pythonPath
  const port = Number(config.mgmtPort) || 7891
  broadcast({ event: 'log', line: '[mgmt] attempting to start daemon via pkexec...' })
  const child = spawn('pkexec', [
    python, '-m', 'wow_client.client', '--daemon', '--mgmt-port', String(port),
  ], { stdio: ['ignore', 'ignore', 'ignore'] })
  // NOTE: daemon 的 stdout/stderr 必须丢弃（或重定向到文件），否则 GUI 退出后
  // 管道写满会阻塞 daemon 的事件循环。日志走管理端口的 log 事件，不丢信息。
  child.on('error', (err) => broadcast({ event: 'log', line: `[daemon] spawn error: ${err.message}` }))
  child.on('exit', (code, signal) => {
    broadcast({ event: 'log', line: `[daemon] exited (code=${code}, signal=${signal})` })
  })
}

// ---------- IPC ----------

ipcMain.handle('vpn:send', (_e, cmd) => {
  return new Promise((resolve, reject) => {
    if (!socket || socket.destroyed) {
      reject(new Error('not connected to daemon'))
      return
    }
    pending.push({ resolve, reject })
    socket.write(JSON.stringify(cmd) + '\n')
  })
})

ipcMain.handle('vpn:state', () => ({ mgmtConnected, state: lastState }))

ipcMain.handle('config:get', () => loadConfig())

ipcMain.handle('config:set', (_e, cfg) => {
  const saved = saveConfig(cfg || {})
  // reconnect management socket if the port changed
  if (socket && socket.remotePort !== (Number(saved.mgmtPort) || 7891)) {
    socket.destroy()
    socket = null
    flushPending(new Error('mgmt port changed'))
    scheduleReconnect()
  }
  return saved
})

// ---------- window ----------

function createWindow() {
  win = new BrowserWindow({
    width: 900,
    height: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (isDev && process.env.VITE_DEV_SERVER_URL !== 'none') {
    win.loadURL('http://localhost:5173')
  } else {
    win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }
}

app.whenReady().then(() => {
  loadConfig()
  createWindow()
  connectMgmt()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

// closing the GUI must not kill the daemon; just drop our mgmt socket
app.on('window-all-closed', () => {
  if (socket) {
    socket.destroy()
    socket = null
  }
  flushPending(new Error('app quitting'))
  if (reconnectTimer) clearTimeout(reconnectTimer)
  app.quit()
})
