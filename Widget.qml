import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Until first-run setup finishes, left-click opens that wizard.
// Afterward, left-click opens the mission card.
BarWidget {
  id: root
  moduleName: "0xrainy.spaceflight"

  property string barText: "🚀  setup"
  property string barClass: "pending"
  property string displayStyle: "text"
  property bool setupComplete: false

  function pluginDir() {
    var u = String(Qt.resolvedUrl("."))
    return u.replace(/^file:\/\//, "").replace(/\/$/, "")
  }

  function readSetupDone(raw) {
    try {
      var data = JSON.parse(String(raw || "{}"))
      return data && data.plugin_wizard_done === true
    } catch (e) {
      return false
    }
  }

  function launchSetup() {
    if (setupProc.running)
      return
    setupProc.command = ["/bin/bash", pluginDir() + "/scripts/launch-setup"]
    setupProc.running = true
  }

  function injectPanel() {
    var target = panelLoader.item
    if (!target)
      return
    if ("bar" in target)
      target.bar = root.bar
    if ("settings" in target)
      target.settings = root.settings
    if ("anchorItem" in target)
      target.anchorItem = hit
    if ("hostWidget" in target)
      target.hostWidget = root
  }

  function syncFromPanel() {
    if (!root.setupComplete) {
      barText = "🚀  setup"
      barClass = "pending"
      return
    }
    var p = panelLoader.item
    if (!p) {
      barText = "🚀  …"
      barClass = "pending"
      return
    }
    barText = String(p.barText || "🚀  …")
    barClass = String(p.barClass || "pending")
    var st = ""
    if (root.settings && root.settings.displayStyle)
      st = String(root.settings.displayStyle)
    if (!st && p.barStyle)
      st = String(p.barStyle)
    displayStyle = (st === "icon") ? "icon" : "text"
  }

  function refresh() {
    if (panelLoader.item && panelLoader.item.refresh)
      panelLoader.item.refresh()
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle)
      panelLoader.item.toggle()
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  function open() {
    if (!root.setupComplete) {
      root.launchSetup()
      return
    }
    if (panelLoader.item && panelLoader.item.openFromHotkey)
      panelLoader.item.openFromHotkey()
  }

  function close() {
    if (panelLoader.item && panelLoader.item.close)
      panelLoader.item.close()
  }

  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function closeForPopoutSwitch() {
    if (panelLoader.item)
      panelLoader.item.closeForPopoutSwitch()
  }

  implicitWidth: Math.max(Style.bar.statusSlot, labelMetrics.width + Style.space(16))
  implicitHeight: barSize

  TextMetrics {
    id: labelMetrics
    font.family: bar ? bar.fontFamily : Style.font.family
    font.pixelSize: Style.font.body
    text: root.displayStyle === "icon" ? "🚀" : root.barText
  }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  FileView {
    id: flagFile
    path: Quickshell.env("HOME") + "/.local/state/spaceflight/onboard.json"
    watchChanges: true
    printErrors: false
    onLoaded: {
      root.setupComplete = root.readSetupDone(text())
      root.syncFromPanel()
    }
    onLoadFailed: {
      root.setupComplete = false
      root.syncFromPanel()
    }
    Component.onCompleted: reload()
  }

  Process {
    id: setupProc
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
      root.syncFromPanel()
      if (panelLoader.item && panelLoader.item.barTextChanged)
        panelLoader.item.barTextChanged.connect(root.syncFromPanel)
    }
  }

  Item {
    id: hit
    anchors.fill: parent

    Text {
      anchors.centerIn: parent
      text: root.displayStyle === "icon" ? "🚀" : root.barText
      color: root.bar ? root.bar.barForeground : Color.foreground
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
      renderType: Text.NativeRendering
    }

    MouseArea {
      anchors.fill: parent
      acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: function(mouse) {
        if (!root.bar)
          return
        if (root.bar.hideTooltip)
          root.bar.hideTooltip(hit)
        root.setupComplete = root.readSetupDone(flagFile.text())
        if (mouse.button === Qt.RightButton)
          root.bar.run("omarchy-launch-or-focus-tui spaceflight")
        else if (mouse.button === Qt.MiddleButton)
          root.bar.run("spaceflight refresh")
        else if (!root.setupComplete)
          root.launchSetup()
        else
          root.togglePanel()
      }
    }
  }
}
