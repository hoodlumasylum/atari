import QtQuick
import QtQuick.Effects

// Full-screen picture behind the home screen: the highlighted game's own art (wide art first), blurred and darkened,
// cross-fading when the selection changes and drifting a little sideways (parallax). Without art: a soft emerald/gold
// glow tinted by the game's colour. "Reduce effects" = no blur (a plain darkened picture) and no drift.
Item {
    id: bd
    property string source: ""
    property real hue: 0.42
    property real drift: 0          // -1 .. 1, where the selection is across the row
    property bool fx: Theme.fx
    property bool anim: Theme.anim
    property bool showA: true
    clip: true

    onSourceChanged: swap()
    function swap() {
        if (showA) { b.source = source } else { a.source = source }
        showA = !showA
    }

    // the glow (always there, so a game without art still changes the mood a little)
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.hsla(bd.hue, 0.45, 0.13, 1) }
            GradientStop { position: 0.55; color: Theme.emeraldDark }
            GradientStop { position: 1.0; color: "#05060a" }
        }
    }
    Rectangle {    // gold light from the top right
        width: parent.width * 0.9; height: width
        x: parent.width * 0.45 - bd.drift * (bd.fx && bd.anim ? 30 : 0); y: -height * 0.55
        radius: width / 2
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#2ae8c25a" }
            GradientStop { position: 1.0; color: "#00e8c25a" }
        }
        Behavior on x { enabled: bd.anim; NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
    }

    Item {
        id: art
        anchors.fill: parent
        anchors.margins: bd.fx ? -60 : 0
        x: bd.fx && bd.anim ? -bd.drift * 40 : 0
        Behavior on x { enabled: bd.anim; NumberAnimation { duration: 700; easing.type: Easing.OutCubic } }
        visible: false
        Image {
            id: a
            objectName: "backdropA"
            anchors.fill: parent
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            sourceSize.width: bd.fx ? 640 : 960       // a small picture is enough under a blur and is cheap to draw
            opacity: bd.showA && status === Image.Ready ? 1 : 0
            Behavior on opacity { enabled: bd.anim; NumberAnimation { duration: 450; easing.type: Easing.InOutQuad } }
        }
        Image {
            id: b
            objectName: "backdropB"
            anchors.fill: parent
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            sourceSize.width: bd.fx ? 640 : 960
            opacity: !bd.showA && status === Image.Ready ? 1 : 0
            Behavior on opacity { enabled: bd.anim; NumberAnimation { duration: 450; easing.type: Easing.InOutQuad } }
        }
    }
    MultiEffect {
        objectName: "backdropBlur"
        source: art
        anchors.fill: art
        x: art.x
        blurEnabled: bd.fx
        blur: 1.0
        blurMax: 48
        saturation: 0.15
        opacity: 0.55
    }
    Rectangle {    // keep text readable: darker at the bottom and the left
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#5508090e" }
            GradientStop { position: 0.6; color: "#9908090e" }
            GradientStop { position: 1.0; color: "#e608090e" }
        }
    }
}
