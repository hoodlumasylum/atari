import QtQuick

// Right-hand panel: art, title, details, PLAY and FAVOURITE.
Rectangle {
    id: dp
    property var game: ({})
    property real u: 1
    property bool focused: false
    property int focusIndex: 0          // 0 = PLAY, 1 = FAVOURITE
    readonly property bool has: game && game.title !== undefined
    signal play()
    signal toggleFavorite()
    signal clicked()

    radius: 14 * u
    color: "#0f111a"
    border.width: 1.5 * u
    border.color: focused ? "#80e0202a" : Theme.line

    Cover {
        id: art
        x: 14 * dp.u
        y: 14 * dp.u
        width: parent.width - 28 * dp.u
        height: Math.min(width * 0.5, parent.height * 0.3)
        u: dp.u
        radius: 10 * dp.u
        source: dp.has ? dp.game.art : ""
        title: dp.has ? dp.game.title : ""
        label: dp.has ? dp.game.platformName : ""
        hue: dp.has ? dp.game.hue : 0.6
        fit: dp.has && dp.game.art !== "" && !dp.game.wideArt
    }
    Rectangle {
        x: art.x; y: art.y; width: art.width; height: art.height
        radius: 10 * dp.u; color: "transparent"; border.width: 1.5 * dp.u; border.color: "#3a4260"
    }
    Text {
        id: titleText
        anchors.top: art.bottom
        anchors.topMargin: 14 * dp.u
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 18 * dp.u
        anchors.rightMargin: 18 * dp.u
        text: dp.has ? dp.game.title : "No game selected"
        color: "white"
        font.pixelSize: 30 * dp.u
        font.bold: true
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
    }
    Text {
        id: sub
        anchors.top: titleText.bottom
        anchors.topMargin: 4 * dp.u
        anchors.left: titleText.left
        anchors.right: titleText.right
        visible: dp.has
        elide: Text.ElideRight
        text: dp.has ? ("Played: " + dp.game.playtime + "   \u00b7   Last: " + dp.game.lastPlayed) : ""
        color: Theme.dim
        font.pixelSize: 15 * dp.u
    }
    Column {
        id: rows
        anchors.top: sub.bottom
        anchors.topMargin: 14 * dp.u
        anchors.left: titleText.left
        anchors.right: titleText.right
        spacing: 7 * dp.u
        visible: dp.has
        Repeater {
            model: [["System", "platformName"], ["Genre", "genre"], ["Players", "players"], ["Release", "release"], ["Rating", "rating"]]
            Row {
                required property var modelData
                height: 24 * dp.u
                Text {
                    width: 96 * dp.u
                    text: modelData[0] + ":"
                    color: Theme.dim
                    font.pixelSize: 18 * dp.u
                }
                Text {
                    visible: modelData[1] !== "rating"
                    width: rows.width - 96 * dp.u
                    elide: Text.ElideRight
                    text: dp.has ? String(dp.game[modelData[1]]) : "-"
                    color: "#eceef6"
                    font.pixelSize: 18 * dp.u
                }
                Row {
                    visible: modelData[1] === "rating"
                    spacing: 3 * dp.u
                    Text {
                        visible: !(dp.has && dp.game.rating >= 0)
                        text: "-"
                        color: "#eceef6"
                        font.pixelSize: 18 * dp.u
                    }
                    Repeater {
                        model: dp.has && dp.game.rating >= 0 ? 5 : 0
                        Icon {
                            required property int index
                            name: dp.game.rating >= index + 0.75 ? "starfill" : "star"
                            size: 20 * dp.u
                            stroke: 1.8
                            color: dp.game.rating >= index + 0.25 ? Theme.yellow : "#5a5f78"
                        }
                    }
                }
            }
        }
    }
    Text {
        id: noteText
        anchors.top: rows.bottom
        anchors.topMargin: 10 * dp.u
        anchors.left: titleText.left
        anchors.right: titleText.right
        anchors.bottom: buttons.top
        anchors.bottomMargin: 8 * dp.u
        visible: dp.has && dp.game.note !== ""
        text: dp.has ? dp.game.note : ""
        wrapMode: Text.Wrap
        elide: Text.ElideRight
        color: Theme.yellow
        font.pixelSize: 14 * dp.u
    }
    Row {
        id: buttons
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 16 * dp.u
        anchors.left: titleText.left
        anchors.right: titleText.right
        spacing: 12 * dp.u
        Rectangle {
            id: playBtn
            readonly property bool sel: dp.focused && dp.focusIndex === 0
            width: (buttons.width - buttons.spacing) * 0.56
            height: 62 * dp.u
            radius: 10 * dp.u
            opacity: dp.has ? 1 : 0.4
            gradient: Gradient {
                GradientStop { position: 0; color: playBtn.sel ? "#ff4a52" : "#ee2a34" }
                GradientStop { position: 1; color: playBtn.sel ? "#c4161f" : "#a8121b" }
            }
            border.width: playBtn.sel ? 3 * dp.u : 0
            border.color: "white"
            Row {
                anchors.centerIn: parent
                spacing: 12 * dp.u
                Icon { name: dp.has && dp.game.needsInstall ? "plus" : "play"; size: 26 * dp.u; color: "white"; anchors.verticalCenter: parent.verticalCenter }
                Text { text: dp.has && dp.game.needsInstall ? "INSTALL" : "PLAY"; color: "white"; font.pixelSize: 24 * dp.u; font.bold: true
                       font.letterSpacing: 2 * dp.u; anchors.verticalCenter: parent.verticalCenter }
            }
            MouseArea { anchors.fill: parent; onClicked: { if (dp.has) dp.play() } }
        }
        Rectangle {
            id: favBtn
            readonly property bool sel: dp.focused && dp.focusIndex === 1
            readonly property bool on: dp.has && dp.game.favorite
            width: buttons.width - playBtn.width - buttons.spacing
            height: 62 * dp.u
            radius: 10 * dp.u
            opacity: dp.has ? 1 : 0.4
            color: favBtn.on ? "#2a0b10" : "#171a28"
            border.width: (favBtn.sel ? 3 : 1.5) * dp.u
            border.color: favBtn.sel ? "white" : (favBtn.on ? Theme.red : "#4a5170")
            Row {
                anchors.centerIn: parent
                spacing: 8 * dp.u
                Icon { name: favBtn.on ? "starfill" : "star"; size: 22 * dp.u; stroke: 2
                       color: favBtn.on ? Theme.yellow : "#e6e8f0"; anchors.verticalCenter: parent.verticalCenter }
                Text { text: "FAVOURITE"; color: "#f0f1f8"; font.pixelSize: 16 * dp.u; font.bold: true
                       font.letterSpacing: 1 * dp.u; anchors.verticalCenter: parent.verticalCenter }
            }
            MouseArea { anchors.fill: parent; onClicked: { if (dp.has) dp.toggleFavorite() } }
        }
    }
    MouseArea { anchors.fill: parent; z: -1; onClicked: dp.clicked() }
}
