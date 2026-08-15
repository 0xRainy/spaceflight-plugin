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
  property string barStyle: state.bar_style || "text"
  property bool wizardOpen: false
  property int wizardStep: 0
  property string draftTopic: ""
  property string wizardNote: ""

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
    root.barStyle = next.bar_style || "text"
  }

  function launchTerminalSetup() {
    var script = pluginDir() + "/scripts/plugin-setup"
    if (root.bar)
      root.bar.run("omarchy-launch-or-focus-tui --app-id=org.omarchy.spaceflight-setup " + script)
    else
      root.runPy(["plugin-setup"])
  }

  function pluginDir() {
    var u = String(Qt.resolvedUrl("."))
    return u.replace(/^file:\/\//, "").replace(/\/$/, "")
  }

  property var pyQueue: []

  function runPy(args) {
    root.pyQueue.push(args)
    if (!helperProc.running)
      root.pumpPy()
  }

  function pumpPy() {
    if (root.pyQueue.length < 1)
      return
    var args = root.pyQueue.shift()
    var dir = pluginDir()
    var cmd = ["env", "PYTHONPATH=" + dir, "python3", "-m", "spaceflight"]
    var i
    for (i = 0; i < args.length && i < 8; i++)
      cmd.push(args[i])
    helperProc.command = cmd
    helperProc.running = true
  }

  function finishWizard() {
    runPy(["setup", "--wizard-done"])
    root.wizardOpen = false
    root.wizardStep = 0
    cacheFile.reload()
  }

  function wizardPick(label) {
    if (root.wizardStep === 0) {
      var style = (label.indexOf("icon") >= 0) ? "icon" : "text"
      runPy(["settings", "--bar-style", style])
      root.barStyle = style
      root.wizardStep = 1
      return
    }
    if (root.wizardStep === 1) {
      var sec = String(label).toLowerCase()
      runPy(["settings", "--bar-section", sec])
      root.wizardStep = 2
      return
    }
    if (root.wizardStep === 2) {
      if (label.indexOf("Skip") === 0) {
        runPy(["setup", "--clear-topic"])
        root.wizardStep = 4
        return
      }
      if (label.indexOf("Generate") === 0) {
        root.wizardStep = 3
        runPy(["setup", "--generate-topic"])
        return
      }
      var typed = topicInput.text ? String(topicInput.text).trim() : ""
      if (typed.length >= 12) {
        runPy(["setup", "--set-topic", typed])
        root.draftTopic = typed
        root.wizardStep = 3
        return
      }
      root.wizardNote = "Paste a topic of at least 12 characters, or generate one."
      return
    }
    if (root.wizardStep === 3) {
      if (label.indexOf("Skip") === 0) {
        root.wizardStep = 4
        return
      }
      if (root.draftTopic)
        runPy(["setup", "--set-topic", root.draftTopic])
      runPy(["notify-test", "--phone"])
      root.wizardStep = 4
      return
    }
    finishWizard()
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

  Process {
    id: helperProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var raw = String(text || "").trim()
        if (raw.indexOf("spaceflight-") === 0) {
          root.draftTopic = raw.split(/\s+/)[0]
          root.runPy(["setup", "--set-topic", root.draftTopic])
        }
        if (raw)
          root.wizardNote = raw
        cacheFile.reload()
      }
    }
    onExited: root.pumpPy()
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

          Column {
            id: wizardCol
            visible: root.wizardOpen
            width: parent.width - parent.leftPadding - parent.rightPadding
            spacing: Style.space(8)

            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              text: root.wizardStep === 0
                ? "Welcome to Spaceflight. The CLI and launch daemon install in the background. How should the bar look?"
                : (root.wizardStep === 1
                  ? "Where should the rocket sit on the bar? (You can change this later in the TUI — press s.)"
                  : (root.wizardStep === 2
                    ? "Phone alerts use the free ntfy app. The topic is a unique secret key — anyone with it can read your alerts. You will need the ntfy app on your phone."
                    : (root.wizardStep === 3
                      ? "Open ntfy on your phone → Subscribe → paste this key. Wait until it shows as subscribed, then tap below."
                      : "You're set. Click the bar anytime for launch details. Right-click opens the TUI. Press s in the TUI to change bar place or the ntfy topic.")))
              color: root.bar ? root.bar.foreground : Color.foreground
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.body
            }

            Text {
              visible: root.wizardStep === 3 && root.draftTopic !== ""
              width: parent.width
              wrapMode: Text.WrapAnywhere
              text: root.draftTopic
              color: root.bar ? root.bar.foreground : Color.foreground
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.body
              font.bold: true
            }

            Flow {
              width: parent.width
              spacing: Style.space(8)

              Repeater {
                model: root.wizardStep === 0
                  ? ["🚀 icon only", "Countdown text"]
                  : (root.wizardStep === 1
                    ? ["Left", "Center", "Right"]
                    : (root.wizardStep === 2
                      ? ["Skip phone", "Generate a key", "I have a key"]
                      : (root.wizardStep === 3
                        ? ["I've subscribed", "Skip phone"]
                        : ["Done"])))
                delegate: Rectangle {
                  required property string modelData
                  width: choiceLab.implicitWidth + Style.space(16)
                  height: choiceLab.implicitHeight + Style.space(10)
                  radius: 6
                  color: Qt.rgba(1, 1, 1, 0.10)
                  Text {
                    id: choiceLab
                    anchors.centerIn: parent
                    text: modelData
                    color: root.bar ? root.bar.foreground : Color.foreground
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.small
                  }
                  MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.wizardPick(modelData)
                  }
                }
              }
            }

            TextInput {
              id: topicInput
              visible: root.wizardStep === 2
              width: parent.width
              color: root.bar ? root.bar.foreground : Color.foreground
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.small
              text: ""
            }

            Text {
              visible: root.wizardNote !== ""
              width: parent.width
              wrapMode: Text.WordWrap
              text: root.wizardNote
              color: root.bar ? root.bar.foreground : Color.foreground
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.small
              opacity: 0.7
            }
          }

          Text {
            visible: !root.wizardOpen
            width: parent.width - parent.leftPadding - parent.rightPadding
            text: "SPACEFLIGHT"
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
            font.letterSpacing: 1.2
          }

          Text {
            visible: !root.wizardOpen && (root.state.onboard || !root.state.ok)
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: "Setup runs in a terminal after you add the plugin. If that window isn't open, tap below."
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
            opacity: 0.8
          }

          Text {
            visible: !root.wizardOpen && root.state.ok
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
            visible: !root.wizardOpen && root.state.ok
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: Model.featuredName(root.state.featured)
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
            font.bold: true
          }

          Text {
            visible: !root.wizardOpen && root.state.ok
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
            visible: !root.wizardOpen && root.state.ok && Model.locationLine(root.state.featured) !== ""
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: Model.locationLine(root.state.featured)
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
            opacity: 0.75
          }

          Text {
            visible: !root.wizardOpen && root.state.ok && root.state.featured && root.state.featured.net_local
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
            visible: !root.wizardOpen && root.state.ok && root.state.featured && root.state.featured.window
            width: parent.width - parent.leftPadding - parent.rightPadding
            wrapMode: Text.WordWrap
            text: "Window  " + ((root.state.featured && root.state.featured.window) || "")
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.small
          }

          Text {
            visible: !root.wizardOpen && root.state.ok && root.state.featured && (root.state.featured.stage_now || root.state.featured.stage_next)
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
            visible: !root.wizardOpen && root.state.ok && root.state.featured && root.state.featured.weather
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
                text: "Run setup in terminal"
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
