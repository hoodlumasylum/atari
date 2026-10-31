import QtQuick

// Banner with the wordmark, the tab row (All Games ... Settings), Add Games, search and a live clock.
Item {
    id: tb
    property real u: 1
    property int activeTab: 0
    property int focusIndex: -1      // 0-4 tabs, 5 Add Games, 6 search, 7 WiFi, 8 previous, 9 play/pause, 10 next (music); -1 = nothing focused
    signal activated(int index)
    signal updateRequested()
    // 0 = everything at full size; each step makes the right-hand side (and at 4+ the tab labels) smaller so nothing overlaps
    property int squeeze: 0
    readonly property real gap: 24 * u
    function overlaps() { return rightRow.x < tabRow.x + tabRow.width + gap }
    function fit() { fitTimer.restart() }
    Timer {      // waits for the rows to lay out again before measuring, so it only squeezes as much as needed
        id: fitTimer
        interval: 40
        onTriggered: if (tb.overlaps() && tb.squeeze < 6) { tb.squeeze++; restart() }
    }
    function refit() { squeeze = 0; fit() }
    readonly property bool mediaOn: backend.media.active
    readonly property bool updOn: backend.updateAvailable
    readonly property string wifiText: backend.wifi.summary
    readonly property int padCount: backend.padBatteries.length
    onMediaOnChanged: refit()
    onUpdOnChanged: refit()
    onWifiTextChanged: refit()
    onPadCountChanged: refit()
    onWidthChanged: { squeeze = 0; fit() }
    onUChanged: { squeeze = 0; fit() }

    readonly property var tabs: [
        { label: "ALL GAMES", icon: "home" }, { label: "FAVOURITES", icon: "star" }, { label: "RECENT", icon: "clock" },
        { label: "SYSTEMS", icon: "pad" }, { label: "SETTINGS", icon: "gear" }
    ]

    Image {
        anchors.fill: parent
        source: Qt.resolvedUrl("../assets/banner.jpg")
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        sourceSize.width: 1920
        smooth: true
    }
    Rectangle {  // keep the tabs readable over the artwork
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#10000000" }
            GradientStop { position: 0.3; color: "#66000000" }
            GradientStop { position: 1.0; color: "#99000000" }
        }
    }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#33ffffff" }

    Wordmark {
        id: wm
        u: tb.u
        compact: true
        anchors.left: parent.left
        anchors.leftMargin: 34 * tb.u
        anchors.verticalCenter: parent.verticalCenter
    }

    Row {
        id: tabRow
        anchors.left: wm.right
        objectName: "tabRow"
        anchors.leftMargin: (tb.squeeze >= 4 ? 28 : 70) * tb.u
        anchors.verticalCenter: parent.verticalCenter
        spacing: (tb.squeeze >= 4 ? 5 : 8) * tb.u
        onWidthChanged: tb.fit()
        Repeater {
            model: tb.tabs
            Rectangle {
                id: tab
                required property var modelData
                required property int index
                readonly property bool active: index === tb.activeTab
                readonly property bool hot: index === tb.focusIndex
                height: 46 * tb.u
                width: tabRowInner.implicitWidth + (tb.squeeze >= 4 ? 24 : 36) * tb.u
                radius: height / 2
                color: active ? "#3a3012" : (hot ? "#26ffffff" : "#40000000")
                border.width: active || hot ? 2 * tb.u : 0
                border.color: active ? Theme.accent : "#cfd3e0"
                Rectangle {   // gold glow round the chosen tab
                    visible: tab.active
                    anchors.fill: parent; anchors.margins: -4 * tb.u
                    radius: height / 2; color: "transparent"
                    border.width: 4 * tb.u; border.color: Theme.accentGlow
                }
                Row {
                    id: tabRowInner
                    anchors.centerIn: parent
                    spacing: 9 * tb.u
                    Icon { scale: tab.hot ? 1.2 : 1.0; Behavior on scale { enabled: Theme.anim; NumberAnimation { duration: 140; easing.type: Easing.OutBack } }
                           name: tab.modelData.icon; size: 22 * tb.u; color: tab.active ? Theme.accent : "#d6d9e6"
                           anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: tb.squeeze < 5 || tab.active
                        text: tab.modelData.label
                        color: tab.active ? "white" : "#d6d9e6"
                        font.pixelSize: 16 * tb.u
                        font.bold: true
                        font.letterSpacing: 0.8 * tb.u
                    }
                }
                MouseArea { anchors.fill: parent; onClicked: tb.activated(tab.index) }
            }
        }
        Rectangle {  // the prominent Add Games button
            id: addBtn
            readonly property bool hot: tb.focusIndex === 5
            height: 46 * tb.u
            objectName: "addGamesButton"
            width: addRow.implicitWidth + 36 * tb.u
            radius: height / 2
            gradient: Gradient {
                GradientStop { position: 0; color: addBtn.hot ? "#ff4a52" : "#ee2a34" }
                GradientStop { position: 1; color: addBtn.hot ? "#c4161f" : "#a8121b" }
            }
            border.width: addBtn.hot ? 3 * tb.u : 0
            border.color: "white"
            Row {
                id: addRow
                anchors.centerIn: parent
                spacing: 8 * tb.u
                Icon { name: "plus"; size: 22 * tb.u; color: "white"; stroke: 2.8; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "ADD GAMES"
                    color: "white"
                    font.pixelSize: 16 * tb.u
                    font.bold: true
                    font.letterSpacing: 0.8 * tb.u
                }
            }
            MouseArea { anchors.fill: parent; onClicked: tb.activated(5) }
        }
    }

    Row {
        id: rightRow
        objectName: "rightRow"
        anchors.right: parent.right
        anchors.rightMargin: (tb.squeeze >= 3 ? 18 : 36) * tb.u
        anchors.verticalCenter: parent.verticalCenter
        spacing: (tb.squeeze >= 2 ? 10 : tb.squeeze >= 1 ? 16 : 22) * tb.u
        onWidthChanged: tb.fit()
        Rectangle {   // a newer CodeAque release exists (found by the quiet daily check)
            visible: backend.updateAvailable
            anchors.verticalCenter: parent.verticalCenter
            height: 34 * tb.u
            width: updText.implicitWidth + 26 * tb.u
            radius: height / 2
            color: "#1d3a1f"
            border.width: 1.5 * tb.u
            border.color: Theme.green
            Text { id: updText; anchors.centerIn: parent; text: "UPDATE " + backend.updateVersion; color: "#bff0c0"
                   font.pixelSize: 14 * tb.u; font.bold: true; font.letterSpacing: 0.8 * tb.u }
            MouseArea { anchors.fill: parent; onClicked: tb.updateRequested() }
        }
        Rectangle {
            id: searchBtn
            objectName: "searchButton"
            width: 46 * tb.u
            height: 46 * tb.u
            radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            color: tb.focusIndex === 6 ? "#26ffffff" : "#40000000"
            border.width: tb.focusIndex === 6 ? 2 * tb.u : 0
            border.color: "#cfd3e0"
            Icon { anchors.centerIn: parent; name: "search"; size: 24 * tb.u; color: "white" }
            MouseArea { anchors.fill: parent; onClicked: tb.activated(6) }
        }
        Rectangle {   // WiFi: the network name (or Cable / No WiFi) - press to open the WiFi screen
            id: wifiBtn
            objectName: "wifiButton"
            readonly property bool hot: tb.focusIndex === 7
            anchors.verticalCenter: parent.verticalCenter
            height: 46 * tb.u
            width: wifiRow.implicitWidth + 30 * tb.u
            radius: height / 2
            color: hot ? "#26ffffff" : "#40000000"
            border.width: hot ? 2 * tb.u : 0
            border.color: "#cfd3e0"
            Row {
                id: wifiRow
                anchors.centerIn: parent
                spacing: 9 * tb.u
                Icon { name: "wifi"; size: 24 * tb.u; color: backend.wifi.summary === "Offline" || backend.wifi.summary === "No WiFi" || backend.wifi.summary === "WiFi off" ? Theme.faint : "white"
                       anchors.verticalCenter: parent.verticalCenter }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: text !== "" && tb.squeeze < 2
                    text: backend.wifi.summary.length > 16 ? backend.wifi.summary.substring(0, 15) + "\u2026" : backend.wifi.summary
                    color: "#d6d9e6"; font.pixelSize: 15 * tb.u; font.bold: true
                }
            }
            MouseArea { anchors.fill: parent; onClicked: tb.activated(7) }
        }
        Row {   // music in the background (Spotify & co. through MPRIS / playerctl): only there while something is playing or paused
            id: mediaRow
            objectName: "mediaControl"
            visible: backend.media.active
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6 * tb.u
            Repeater {
                model: [ { act: "previous", idx: 8, sym: "\u23EE" }, { act: "play-pause", idx: 9, sym: "" }, { act: "next", idx: 10, sym: "\u23ED" } ]
                Rectangle {
                    required property var modelData
                    readonly property bool hot: tb.focusIndex === modelData.idx
                    objectName: "media_" + modelData.act
                    anchors.verticalCenter: parent.verticalCenter
                    width: 40 * tb.u; height: 40 * tb.u; radius: width / 2
                    color: hot ? "#26ffffff" : "#40000000"
                    border.width: hot ? 2 * tb.u : 0
                    border.color: "#cfd3e0"
                    Text { anchors.centerIn: parent; color: "white"; font.pixelSize: 18 * tb.u; font.bold: true
                           text: modelData.act === "play-pause" ? (backend.media.playing ? "\u23F8" : "\u25B6") : modelData.sym }
                    MouseArea { anchors.fill: parent; onClicked: tb.activated(modelData.idx) }
                }
            }
            Text {
                objectName: "mediaText"
                anchors.verticalCenter: parent.verticalCenter
                visible: tb.squeeze < 2
                width: Math.min(implicitWidth, (tb.squeeze >= 1 ? 120 : 230) * tb.u)
                elide: Text.ElideRight
                text: backend.media.text
                color: "#d6d9e6"; font.pixelSize: 14 * tb.u
            }
        }
        Rectangle {   // quick brightness: drag (or tap) along the bar; the sun opens Settings > Brightness
            id: brPill
            objectName: "brightnessPill"
            anchors.verticalCenter: parent.verticalCenter
            height: 34 * tb.u
            width: (tb.squeeze >= 3 ? 96 : tb.squeeze >= 1 ? 130 : 170) * tb.u
            radius: height / 2
            color: "#40000000"
            property int shown: backend.brightness >= 0 ? backend.brightness : 70
            Text { id: sun; x: 10 * tb.u; anchors.verticalCenter: parent.verticalCenter; text: "\u2600"; color: "#e8c15a"; font.pixelSize: 18 * tb.u }
            Rectangle {
                id: brTrack
                x: 36 * tb.u; width: parent.width - (pctText.visible ? 80 : 48) * tb.u; height: 6 * tb.u; radius: 3 * tb.u
                anchors.verticalCenter: parent.verticalCenter
                color: "#55ffffff"
                Rectangle { width: parent.width * brPill.shown / 100; height: parent.height; radius: parent.radius; color: "#e8c15a" }
                Rectangle { x: parent.width * brPill.shown / 100 - width / 2; anchors.verticalCenter: parent.verticalCenter
                            width: 14 * tb.u; height: width; radius: width / 2; color: "white" }
            }
            Text { id: pctText; visible: tb.squeeze < 1; anchors.right: parent.right; anchors.rightMargin: 8 * tb.u; anchors.verticalCenter: parent.verticalCenter
                   text: brPill.shown + "%"; color: "#d6d9e6"; font.pixelSize: 13 * tb.u }
            MouseArea {
                anchors.fill: brTrack; anchors.margins: -12 * tb.u
                property int pending: -1
                function at(mx) { return Math.max(5, Math.min(100, Math.round((mx - 12 * tb.u) / brTrack.width * 100))) }
                onPressed: function (m) { pending = at(m.x); brPill.shown = pending }
                onPositionChanged: function (m) { pending = at(m.x); brPill.shown = pending }
                onReleased: { if (pending >= 0) backend.setBrightness(pending); pending = -1 }
            }
            Connections { target: backend; function onBrightnessChanged() { brPill.shown = backend.brightness >= 0 ? backend.brightness : 70 } }
        }
        Row {   // a small battery pill for each connected controller that reports one (or "Battery unknown" for a wireless pad)
            objectName: "padBatteries"
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6 * tb.u
            Rectangle {     // always there: with no pad, a way to pair one
                objectName: "noPadPill"
                visible: backend.padBatteries.length === 0
                height: 34 * tb.u
                width: noPadRow.implicitWidth + 20 * tb.u
                radius: height / 2
                color: "#40000000"
                Row {
                    id: noPadRow
                    anchors.centerIn: parent
                    spacing: 6 * tb.u
                    Icon { name: "pad"; size: 18 * tb.u; color: "#9aa0b4"; anchors.verticalCenter: parent.verticalCenter }
                    Text { anchors.verticalCenter: parent.verticalCenter; visible: tb.squeeze < 3; text: backend.padsWaiting.length ? (tb.squeeze >= 1 ? "Press PS" : "Pad: press PS to connect") : (tb.squeeze >= 1 ? "Pair controller" : "No controller - tap to pair"); color: "#c9cdda"; font.pixelSize: 14 * tb.u }
                }
                MouseArea { anchors.fill: parent; onClicked: backend.openControllerPill() }
            }
            Repeater {
                model: backend.padBatteries
                Rectangle {
                    required property var modelData
                    objectName: "padBattery"
                    property string label: modelData.text
                    height: 34 * tb.u
                    width: battRow.implicitWidth + 20 * tb.u
                    radius: height / 2
                    color: modelData.low ? "#a01822" : "#40000000"
                    border.width: modelData.low ? 2 * tb.u : 0
                    border.color: "white"
                    MouseArea { anchors.fill: parent; onClicked: backend.openControllerPill() }
                    Row {
                        id: battRow
                        anchors.centerIn: parent
                        spacing: 6 * tb.u
                        Icon { name: "pad"; size: 18 * tb.u; color: modelData.charging ? Theme.green : "#d6d9e6"; anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: (modelData.low ? "LOW " : "") + modelData.text
                            color: modelData.known ? "white" : "#9aa0b4"
                            font.pixelSize: 14 * tb.u
                            font.bold: modelData.low
                        }
                    }
                }
            }
        }
        Text {
            id: clock
            objectName: "clock"
            visible: tb.squeeze < 6
            anchors.verticalCenter: parent.verticalCenter
            property string stamp: Qt.formatTime(new Date(), "HH:mm")
            text: stamp
            color: "white"
            font.pixelSize: 26 * tb.u
            font.bold: true
            Timer {
                interval: 1000
                running: true
                repeat: true
                onTriggered: clock.stamp = Qt.formatTime(new Date(), "HH:mm")
            }
        }
    }
}
