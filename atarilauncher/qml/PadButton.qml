import QtQuick

// A round controller-button glyph (A B X Y), the menu (three lines) button, or LB / RB shoulder buttons.
Item {
    id: pb
    property string kind: "A"
    property real u: 1
    readonly property bool shoulder: kind === "LB" || kind === "RB"
    readonly property color tint: kind === "A" ? Theme.green : kind === "B" ? Theme.red
                                : kind === "X" ? Theme.blue : kind === "Y" ? Theme.yellow : "#cfd3e0"
    width: (shoulder ? 54 : 34) * u
    height: 34 * u
    Rectangle {
        anchors.fill: parent
        radius: pb.shoulder ? 8 * pb.u : width / 2
        color: pb.shoulder ? "transparent" : (pb.kind === "menu" ? "#2b2f42" : pb.tint)
        border.width: pb.shoulder ? 2 * pb.u : (pb.kind === "menu" ? 2 * pb.u : 0)
        border.color: pb.kind === "menu" ? "#cfd3e0" : "#cfd3e0"
        Text {
            visible: pb.kind !== "menu"
            anchors.centerIn: parent
            text: pb.kind
            color: pb.shoulder ? "#e6e8f0" : (pb.kind === "Y" ? "#241a00" : "white")
            font.pixelSize: (pb.shoulder ? 17 : 20) * pb.u
            font.bold: true
        }
        Column {
            visible: pb.kind === "menu"
            anchors.centerIn: parent
            spacing: 3.5 * pb.u
            Repeater {
                model: 3
                Rectangle { width: 14 * pb.u; height: 2.4 * pb.u; radius: 1.2 * pb.u; color: "#e6e8f0" }
            }
        }
    }
}
