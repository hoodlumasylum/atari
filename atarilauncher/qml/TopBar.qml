import QtQuick

// Banner with the wordmark, the tab row (All Games ... Settings), Add Games, search and a live clock.
Item {
    id: tb
    property real u: 1
    property int activeTab: 0
    property int focusIndex: -1      // 0-4 tabs, 5 Add Games, 6 search; -1 = nothing focused
    signal activated(int index)
    signal updateRequested()

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
        anchors.left: parent.left
        anchors.leftMargin: 34 * tb.u
        anchors.verticalCenter: parent.verticalCenter
    }

    Row {
        id: tabRow
        anchors.left: wm.right
        anchors.leftMargin: 70 * tb.u
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8 * tb.u
        Repeater {
            model: tb.tabs
            Rectangle {
                id: tab
                required property var modelData
                required property int index
                readonly property bool active: index === tb.activeTab
                readonly property bool hot: index === tb.focusIndex
                height: 46 * tb.u
                width: tabRowInner.implicitWidth + 36 * tb.u
                radius: height / 2
                color: active ? "#3a0a10" : (hot ? "#26ffffff" : "#40000000")
                border.width: active || hot ? 2 * tb.u : 0
                border.color: active ? Theme.redBright : "#cfd3e0"
                Row {
                    id: tabRowInner
                    anchors.centerIn: parent
                    spacing: 9 * tb.u
                    Icon { scale: tab.hot ? 1.2 : 1.0; Behavior on scale { enabled: Theme.anim; NumberAnimation { duration: 140; easing.type: Easing.OutBack } }
                           name: tab.modelData.icon; size: 22 * tb.u; color: tab.active ? "white" : "#d6d9e6"
                           anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
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
        anchors.right: parent.right
        anchors.rightMargin: 36 * tb.u
        anchors.verticalCenter: parent.verticalCenter
        spacing: 26 * tb.u
        Rectangle {   // a newer Atari release exists (found by the quiet daily check)
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
        Text {
            id: clock
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
