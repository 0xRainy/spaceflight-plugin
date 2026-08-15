import QtQuick
import Quickshell
import Quickshell.Io

// First-boot: install CLI/daemon, then finish setup in the installer TTY
// or one fallback terminal. Does not edit system files.
Item {
  id: root
  property var shell: null
  property var manifest: null
  property bool booted: false

  function pluginDir() {
    var u = String(Qt.resolvedUrl("."))
    return u.replace(/^file:\/\//, "").replace(/\/$/, "")
  }

  function startFirstBoot() {
    if (root.booted || bootProc.running)
      return
    root.booted = true
    bootProc.command = ["/bin/bash", pluginDir() + "/scripts/first-boot"]
    bootProc.running = true
  }

  Component.onCompleted: Qt.callLater(root.startFirstBoot)

  Process {
    id: bootProc
  }
}
