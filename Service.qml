import QtQuick
import Quickshell
import Quickshell.Io

// After `omarchy plugin add` enables us, open a terminal for interactive setup.
// The official installer never runs plugin hooks — this is the first code that runs.
Item {
  id: root
  property var shell: null
  property bool launched: false

  function pluginDir() {
    var u = String(Qt.resolvedUrl("."))
    return u.replace(/^file:\/\//, "").replace(/\/$/, "")
  }

  function launchSetupTerminal() {
    if (root.launched || launchProc.running)
      return
    root.launched = true
    var script = pluginDir() + "/scripts/plugin-setup"
    launchProc.command = ["omarchy-launch-or-focus-tui", "--app-id=org.omarchy.spaceflight-setup", script]
    launchProc.running = true
  }

  FileView {
    id: wizardFlag
    path: Quickshell.env("HOME") + "/.local/state/spaceflight/onboard.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.maybeLaunch(text())
    onLoadFailed: root.maybeLaunch("")
    Component.onCompleted: reload()
  }

  function maybeLaunch(raw) {
    var done = false
    try {
      var data = JSON.parse(String(raw || "{}"))
      done = data && data.plugin_wizard_done === true
    } catch (e) {
      done = false
    }
    if (!done)
      Qt.callLater(root.launchSetupTerminal)
  }

  Process {
    id: launchProc
  }
}
