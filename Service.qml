import QtQuick
import Quickshell
import Quickshell.Io

// Omarchy does not run plugin install hooks. The moment this service loads
// (plugin enable, which is the end of `omarchy plugin add`), open a terminal
// and run the interactive TUI / daemon / ntfy wizard there — never in the bar.
Item {
  id: root
  property var shell: null
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
    var script = pluginDir() + "/scripts/plugin-setup"
    // launch-tui opens xdg-terminal-exec; do not use the bar card.
    launchProc.command = ["omarchy-launch-tui", "--app-id=org.omarchy.spaceflight-setup", script]
    launchProc.running = true
  }

  FileView {
    id: flagFile
    path: Quickshell.env("HOME") + "/.local/state/spaceflight/onboard.json"
    watchChanges: true
    printErrors: false
    onLoaded: {
      if (!root.setupDone(text()))
        root.launchSetupTerminal()
    }
    onLoadFailed: root.launchSetupTerminal()
    Component.onCompleted: reload()
  }

  Process {
    id: launchProc
  }
}
