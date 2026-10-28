import QtQuick

// The Code logo (original artwork by the project owner: winged crest with "CODE" and an ankh for the O).
// `u` scales it like everything else; the logo is square, so the item is as wide as it is tall.
Item {
    id: wm
    property real u: 1
    width: height
    height: 96 * u
    Image {
        anchors.fill: parent
        source: Qt.resolvedUrl("../assets/code-logo.png")
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        asynchronous: false
    }
}
