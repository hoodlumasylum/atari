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
    required property bool fit
    required property string badge
    property real u: 1
    property bool current: false     // the highlighted game
    property bool focused: false     // ... and the grid currently has the focus
    property bool listMode: false    // one game per row: small cover on the left, name and system next to it
    signal clicked()
    signal activated()

    readonly property real capH: 34 * u

    Item {
        id: card
        x: 8 * tile.u
        y: (tile.listMode ? 5 : 8) * tile.u
        height: tile.listMode ? tile.height - 10 * tile.u : tile.height - tile.capH - 12 * tile.u
        width: tile.listMode ? height * 0.75 : tile.width - 16 * tile.u
        scale: tile.current && tile.focused && !tile.listMode ? 1.05 : 1.0
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
            border.color: Theme.accentGlow
        }
        Rectangle {
            visible: tile.current && tile.focused
            anchors.fill: parent
            anchors.margins: -3.5 * tile.u
            radius: 11 * tile.u
            color: "transparent"
            border.width: 3 * tile.u
            border.color: Theme.accent
        }
        Cover {
            anchors.fill: parent
            anchors.margins: 2 * tile.u
            u: tile.u
            radius: 7 * tile.u
            source: tile.cover
            fit: tile.fit
            title: tile.title
            label: tile.platformName
            hue: tile.hue
            glyph: Theme.glyphFor(tile.gid)
        }
        Rectangle {  // frame
            anchors.fill: parent
            radius: 9 * tile.u
            color: "transparent"
            border.width: (tile.current ? 3 : 1.5) * tile.u
            border.color: tile.current ? Theme.accent : "#2c3044"
        }
        Rectangle {   // Modern Games: will it run on Linux (ProtonDB / anti-cheat)
            objectName: "runBadge"
            visible: tile.badge !== ""
            anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 6 * tile.u
            height: 22 * tile.u; width: Math.min(badgeText.implicitWidth + 14 * tile.u, parent.width - 12 * tile.u)
            radius: height / 2
            color: tile.badge === "Works great" ? "#cc1f7a3a" : tile.badge === "Should work" ? "#cc8a6d12" : "#cca01822"
            Text { id: badgeText; anchors.centerIn: parent; width: parent.width - 10 * tile.u; horizontalAlignment: Text.AlignHCenter
                   elide: Text.ElideRight; text: tile.badge; color: "white"; font.pixelSize: 12 * tile.u; font.bold: true }
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
    Rectangle {      // list mode: the highlighted row
        visible: tile.listMode && tile.current
        anchors.fill: parent
        anchors.margins: 2 * tile.u
        z: -1
        radius: 10 * tile.u
        color: tile.focused ? "#2a2410" : "#171a22"
        border.width: 2 * tile.u
        border.color: tile.focused ? Theme.accent : "#4a4030"
    }
    Column {
        visible: tile.listMode
        anchors.left: card.right
        anchors.leftMargin: 16 * tile.u
        anchors.right: parent.right
        anchors.rightMargin: 12 * tile.u
        anchors.verticalCenter: parent.verticalCenter
        spacing: 3 * tile.u
        Text { width: parent.width; elide: Text.ElideRight; text: tile.title; color: "white"
               font.pixelSize: 20 * tile.u; font.bold: tile.current }
        Text { width: parent.width; elide: Text.ElideRight; color: "#9aa1b6"; font.pixelSize: 15 * tile.u
               text: tile.platformName + (tile.lastPlayed !== "" && tile.lastPlayed !== "Never" ? "   ·   Played " + tile.lastPlayed : "")
                     + (tile.playtime !== "" && tile.playtime !== "Not played yet" ? "   ·   " + tile.playtime : "") }
    }
    Text {
        visible: !tile.listMode
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
