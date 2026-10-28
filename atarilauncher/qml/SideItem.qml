import QtQuick

// A row of the left sidebar: icon + label, red when it is the list being shown.
Rectangle {
    id: si
    property string icon: "pad"
    property string label: ""
    property real u: 1
    property bool active: false
    property bool focused: false
    signal clicked()
    height: 46 * u
    radius: 8 * u
    color: active ? "#2a0b10" : (focused ? "#1a1d2c" : "transparent")
    border.width: active ? 2 * u : (focused ? 1.5 * u : 0)
    border.color: active ? Theme.red : "#3a4260"
    Icon {
        id: ic
        anchors.left: parent.left
        anchors.leftMargin: 14 * si.u
        anchors.verticalCenter: parent.verticalCenter
        name: si.icon
        size: 24 * si.u
        color: si.active ? Theme.redBright : "#c4c8da"
    }
    Text {
        anchors.left: ic.right
        anchors.leftMargin: 14 * si.u
        anchors.right: parent.right
        anchors.rightMargin: 10 * si.u
        anchors.verticalCenter: parent.verticalCenter
        elide: Text.ElideRight
        text: si.label
        color: si.active ? "white" : "#dfe2ee"
        font.pixelSize: 20 * si.u
        font.bold: si.active
    }
    MouseArea { anchors.fill: parent; onClicked: si.clicked() }
}
