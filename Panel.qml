import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Click card: same layout as the original Waybar hover popup.
Panel {
  id: root
  moduleName: "0xrainy.spaceflight"
  ipcTarget: "0xrainy.spaceflight"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property bool openedFromHotkey: false
  readonly property var barIdentity: hostWidget || root

  property var state: Model.emptyPanel()
  property string barText: state.text || "🚀  …"
  property string barClass: state.klass || "pending"
  property string barStyle: state.bar_style || "text"

  readonly property int refreshMs: {
    var n = 1000
    if (root.settings && typeof root.settings.refreshMs !== "undefined")
      n = Number(root.settings.refreshMs)
    return Model.clampInt(n, 250, 10000, 1000)
  }

  readonly property string cardFont: {
    if (root.bar && root.bar.fontFamily)
      return String(root.bar.fontFamily)
    return "CaskaydiaCove Nerd Font Mono, JetBrainsMono Nerd Font, monospace"
  }

  function setCenterHoverRevealSuppressed(value) {
    if (root.bar && "centerHoverRevealSuppressed" in root.bar)
      root.bar.centerHoverRevealSuppressed = value
  }

  function open() {
    openedFromHotkey = false
    setCenterHoverRevealSuppressed(false)
    root.controller.show()
    cacheFile.reload()
  }

  function openFromHotkey() {
    openedFromHotkey = true
    root.controller.show()
    cacheFile.reload()
    Qt.callLater(function() {
      if (root.opened)
        setCenterHoverRevealSuppressed(true)
    })
  }

  function close() {
    setCenterHoverRevealSuppressed(false)
    root.controller.hide()
  }

  function toggle() {
    if (root.opened)
      root.close()
    else
      root.openFromHotkey()
  }

  function refresh() {
    cacheFile.reload()
  }

  function applyRaw(raw) {
    var next = Model.parseCache(raw)
    root.state = next
    root.barText = next.text
    root.barClass = next.klass
    root.barStyle = next.bar_style || "text"
  }

  function pluginDir() {
    var u = String(Qt.resolvedUrl("."))
    return u.replace(/^file:\/\//, "").replace(/\/$/, "")
  }

  function runTui() {
    if (root.bar)
      root.bar.run("omarchy-launch-or-focus-tui spaceflight")
  }

  function launchTerminalSetup() {
    var script = pluginDir() + "/scripts/launch-setup"
    if (root.bar)
      root.bar.run("/bin/bash " + script)
  }

  function openStream() {
    var url = root.state.featured && root.state.featured.stream_url
    if (url && root.bar)
      root.bar.run("xdg-open " + JSON.stringify(String(url)))
  }

  FileView {
    id: cacheFile
    path: Quickshell.env("HOME") + "/.cache/spaceflight/waybar.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.applyRaw(text())
    onLoadFailed: root.applyRaw("")
  }

  Timer {
    interval: root.refreshMs
    running: true
    repeat: true
    onTriggered: cacheFile.reload()
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(440))
    contentHeight: panel.fittedContentHeight(bodyCol.implicitHeight + Style.space(16))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: bodyCol.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: bodyCol
          width: parent.width
          spacing: Style.space(8)
          leftPadding: Style.space(14)
          rightPadding: Style.space(14)
          topPadding: Style.space(10)
          bottomPadding: Style.space(10)

          Text {
            visible: root.state.tooltip !== ""
            width: parent.width - parent.leftPadding - parent.rightPadding
            text: root.state.tooltip
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.cardFont
            font.pixelSize: Style.font.small
            wrapMode: Text.NoWrap
            lineHeight: 1.12
          }

          Text {
            visible: root.state.tooltip === "" && !root.state.ok
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: "Finish setup in the same terminal as omarchy plugin add. If that is gone, tap Run setup."
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
            opacity: 0.8
          }

          Row {
            spacing: Style.space(8)

            Rectangle {
              width: tuiLab.implicitWidth + Style.space(16)
              height: tuiLab.implicitHeight + Style.space(8)
              radius: 6
              color: Qt.rgba(1, 1, 1, 0.08)
              Text {
                id: tuiLab
                anchors.centerIn: parent
                text: "Open TUI"
                color: root.bar ? root.bar.foreground : Color.foreground
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.small
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.runTui()
              }
            }

            Rectangle {
              visible: !root.state.ok
              width: setupLab.implicitWidth + Style.space(16)
              height: setupLab.implicitHeight + Style.space(8)
              radius: 6
              color: Qt.rgba(1, 1, 1, 0.08)
              Text {
                id: setupLab
                anchors.centerIn: parent
                text: "Run setup"
                color: root.bar ? root.bar.foreground : Color.foreground
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.small
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.launchTerminalSetup()
              }
            }

            Rectangle {
              visible: !!(root.state.featured && root.state.featured.stream_url)
              width: watchLab.implicitWidth + Style.space(16)
              height: watchLab.implicitHeight + Style.space(8)
              radius: 6
              color: Qt.rgba(1, 1, 1, 0.08)
              Text {
                id: watchLab
                anchors.centerIn: parent
                text: "Watch"
                color: root.bar ? root.bar.foreground : Color.foreground
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.small
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.openStream()
              }
            }
          }
        }
      }
    }
  }
}
