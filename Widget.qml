import QtQuick
import qs.Commons
import qs.Ui

// Bar pill: rocket + live countdown. Click opens the mission panel (no tooltip).
BarWidget {
  id: root
  moduleName: "0xrainy.spaceflight"

  property string barText: "🚀  …"
  property string barClass: "pending"

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
    var p = panelLoader.item
    if (!p) {
      barText = "🚀  …"
      barClass = "pending"
      return
    }
    barText = String(p.barText || "🚀  …")
    barClass = String(p.barClass || "pending")
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
    text: root.barText
  }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

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
      text: root.barText
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
        if (mouse.button === Qt.RightButton)
          root.bar.run("omarchy-launch-or-focus-tui spaceflight")
        else if (mouse.button === Qt.MiddleButton)
          root.bar.run("spaceflight refresh")
        else
          root.togglePanel()
      }
    }
  }
}
