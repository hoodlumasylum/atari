import QtQuick

// The header above the games: the system's name, a line about it, an original drawing of that kind of machine and
// a few plain numbers (no ratings, no logos). Dark emerald with gold, with a simple drawn desert-and-pyramids backdrop.
Rectangle {
    id: hero
    property real u: 1
    property var info: ({})          // the tile of the system shown ({key, label, short, full, blurb, glyph, count})
    property string title: ""
    property string subtitle: ""
    property string blurb: ""
    property var chips: []           // [{icon, text}]
    radius: 16 * u
    clip: true
    gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0.0; color: "#06231a" }
        GradientStop { position: 0.55; color: "#0b3a2b" }
        GradientStop { position: 1.0; color: "#14110a" }
    }
    border.width: 1.5 * u
    border.color: "#4de8c25a"

    Canvas {           // original backdrop: a sun disc, dunes and three pyramids in thin gold lines
        id: bg
        anchors.fill: parent
        opacity: 0.55
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        renderTarget: Canvas.FramebufferObject
        onPaint: {
            var c = getContext("2d"); var w = width, h = height
            c.reset()
            var g = c.createRadialGradient(w * 0.72, h * 0.35, 0, w * 0.72, h * 0.35, h * 0.9)
            g.addColorStop(0, "rgba(232,194,90,0.28)"); g.addColorStop(1, "rgba(232,194,90,0)")
            c.fillStyle = g; c.fillRect(0, 0, w, h)
            c.strokeStyle = "rgba(232,194,90,0.55)"; c.lineWidth = Math.max(1, 1.4 * hero.u)
            function pyr(x, base, half, top) {
                c.beginPath(); c.moveTo(x - half, base); c.lineTo(x, base - top); c.lineTo(x + half, base); c.stroke()
                c.beginPath(); c.moveTo(x, base - top); c.lineTo(x + half * 0.25, base); c.stroke()
            }
            pyr(w * 0.50, h * 0.98, h * 0.34, h * 0.42)
            pyr(w * 0.60, h * 0.98, h * 0.48, h * 0.60)
            pyr(w * 0.40, h * 0.98, h * 0.24, h * 0.28)
            c.strokeStyle = "rgba(232,194,90,0.30)"
            c.beginPath(); c.moveTo(0, h * 0.92); c.bezierCurveTo(w * 0.3, h * 0.80, w * 0.6, h * 1.02, w, h * 0.86); c.stroke()
            c.beginPath(); c.arc(w * 0.72, h * 0.35, h * 0.16, 0, Math.PI * 2); c.stroke()
        }
    }
    Rectangle {        // darker left side so the text is easy to read
        anchors.fill: parent
        radius: parent.radius
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#cc03120d" }
            GradientStop { position: 0.55; color: "#4003120d" }
            GradientStop { position: 1.0; color: "#00000000" }
        }
    }
    Icon {             // the machine
        anchors.right: parent.right
        anchors.rightMargin: parent.width * 0.04
        anchors.verticalCenter: parent.verticalCenter
        size: parent.height * 0.86
        name: Theme.consoleFor(hero.info.key, hero.info.glyph)
        color: Theme.accent
        stroke: 0.9
    }
    Column {
        anchors.left: parent.left
        anchors.leftMargin: 28 * hero.u
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width * 0.6
        spacing: 6 * hero.u
        Text {
            width: parent.width
            text: hero.title.toUpperCase()
            color: "white"
            font.pixelSize: 54 * hero.u
            font.bold: true
            font.letterSpacing: 4 * hero.u
            elide: Text.ElideRight
            fontSizeMode: Text.HorizontalFit
            minimumPixelSize: 26 * hero.u
        }
        Text {
            visible: text !== "" && text.toUpperCase() !== hero.title.toUpperCase()
            width: parent.width
            text: hero.subtitle.toUpperCase()
            color: Theme.accent
            font.pixelSize: 17 * hero.u
            font.letterSpacing: 3 * hero.u
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: hero.blurb
            color: "#d9dde8"
            font.pixelSize: 17 * hero.u
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
        Item { width: 1; height: 4 * hero.u }
        Row {
            spacing: 10 * hero.u
            Repeater {
                model: hero.chips
                Rectangle {
                    required property var modelData
                    height: 38 * hero.u
                    width: chipRow.implicitWidth + 24 * hero.u
                    radius: 10 * hero.u
                    color: "#a60b0f14"
                    border.width: 1.2 * hero.u
                    border.color: "#66e8c25a"
                    Row {
                        id: chipRow
                        anchors.centerIn: parent
                        spacing: 8 * hero.u
                        Icon { name: modelData.icon; size: 20 * hero.u; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: modelData.text; color: "white"; font.pixelSize: 15 * hero.u; font.bold: true
                               anchors.verticalCenter: parent.verticalCenter }
                    }
                }
            }
        }
    }
}
