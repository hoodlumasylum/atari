import QtQuick

// Game art: the picture if there is one, otherwise a clean generated tile (gradient + monogram).
Item {
    id: cv
    property string source: ""
    property string title: ""
    property string label: ""      // small text, e.g. the system name
    property real hue: 0.6
    property real u: 1
    property real radius: 8
    property bool fit: false       // true = show the whole picture (letterboxed) instead of cropping
    property alias status: img.status
    readonly property string monogram: {
        var words = title.replace(/[^A-Za-z0-9 ]/g, " ").trim().split(/\s+/).filter(function (w) { return w.length > 0 })
        if (words.length === 0) return "?"
        if (words.length === 1) return words[0].substring(0, 2).toUpperCase()
        return (words[0].charAt(0) + words[1].charAt(0) + (words.length > 2 ? words[2].charAt(0) : "")).toUpperCase()
    }
    Rectangle {
        anchors.fill: parent
        radius: cv.radius
        visible: img.status !== Image.Ready || cv.fit
        clip: true
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.hsla(cv.hue, 0.55, 0.34, 1) }
            GradientStop { position: 1.0; color: Qt.hsla((cv.hue + 0.08) % 1, 0.6, 0.11, 1) }
        }
        Rectangle {  // soft highlight band
            width: parent.width * 1.4
            height: parent.height * 0.22
            rotation: -24
            x: -parent.width * 0.2
            y: parent.height * 0.12
            color: "#14ffffff"
        }
        Text {
            visible: img.status !== Image.Ready
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -cv.height * 0.04
            text: cv.monogram
            color: "#f3f4f8"
            opacity: 0.92
            font.pixelSize: Math.min(cv.width * 0.34, cv.height * 0.46)
            font.weight: Font.Black
            font.letterSpacing: 2 * cv.u
        }
        Text {
            visible: img.status !== Image.Ready && cv.label !== ""
            anchors.bottom: parent.bottom
            anchors.bottomMargin: cv.height * 0.07
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 12 * cv.u
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: cv.label.toUpperCase()
            color: "#d9dcec"
            font.pixelSize: Math.max(9, Math.min(cv.width * 0.075, 16 * cv.u))
            font.letterSpacing: 1.5 * cv.u
        }
    }
    Image {
        id: img
        anchors.fill: parent
        anchors.margins: 1
        source: cv.source
        asynchronous: true
        cache: true
        fillMode: cv.fit ? Image.PreserveAspectFit : Image.PreserveAspectCrop
        sourceSize.width: 520
        sourceSize.height: 520
        visible: status === Image.Ready
    }
}
