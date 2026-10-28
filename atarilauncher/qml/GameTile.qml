import QtQuick

Item {
    id: tile
    required property int index
    required property string gid
    required property string title
    required property string platform
    required property string platformName
    required property string cover
    required property bool favorite
    required property string playtime
    required property string lastPlayed
    required property string note
    required property real hue
    property real u: 1
    property bool current: false     // the highlighted game
    property bool focused: false     // ... and the grid currently has the focus
    signal clicked()
    signal activated()

    readonly property real capH: 34 * u

    Item {
        id: card
        x: 8 * tile.u
        y: 8 * tile.u
        width: tile.width - 16 * tile.u
        height: tile.height - tile.capH - 12 * tile.u
        scale: tile.current && tile.focused ? 1.05 : 1.0
        z: tile.current ? 2 : 0
        Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutQuad } }

        // red glow (only for the highlighted tile): two soft rings
        Rectangle {
            visible: tile.current && tile.focused
            anchors.fill: parent
            anchors.margins: -7 * tile.u
            radius: 14 * tile.u
            color: "transparent"
            border.width: 5 * tile.u
            border.color: "#33e0202a"
        }
        Rectangle {
            visible: tile.current && tile.focused
            anchors.fill: parent
            anchors.margins: -3.5 * tile.u
            radius: 11 * tile.u
            color: "transparent"
            border.width: 3 * tile.u
            border.color: "#66e0202a"
        }
        Cover {
            anchors.fill: parent
            anchors.margins: 2 * tile.u
            u: tile.u
            radius: 7 * tile.u
            source: tile.cover
            title: tile.title
            label: tile.platformName
            hue: tile.hue
        }
        Rectangle {  // frame
            anchors.fill: parent
            radius: 9 * tile.u
            color: "transparent"
            border.width: (tile.current ? 3 : 1.5) * tile.u
            border.color: tile.current ? (tile.focused ? Theme.redBright : Theme.red) : "#2c3044"
        }
        Icon {
            visible: tile.favorite
            name: "starfill"
            color: Theme.yellow
            size: 24 * tile.u
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 7 * tile.u
        }
    }
    Text {
        anchors.top: card.bottom
        anchors.topMargin: 6 * tile.u
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 6 * tile.u
        anchors.rightMargin: 6 * tile.u
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        text: tile.title
        color: tile.current ? Theme.text : "#bfc3d4"
        font.pixelSize: 17 * tile.u
        font.bold: tile.current
    }
    MouseArea {
        anchors.fill: parent
        onClicked: tile.clicked()
        onDoubleClicked: tile.activated()
    }
}
