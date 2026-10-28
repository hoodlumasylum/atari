import QtQuick

// A crisp vector icon (see Theme.icons). Rendered once into a texture - cheap on any GPU.
Item {
    id: ic
    property string name: "pad"
    property color color: Theme.text
    property real size: 24
    property real stroke: 2
    width: size
    height: size
    Image {
        anchors.fill: parent
        sourceSize: Qt.size(Math.max(16, Math.ceil(ic.size * 1.5)), Math.max(16, Math.ceil(ic.size * 1.5)))
        source: Theme.svgUrl(ic.name, ic.color, ic.stroke)
        smooth: true
        cache: true
    }
}
