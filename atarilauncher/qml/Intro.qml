import QtQuick

// The start-up intro screen. With no video of your own it plays Code's own short animation (original artwork: the app's
// wordmark over the flowing waves, plus a soft original sound). With your video, a video player covers the screen and this
// is just the black backdrop. Any key, click or controller button skips (handled in Main.qml / the backend).
Item {
    id: intro
    property real u: 1
    readonly property bool own: backend.introMode === "default"
    property real shown: 0                 // 0..1 fade/zoom in, then out at the end

    Rectangle { anchors.fill: parent; color: "#05060b" }
    WaveBackground { anchors.fill: parent; active: intro.visible && intro.own; opacity: intro.own ? 1 : 0 }

    // scan lines + soft vignette: a nod to old screens, drawn here (nothing borrowed)
    Repeater {
        model: intro.own ? Math.ceil(intro.height / (6 * intro.u)) : 0
        Rectangle { y: index * 6 * intro.u; width: intro.width; height: 1.5 * intro.u; color: "#10000000" }
    }

    Column {
        anchors.centerIn: parent
        spacing: 18 * intro.u
        visible: intro.own
        opacity: intro.shown
        scale: 0.92 + 0.08 * intro.shown
        Wordmark { id: wm; u: intro.u * 2.4; anchors.horizontalCenter: parent.horizontalCenter }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "GAME LAUNCHER"
            color: "#b9bdd2"
            font.pixelSize: 26 * intro.u
            font.letterSpacing: 10 * intro.u
        }
    }

    Rectangle { id: blackout; anchors.fill: parent; color: "black"; opacity: 0 }

    Text {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 34 * intro.u
        anchors.horizontalCenter: parent.horizontalCenter
        text: "Press any key to skip"
        color: "#6b7090"
        font.pixelSize: 20 * intro.u
        opacity: 0.8
    }

    SequentialAnimation {
        running: intro.visible && intro.own
        NumberAnimation { target: intro; property: "shown"; from: 0; to: 1; duration: Theme.anim ? 1100 : 1; easing.type: Easing.OutCubic }
        PauseAnimation { duration: Theme.anim ? 1500 : 1900 }
        NumberAnimation { target: blackout; property: "opacity"; from: 0; to: 1; duration: Theme.anim ? 900 : 1 }
    }
    MouseArea { anchors.fill: parent; cursorShape: Qt.BlankCursor; onClicked: backend.skipIntro() }     // no mouse pointer during the intro
}
