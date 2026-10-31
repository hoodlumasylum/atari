import QtQuick

// One system in the home row: a dark card with an original line drawing of that kind of machine and its name.
// The system being shown gets a gold frame (with a soft glow while the row has the focus).
Item {
    id: st
    property var info: ({})
    property real u: 1
    property bool selected: false    // the system whose games are shown
    property bool focused: false     // the tile row has the focus
    signal clicked()

    readonly property bool special: info.key === "__add" || info.key === "__more"
    readonly property bool lit: st.selected || (st.focused && st.special)

    Item {
        id: card
        anchors.fill: parent
        anchors.margins: 5 * st.u
        scale: st.focused ? 1.06 : 1.0
        Behavior on scale { enabled: Theme.anim; NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
        Rectangle {          // glow
            visible: st.lit && st.focused
            anchors.fill: parent
            anchors.margins: -5 * st.u
            radius: 16 * st.u
            color: "transparent"
            border.width: 5 * st.u
            border.color: Theme.accentGlow
        }
        Rectangle {
            id: face
            anchors.fill: parent
            radius: 12 * st.u
            gradient: Gradient {
                GradientStop { position: 0.0; color: st.lit ? "#2a2410" : "#171a22" }
                GradientStop { position: 1.0; color: st.lit ? "#120f06" : "#0b0d12" }
            }
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.12
                name: Theme.consoleFor(st.info.key, st.info.glyph)
                color: st.lit ? Theme.accent : "#e9ebf2"
                size: parent.height * 0.5
                stroke: 1.25
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 8 * st.u
                width: parent.width - 10 * st.u
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: st.special ? (st.info.key === "__add" ? "ADD GAMES" : (st.info.short.indexOf("fewer") >= 0 ? "FEWER" : "ALL SYSTEMS"))
                                 : (st.info.short ? st.info.short.toUpperCase() : "")
                color: st.lit ? "white" : "#cfd3e0"
                font.pixelSize: 15 * st.u
                font.bold: true
                font.letterSpacing: 0.5 * st.u
            }
        }
        Rectangle {  // frame
            anchors.fill: parent
            radius: 12 * st.u
            color: "transparent"
            border.width: (st.lit ? 3 : 1.2) * st.u
            border.color: st.lit ? Theme.accent : (st.focused ? "#6a7290" : "#2a3042")
        }
    }
    MouseArea { anchors.fill: parent; onClicked: st.clicked() }
}
