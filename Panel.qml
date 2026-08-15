import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

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

  readonly property int refreshMs: {
    var n = 1000
    if (root.settings && typeof root.settings.refreshMs !== "undefined")
      n = Number(root.settings.refreshMs)
    return Model.clampInt(n, 250, 10000, 1000)
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
  }

  function runTui() {
    if (root.bar)
      root.bar.run("omarchy-launch-or-focus-tui spaceflight")
  }

  function runSetup() {
    if (root.bar)
      root.bar.run("omarchy-launch-or-focus-tui spaceflight setup")
  }

  function runRefresh() {
    if (root.bar)
      root.bar.run("spaceflight refresh")
    Qt.callLater(root.refresh)
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
    contentWidth: panel.fittedContentWidth(Style.space(420))
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
          leftPadding: Style.space(16)
          rightPadding: Style.space(16)
          topPadding: Style.space(12)
          bottomPadding: Style.space(12)

          Text {
            width: parent.width - parent.leftPadding - parent.rightPadding
            text: "SPACEFLIGHT"
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
            font.letterSpacing: 1.2
          }

          Text {
            visible: root.state.onboard || !root.state.ok
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: "No launch cache yet. Install the CLI, enable the user daemon, then refresh."
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
            opacity: 0.8
          }

          Text {
            visible: root.state.ok
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: {
              var f = root.state.featured || {}
              return (f.glyph || "🚀") + "  " + (f.provider_abbr || "") + "  " + (f.countdown || "")
            }
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.display
            font.bold: true
          }

          Text {
            visible: root.state.ok
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: Model.featuredName(root.state.featured)
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
            font.bold: true
          }

          Text {
            visible: root.state.ok
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: {
              var f = root.state.featured || {}
              var bits = []
              if (f.vehicle)
                bits.push(f.vehicle)
              if (f.status)
                bits.push(f.status)
              if (f.live)
                bits.push("LIVE")
              if (f.hold)
                bits.push("HOLD")
              if (f.scrub)
                bits.push("SCRUB")
              return bits.join("  ·  ")
            }
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
            opacity: 0.75
          }

          Text {
            visible: root.state.ok && Model.locationLine(root.state.featured) !== ""
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: Model.locationLine(root.state.featured)
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
            opacity: 0.75
          }

          Text {
            visible: root.state.ok && root.state.featured && root.state.featured.net_local
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: {
              var f = root.state.featured || {}
              return "NET  " + (f.net_local || "") + "\n     " + (f.net_utc || "")
            }
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
          }

          Text {
            visible: root.state.ok && root.state.featured && root.state.featured.window
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: "Window  " + ((root.state.featured && root.state.featured.window) || "")
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
          }

          Text {
            visible: root.state.ok && root.state.featured && (root.state.featured.stage_now || root.state.featured.stage_next)
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: {
              var f = root.state.featured || {}
              var lines = []
              if (f.stage_now)
                lines.push("Now   ·  " + f.stage_now)
              if (f.stage_next)
                lines.push("Next  ·  " + f.stage_next)
              return lines.join("\n")
            }
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
          }

          Text {
            visible: root.state.ok && root.state.featured && root.state.featured.weather
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: (root.state.featured && root.state.featured.weather) || ""
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
            opacity: 0.8
          }

          Repeater {
            model: root.state.upcoming || []
            delegate: Text {
              required property var modelData
              required property int index
              width: bodyCol.width - bodyCol.leftPadding - bodyCol.rightPadding
              visible: index < Model.MAX_UPCOMING
              text: (modelData.glyph || "·") + "  "
                    + (modelData.provider_abbr || "") + "  "
                    + (modelData.countdown || "") + "  "
                    + (modelData.status || "") + "  "
                    + (modelData.name || "")
              color: root.bar ? root.bar.foreground : Color.foreground
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.small
              opacity: 0.8
              wrapMode: Text.NoWrap
              elide: Text.ElideRight
            }
          }

          Text {
            width: parent.width - parent.leftPadding - parent.rightPadding
            text: "data " + Model.ageLabel(root.state.age_sec)
                  + "   ·   click TUI  ·   middle refresh  ·   n stages in TUI"
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
            opacity: 0.55
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
              width: setupLab.implicitWidth + Style.space(16)
              height: setupLab.implicitHeight + Style.space(8)
              radius: 6
              color: Qt.rgba(1, 1, 1, 0.08)
              Text {
                id: setupLab
                anchors.centerIn: parent
                text: "Phone setup"
                color: root.bar ? root.bar.foreground : Color.foreground
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.small
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.runSetup()
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
