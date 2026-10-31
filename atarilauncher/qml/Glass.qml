import QtQuick
import QtQuick.Effects

// A frosted-glass panel: see-through dark tint over the blurred backdrop, a fine light edge, a soft highlight at the top and
// (with effects on) a soft shadow. Put content inside it as children. "Reduce effects" = a plain, slightly more solid panel.
Item {
    id: g
    property real u: 1
    property real radius: 20 * u
    property color tint: Theme.fx ? "#9c0c0f17" : "#e00d0f18"
    property color edge: "#26ffffff"
    property real edgeWidth: 1 * u
    property bool shadow: true
    property bool highlighted: false
    default property alias content: inner.data

    MultiEffect {
        visible: Theme.fx && g.shadow
        source: shape
        anchors.fill: shape
        shadowEnabled: true
        shadowColor: "#b0000000"
        shadowBlur: 0.9
        shadowVerticalOffset: 6 * g.u
        shadowScale: 1.0
        paddingRect: Qt.rect(30 * g.u, 30 * g.u, 60 * g.u, 60 * g.u)
    }
    Rectangle {
        id: shape
        anchors.fill: parent
        radius: g.radius
        color: g.tint
        border.width: g.highlighted ? 2 * g.u : g.edgeWidth
        border.color: g.highlighted ? Theme.accent : g.edge
        Behavior on border.color { enabled: Theme.anim; ColorAnimation { duration: 180 } }
        Rectangle {   // soft light along the top edge, like glass
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.margins: 1
            height: Math.min(parent.height / 3, 60 * g.u)
            radius: g.radius
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#14ffffff" }
                GradientStop { position: 1.0; color: "#00ffffff" }
            }
        }
    }
    Item { id: inner; anchors.fill: parent }
}
