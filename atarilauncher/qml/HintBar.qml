import QtQuick

// Controller hints along the bottom (they really work: see gamepad_helper.py and the key handling in Main.qml).
Rectangle {
    id: hb
    property real u: 1
    color: Theme.fx ? "#800a0b12" : "#e60b0c13"
    Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.line }
    readonly property var hints: [
        { k: "A", t: "SELECT" }, { k: "B", t: "BACK" }, { k: "X", t: "FAVOURITE" }, { k: "Y", t: "OPTIONS" },
        { k: "menu", t: "CHANGE SYSTEM" }, { k: "LB", t: "PREVIOUS" }, { k: "RB", t: "NEXT" }, { k: "R3", t: "GRID / LIST" }
    ]
    Row {
        anchors.centerIn: parent
        spacing: 34 * hb.u
        Repeater {
            model: hb.hints
            Row {
                required property var modelData
                spacing: 10 * hb.u
                PadButton { kind: modelData.k; u: hb.u; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.t
                    color: "#d6d9e6"
                    font.pixelSize: 18 * hb.u
                    font.letterSpacing: 1.2 * hb.u
                }
            }
        }
    }
}
