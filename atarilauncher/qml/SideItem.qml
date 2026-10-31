import QtQuick

// A row of the left sidebar: icon + label, red when it is the list being shown.
Rectangle {
    id: si
    property string icon: "pad"
    property string label: ""
    property real u: 1
    property bool active: false
    property bool focused: false
    property int count: -1           // number of games (shown on the right), -1 = none
    signal clicked()
    height: 46 * u
    radius: 8 * u
    color: active ? "#2a2410" : (focused ? "#1a1d2c" : "transparent")
    border.width: active ? 2 * u : (focused ? 1.5 * u : 0)
    border.color: active ? Theme.accent : "#3a4260"
    Icon {
        id: ic
        anchors.left: parent.left
        anchors.leftMargin: 14 * si.u
        anchors.verticalCenter: parent.verticalCenter
        name: si.icon
        size: 24 * si.u
        color: si.active ? Theme.accent : "#c4c8da"
        scale: si.focused || si.active ? 1.15 : 1.0
        Behavior on scale { enabled: Theme.anim; NumberAnimation { duration: 140; easing.type: Easing.OutBack } }
    }
    Text {
        anchors.left: ic.right
        anchors.leftMargin: 14 * si.u
        anchors.right: cnt.visible ? cnt.left : parent.right
        anchors.rightMargin: 10 * si.u
        anchors.verticalCenter: parent.verticalCenter
        elide: Text.ElideRight
        text: si.label
        color: si.active ? "white" : "#dfe2ee"
        font.pixelSize: 20 * si.u
        font.bold: si.active
    }
    Rectangle {
        id: cnt
        visible: si.count >= 0
        anchors.right: parent.right
        anchors.rightMargin: 10 * si.u
        anchors.verticalCenter: parent.verticalCenter
        height: 26 * si.u
        width: Math.max(34 * si.u, cntText.implicitWidth + 16 * si.u)
        radius: 13 * si.u
        color: si.active ? "#40e8c25a" : "#1c2030"
        Text { id: cntText; anchors.centerIn: parent; text: si.count; color: si.active ? "white" : "#aab0c4"
               font.pixelSize: 15 * si.u; font.bold: true }
    }
    MouseArea { anchors.fill: parent; onClicked: si.clicked() }
}
