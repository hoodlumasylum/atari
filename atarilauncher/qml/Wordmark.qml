import QtQuick

// The CodeAque logo (original artwork by the project owner: the gold and emerald Anubis with the CODEAQUE GAMING wordmark).
// `u` scales it like everything else; the logo is square, so the item is as wide as it is tall.
Item {
    id: wm
    property real u: 1
    property bool compact: false          // the top bar: the Anubis head alone (the wordmark is unreadable at that size)
    width: height
    height: 96 * u
    Image {
        anchors.fill: parent
        source: Qt.resolvedUrl(wm.compact ? "../assets/codeaque-icon.png" : "../assets/codeaque-logo.png")
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        asynchronous: false
    }
}
