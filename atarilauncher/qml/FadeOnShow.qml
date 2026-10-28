import QtQuick

// Put one inside a screen (or point `target` at it): the screen fades in softly each time it appears.
// Does nothing when "Reduce animations" is ON.
Item {
    id: fade
    property Item target: parent
    width: 0; height: 0; visible: true
    property int duration: 170
    property var _conn: Connections {
        target: fade.target
        function onVisibleChanged() { if (fade.target && fade.target.visible && Theme.anim) fade._anim.restart() }
    }
    property var _anim: NumberAnimation {
        target: fade.target
        property: "opacity"
        from: 0.0
        to: 1.0
        duration: fade.duration
        easing.type: Easing.OutQuad
    }
}
