import QtQuick
import Quickshell
import Quickshell.Io

// `omarchy plugin add` never runs hooks. When this service is enabled it
// opens a *terminal* (not the bar card) for TUI/daemon/ntfy setup.
Item {
  id: root
  property var shell: null
  property var manifest: null
  property bool launched: false

  function pluginDir() {
    var u = String(Qt.resolvedUrl("."))
    return u.replace(/^file:\/\//, "").replace(/\/$/, "")
  }

  function setupDone(raw) {
    try {
      var data = JSON.parse(String(raw || "{}"))
      return data && data.plugin_wizard_done === true
    } catch (e) {
      return false
    }
  }

  function launchSetupTerminal() {
    if (root.launched || launchProc.running)
      return
    root.launched = true
    var script = pluginDir() + "/scripts/launch-setup"
    launchProc.command = ["/bin/bash", script]
    launchProc.running = true
  }

  FileView {
    id: flagFile
    path: Quickshell.env("HOME") + "/.local/state/spaceflight/onboard.json"
    watchChanges: true
    printErrors: false
    onLoaded: {
      if (!root.setupDone(text()))
        Qt.callLater(root.launchSetupTerminal)
    }
    onLoadFailed: Qt.callLater(root.launchSetupTerminal)
    Component.onCompleted: reload()
  }

  Process {
    id: launchProc
  }
}
