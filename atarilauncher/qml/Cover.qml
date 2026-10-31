import QtQuick
import QtQuick.Window

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
    property string glyph: ""      // an app tile: an original vector picture + its name instead of a downloaded logo
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
            GradientStop { position: 0.0; color: cv.glyph !== "" ? Theme.emerald : Qt.hsla(cv.hue, 0.55, 0.34, 1) }
            GradientStop { position: 1.0; color: cv.glyph !== "" ? Theme.emeraldDark : Qt.hsla((cv.hue + 0.08) % 1, 0.6, 0.11, 1) }
        }
        Rectangle {   // thin gold frame on app tiles
            visible: cv.glyph !== ""
            anchors.fill: parent; anchors.margins: 4 * cv.u
            radius: Math.max(0, cv.radius - 3 * cv.u)
            color: "transparent"; border.color: "#99e8c25a"; border.width: 1.5 * cv.u
        }
        Icon {
            objectName: "tileGlyph"
            visible: cv.glyph !== "" && img.status !== Image.Ready
            name: cv.glyph
            color: Theme.gold
            stroke: 1.6
            size: Math.min(cv.width * 0.42, cv.height * 0.5)
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -cv.height * 0.09
        }
        Text {
            visible: cv.glyph !== "" && img.status !== Image.Ready
            anchors.top: parent.verticalCenter
            anchors.topMargin: cv.height * 0.2
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 14 * cv.u
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: cv.title
            color: Theme.gold
            font.pixelSize: Math.max(11, Math.min(cv.width * 0.12, cv.height * 0.13))
            font.bold: true
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
            visible: img.status !== Image.Ready && cv.glyph === ""
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
            visible: img.status !== Image.Ready && cv.label !== "" && cv.glyph === ""
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
        // decoded at the tile's real size on this screen (at least 512 px) - a picture is never decoded small and stretched
        sourceSize.width: Math.max(512, Math.ceil(cv.width * Math.max(1, Screen.devicePixelRatio) * 1.25))
        sourceSize.height: Math.max(512, Math.ceil(cv.height * Math.max(1, Screen.devicePixelRatio) * 1.25))
        smooth: true
        mipmap: true
        visible: status === Image.Ready
    }
}
