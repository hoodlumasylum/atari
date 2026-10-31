import QtQuick

// A controller-button glyph drawn by CodeAque (no maker logos). style "xbox": A B X Y in their usual colours, the Menu (three
// lines) and View buttons, LB / RB. style "ps": cross / circle / square / triangle shapes in PlayStation-like colours, OPTIONS /
// SHARE, L1 / R1. kind is always the Xbox name (A B X Y menu view LB RB); the style turns it into the other layout.
Item {
    id: pb
    property string kind: "A"
    property real u: 1
    property string style: (typeof backend !== "undefined" && backend) ? backend.padStyle : "xbox"
    readonly property bool ps: style === "ps"
    readonly property bool shoulder: kind === "LB" || kind === "RB"
    readonly property bool pill: kind === "menu" || kind === "view"
    readonly property bool face: !shoulder && !pill
    readonly property string psShape: kind === "A" ? "cross" : kind === "B" ? "circle" : kind === "X" ? "square" : kind === "Y" ? "triangle" : ""
    readonly property color tint: ps ? (kind === "A" ? "#7ea4e8" : kind === "B" ? "#ec6a73" : kind === "X" ? "#e08fcf" : "#45c4a6")
                                     : (kind === "A" ? Theme.green : kind === "B" ? Theme.red : kind === "X" ? Theme.blue
                                        : kind === "Y" ? Theme.yellow : "#cfd3e0")
    readonly property string label: shoulder ? (ps ? (kind === "LB" ? "L1" : "R1") : kind)
                                  : pill ? (ps ? (kind === "menu" ? "OPTIONS" : "SHARE") : "") : (ps ? "" : kind)
    objectName: "padButton_" + kind
    width: (shoulder ? 54 : (pill && ps) ? 84 : 34) * u
    height: 34 * u

    Rectangle {
        anchors.fill: parent
        radius: pb.shoulder || (pb.pill && pb.ps) ? 8 * pb.u : width / 2
        color: pb.shoulder ? "transparent" : pb.pill ? "#2b2f42" : (pb.ps ? "#1b1e2b" : pb.tint)
        border.width: pb.shoulder || pb.pill ? 2 * pb.u : (pb.ps ? 2 * pb.u : 0)
        border.color: pb.ps && pb.face ? pb.tint : "#cfd3e0"
        Text {
            visible: pb.label !== ""
            anchors.centerIn: parent
            text: pb.label
            color: pb.shoulder || pb.pill ? "#e6e8f0" : (pb.kind === "Y" ? "#241a00" : "white")
            font.pixelSize: (pb.pill ? 13 : pb.shoulder ? 17 : 20) * pb.u
            font.bold: true
        }
        Column {   // Xbox Menu: three lines
            visible: pb.kind === "menu" && !pb.ps
            anchors.centerIn: parent
            spacing: 3.5 * pb.u
            Repeater { model: 3; Rectangle { width: 14 * pb.u; height: 2.4 * pb.u; radius: 1.2 * pb.u; color: "#e6e8f0" } }
        }
        Item {     // Xbox View: two small overlapping squares
            visible: pb.kind === "view" && !pb.ps
            anchors.centerIn: parent; width: 16 * pb.u; height: 13 * pb.u
            Rectangle { x: 0; y: 3 * pb.u; width: 10 * pb.u; height: 9 * pb.u; color: "transparent"; border.width: 1.8 * pb.u; border.color: "#e6e8f0" }
            Rectangle { x: 5 * pb.u; y: 0; width: 10 * pb.u; height: 9 * pb.u; color: "#2b2f42"; border.width: 1.8 * pb.u; border.color: "#e6e8f0" }
        }
        Canvas {   // PlayStation-style face shapes, drawn here
            id: shape
            visible: pb.ps && pb.face
            anchors.centerIn: parent
            width: 18 * pb.u; height: 18 * pb.u
            property string s: pb.psShape
            property color c: pb.tint
            onSChanged: requestPaint()
            onCChanged: requestPaint()
            onVisibleChanged: requestPaint()
            onPaint: {
                var g = getContext("2d"); g.reset()
                g.strokeStyle = c; g.lineWidth = 2.6 * pb.u; g.lineCap = "round"; g.lineJoin = "round"
                var w = width, h = height, m = 2.5 * pb.u
                g.beginPath()
                if (s === "cross") { g.moveTo(m, m); g.lineTo(w - m, h - m); g.moveTo(w - m, m); g.lineTo(m, h - m) }
                else if (s === "circle") { g.arc(w / 2, h / 2, w / 2 - m, 0, 2 * Math.PI) }
                else if (s === "square") { g.rect(m, m, w - 2 * m, h - 2 * m) }
                else if (s === "triangle") { g.moveTo(w / 2, m); g.lineTo(w - m, h - m * 1.4); g.lineTo(m, h - m * 1.4); g.closePath() }
                g.stroke()
            }
        }
    }
}
