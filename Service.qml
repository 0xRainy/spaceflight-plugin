import QtQuick
import Quickshell
import Quickshell.Io

// Silent first-boot only. Setup questions run in the `omarchy plugin add`
// terminal (shell hook / continue-setup). Never open extra terminals.
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
