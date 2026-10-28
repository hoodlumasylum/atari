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
    property bool current: false
    signal clicked()
    signal activated()

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: parent.width - 24 * tile.u
        height: parent.height - 24 * tile.u
        radius: 10 * tile.u
        color: "#120e0b"
        border.width: tile.current ? 6 * tile.u : 2 * tile.u
        border.color: tile.current ? Theme.orange : "#3a2a1c"
        scale: tile.current ? 1.06 : 1.0
        z: tile.current ? 2 : 0
        Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }

        // --- placeholder art (always drawn underneath; hidden once real art loads) ---
        Rectangle {
            id: placeholder
            anchors.fill: parent
            anchors.margins: card.border.width
            radius: 6 * tile.u
            visible: img.status !== Image.Ready
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.hsla(tile.hue, 0.55, 0.30, 1) }
                GradientStop { position: 1.0; color: Qt.hsla(tile.hue, 0.65, 0.12, 1) }
            }
            Column {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottomMargin: 26 * tile.u
                StripeBar { width: parent.width; stripe: 6 * tile.u; opacity: 0.9 }
            }
            Text {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -20 * tile.u
                width: parent.width - 30 * tile.u
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                maximumLineCount: 4
                elide: Text.ElideRight
                text: tile.title
                color: Theme.text
                font.pixelSize: 34 * tile.u
                font.bold: true
            }
        }
        Image {
            id: img
            anchors.fill: parent
            anchors.margins: card.border.width
            source: tile.cover
            asynchronous: true
            fillMode: Image.PreserveAspectCrop
            sourceSize.width: 400
            sourceSize.height: 600
            visible: status === Image.Ready
        }
        // --- bottom caption ---
        Rectangle {
            visible: img.status === Image.Ready
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: card.border.width
            height: 64 * tile.u
            color: "#cc0b0907"
            Text {
                anchors.fill: parent
                anchors.margins: 8 * tile.u
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
                text: tile.title
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
                color: Theme.text
                font.pixelSize: 21 * tile.u
            }
        }
        // --- platform badge ---
        Rectangle {
            x: 10 * tile.u
            y: 10 * tile.u
            height: 30 * tile.u
            width: badgeText.implicitWidth + 20 * tile.u
            radius: 5 * tile.u
            color: Theme.platformColor(tile.platform)
            Text {
                id: badgeText
                anchors.centerIn: parent
                text: tile.platformName
                color: "white"
                font.pixelSize: 17 * tile.u
                font.bold: true
            }
        }
        Text {
            visible: tile.favorite
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 8 * tile.u
            text: "\u2605"
            color: Theme.yellow
            font.pixelSize: 40 * tile.u
            style: Text.Outline
            styleColor: "#000000"
        }
        MouseArea {
            anchors.fill: parent
            onClicked: tile.clicked()
            onDoubleClicked: tile.activated()
        }
    }
}
