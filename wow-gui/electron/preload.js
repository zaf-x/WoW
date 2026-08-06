const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('wow', {
  send: (cmd) => ipcRenderer.invoke('vpn:send', cmd),
  onEvent: (cb) => {
    const listener = (_e, obj) => cb(obj)
    ipcRenderer.on('vpn:event', listener)
    return () => ipcRenderer.removeListener('vpn:event', listener)
  },
  getState: () => ipcRenderer.invoke('vpn:state'),
  getConfig: () => ipcRenderer.invoke('config:get'),
  setConfig: (cfg) => ipcRenderer.invoke('config:set', cfg),
})
