import QtQuick
import QtQuick.Window

// A tiny "REC 00:12" badge in the top-right corner, always on top and click-through, shown while the screen recorder runs
// (so you can see it over a full-screen game or web app). Best effort: some window managers keep full-screen windows on top.
Window {
    id: ind
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
    color: "transparent"
    width: 170
    height: 44
    visible: backend.recording
    x: Screen.width - width - 24
    y: 20
    Rectangle {
        anchors.fill: parent
        radius: 22
        color: "#d9120508"
        border.width: 2
        border.color: "#ee2a34"
        Row {
            anchors.centerIn: parent
            spacing: 10
            Rectangle {
                width: 16; height: 16; radius: 8; color: "#ff2a34"
                anchors.verticalCenter: parent.verticalCenter
                SequentialAnimation on opacity {
                    running: ind.visible; loops: Animation.Infinite
                    NumberAnimation { to: 0.25; duration: 600 }
                    NumberAnimation { to: 1.0; duration: 600 }
                }
            }
            Text { text: backend.recText; color: "white"; font.pixelSize: 20; font.bold: true; anchors.verticalCenter: parent.verticalCenter }
        }
    }
}
