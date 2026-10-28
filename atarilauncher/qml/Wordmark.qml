import QtQuick

// Plain stylised text wordmark with a simple three-bar motif (original artwork, not a copy of any logo).
Item {
    id: wm
    property real u: 1
    width: motif.width + 18 * u + word.implicitWidth
    height: 80 * u
    Item {
        id: motif
        width: 56 * wm.u
        height: 64 * wm.u
        anchors.verticalCenter: parent.verticalCenter
        Repeater {
            model: [-16, 0, 16]
            Item {
                required property int modelData
                x: motif.width / 2 - width / 2 + modelData * 0.9 * wm.u
                width: 11 * wm.u
                height: motif.height
                y: modelData === 0 ? -4 * wm.u : 0
                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width
                    height: parent.height + (modelData === 0 ? 8 * wm.u : 0)
                    radius: 4 * wm.u
                    rotation: modelData
                    gradient: Gradient {
                        GradientStop { position: 0; color: Theme.redBright }
                        GradientStop { position: 1; color: "#a8121b" }
                    }
                }
            }
        }
    }
    Text {   // soft glow: the same word, a little bigger and see-through, behind the real one
        anchors.centerIn: word
        text: word.text
        font: word.font
        scale: 1.04
        color: Theme.red
        opacity: 0.35
    }
    Text {
        id: word
        anchors.left: motif.right
        anchors.leftMargin: 18 * wm.u
        anchors.verticalCenter: parent.verticalCenter
        text: "ATARI"
        color: Theme.red
        font.pixelSize: 68 * wm.u
        font.weight: Font.Black
        font.italic: false
        font.letterSpacing: 5 * wm.u
        style: Text.Outline
        styleColor: "#5a0b11"
    }
}
