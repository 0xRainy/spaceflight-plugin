import QtQuick
import Quickshell
import Quickshell.Io

// Runs once after `omarchy plugin add` enables the plugin: install CLI + daemon.
Item {
  id: root
  property var shell: null
  property bool started: false

  function pluginDir() {
    var u = String(Qt.resolvedUrl("."))
    return u.replace(/^file:\/\//, "").replace(/\/$/, "")
  }

  function startBootstrap() {
    if (bootProc.running)
      return
    var dir = pluginDir()
    bootProc.command = ["env", "PYTHONPATH=" + dir, "python3", "-m", "spaceflight", "bootstrap"]
    bootProc.running = true
  }

  Component.onCompleted: startBootstrap()

  Process {
    id: bootProc
    stdout: StdioCollector { waitForEnd: true }
  }
}
