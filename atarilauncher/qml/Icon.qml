import QtQuick
import QtQuick.Window

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
        // drawn at the screen's real pixel density (x2 head-room for zoom / the selected tile growing) - never upscaled
        readonly property int px: Math.max(32, Math.ceil(ic.size * Math.max(1, Screen.devicePixelRatio) * 2))
        sourceSize: Qt.size(px, px)
        mipmap: true
        source: Theme.svgUrl(ic.name, ic.color, ic.stroke)
        smooth: true
        cache: true
    }
}
