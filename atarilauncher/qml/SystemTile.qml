import QtQuick

// One big system card: coloured gradient, simple original glyph and the system name.
Item {
    id: st
    property var info: ({})
    property real u: 1
    property bool selected: false    // the system whose games are shown
    property bool focused: false     // the tile row has the focus
    signal clicked()

    property real bob: 0             // -1..1, moves the icon of the chosen tile up and down a little
    SequentialAnimation on bob {
        loops: Animation.Infinite
        running: Theme.anim && st.selected && st.focused
        NumberAnimation { from: -1; to: 1; duration: 1100; easing.type: Easing.InOutSine }
        NumberAnimation { from: 1; to: -1; duration: 1100; easing.type: Easing.InOutSine }
    }
    onSelectedChanged: if (!selected) bob = 0
    onFocusedChanged: if (!focused) bob = 0
    readonly property bool special: info.key === "__add" || info.key === "__more"

    Item {
        id: card
        anchors.fill: parent
        anchors.margins: 7 * st.u
        scale: st.selected && st.focused ? 1.04 : 1.0
        Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
        Rectangle {
            visible: st.selected
            anchors.fill: parent
            anchors.margins: -6 * st.u
            radius: 20 * st.u
            color: "transparent"
            border.width: 5 * st.u
            border.color: st.focused ? "#40e0202a" : "#26e0202a"
            opacity: Theme.anim && st.focused ? 0.75 + 0.25 * (st.bob + 1) / 2 : 1.0
        }
        Rectangle {
            visible: st.selected
            anchors.fill: parent
            anchors.margins: -3 * st.u
            radius: 17 * st.u
            color: "transparent"
            border.width: 3 * st.u
            border.color: st.focused ? "#80e0202a" : "#4de0202a"
        }
        Rectangle {
            id: face
            anchors.fill: parent
            radius: 15 * st.u
            gradient: Gradient {
                GradientStop { position: 0.0; color: st.info.c1 ? st.info.c1 : "#222" }
                GradientStop { position: 1.0; color: st.info.c2 ? st.info.c2 : "#111" }
            }
            clip: true
            Rectangle {  // light sweep
                width: parent.width * 1.6
                height: parent.height * 0.35
                rotation: -28
                x: -parent.width * 0.3
                y: parent.height * 0.05
                color: "#12ffffff"
            }
            Rectangle {  // darker foot so the name is easy to read
                anchors.bottom: parent.bottom
                width: parent.width
                height: parent.height * 0.34
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 1.0; color: "#99000000" }
                }
            }
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.12 + st.bob * 4 * st.u
                name: st.info.glyph ? st.info.glyph : "pad"
                color: "#f3f4f8"
                size: parent.height * 0.46
                stroke: st.info.glyph === "bars" ? 1.6 : 1.3
                opacity: 0.93
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: (st.info.count >= 0 ? 30 : 20) * st.u
                width: parent.width - 16 * st.u
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: st.info.short ? st.info.short : ""
                color: "white"
                font.pixelSize: 25 * st.u
                font.bold: true
            }
            Text {
                visible: st.info.count >= 0
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 10 * st.u
                text: st.info.count + (st.info.count === 1 ? " game" : " games")
                color: "#c9cde0"
                font.pixelSize: 15 * st.u
            }
        }
        Rectangle {  // frame
            anchors.fill: parent
            radius: 15 * st.u
            color: "transparent"
            border.width: (st.selected ? 3 : 1.5) * st.u
            border.color: st.selected ? Theme.redBright : "#3a4260"
        }
    }
    MouseArea { anchors.fill: parent; onClicked: st.clicked() }
}
