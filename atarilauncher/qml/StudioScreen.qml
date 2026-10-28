import QtQuick

// Hoodlum Asylum Studio: three big buttons (Make a beat / Record your voice / Mix & share) and a list page for each.
// Dark, with gold and green. Keyboard / gamepad: arrows + Enter + Esc.  Touch: tap a card or a row, and the big < > buttons.
Item {
    id: st
    property real u: 1
    property var studio
    readonly property color gold: "#e0b13a"
    readonly property color goldDark: "#3a2c08"
    readonly property color green: "#3fae49"
    readonly property color ink: "#070a07"
    property string page: "home"
    property int homeIdx: 0
    property var cards: []
    signal closed()

    function isEnter(k) { return k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space }
    function open() {
        studio.openPage("home")
        page = "home"; homeIdx = 0
        cards = studio.homeCards()
    }
    function refresh() {
        page = studio.pageName
        cards = studio.homeCards()
        if (page === "home") return
        var idx = list.currentIndex
        list.model = studio.rows(page)
        list.currentIndex = Math.max(0, Math.min(idx, list.count - 1))
        var r = list.model[list.currentIndex]
        if (!r || r.kind === "info") list.firstSelectable()
    }
    function goPage(p) { studio.openPage(p); list.currentIndex = 0; refresh(); list.firstSelectable() }
    function currentId() { var r = list.model[list.currentIndex]; return r ? (r.id || "") : "" }
    function press(id) {
        var res = studio.activate(page, id)
        if (res === "back") { studio.leave(); page = "home"; refresh() }
        else refresh()
    }
    function adjust(d) { if (page !== "home") studio.adjust(page, currentId(), d) }
    function cardPress(i) {
        var id = cards[i].id
        if (!studio.available) { studio.fix(); return }
        if (id === "beat" || id === "record" || id === "mix") goPage(id)
        else { studio.activate("home", id); refresh() }
    }
    function handleKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape || k === Qt.Key_B) {
            if (page === "home") { studio.leave(); closed() } else { studio.leave(); refresh() }
            return
        }
        if (page === "home") {
            if (k === Qt.Key_Left) homeIdx = homeIdx === 0 || homeIdx === 3 ? homeIdx : homeIdx - 1
            else if (k === Qt.Key_Right) homeIdx = homeIdx === 2 || homeIdx === 4 ? homeIdx : homeIdx + 1
            else if (k === Qt.Key_Down && homeIdx < 3) homeIdx = homeIdx === 2 ? 4 : 3
            else if (k === Qt.Key_Up && homeIdx >= 3) homeIdx = homeIdx === 4 ? 2 : 0
            else if (isEnter(k)) cardPress(homeIdx)
            return
        }
        if (k === Qt.Key_Up) list.move(-1)
        else if (k === Qt.Key_Down) list.move(1)
        else if (k === Qt.Key_Left) adjust(-1)
        else if (k === Qt.Key_Right) adjust(1)
        else if (isEnter(k)) press(currentId())
    }
    Connections { target: studio; function onChanged() { st.refresh() } }
    Component.onCompleted: refresh()

    Rectangle { anchors.fill: parent; color: st.ink }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#0d1409" }
            GradientStop { position: 1.0; color: "#070a07" }
        }
    }

    // ------------------------------------------------------------------ header
    Row {
        id: head
        x: 40 * st.u; y: 24 * st.u
        spacing: 14 * st.u
        Text { text: "HOODLUM ASYLUM"; color: st.gold; font.pixelSize: 34 * st.u; font.bold: true; font.letterSpacing: 3 * st.u }
        Text { text: "STUDIO"; color: st.green; font.pixelSize: 34 * st.u; font.bold: true; font.letterSpacing: 3 * st.u }
    }
    Text {
        anchors.right: parent.right; anchors.rightMargin: 40 * st.u; y: 34 * st.u
        text: studio.projectName + (studio.isPlaying ? "   \u25b6 playing" : "")
        color: studio.isPlaying ? st.green : "#9a9f8a"; font.pixelSize: 20 * st.u
    }
    Rectangle { x: 40 * st.u; y: 76 * st.u; width: parent.width - 80 * st.u; height: 3 * st.u; radius: 2
        gradient: Gradient { orientation: Gradient.Horizontal
            GradientStop { position: 0; color: st.gold } GradientStop { position: 1; color: st.green } } }

    // ------------------------------------------------------------------ home: three big cards
    Item {
        id: homeView
        visible: st.page === "home"
        x: 40 * st.u; y: 100 * st.u; width: parent.width - 80 * st.u; height: parent.height - 190 * st.u

        Text {
            visible: !studio.available
            anchors.centerIn: parent; width: parent.width * 0.8
            wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter
            text: studio.helpText + (studio.fixText !== "" ? "\n\n" + studio.fixText : "") + "\n\nPress Enter / A (or click here) to fix it."
            color: st.gold; font.pixelSize: 24 * st.u
            MouseArea { anchors.fill: parent; onClicked: studio.fix() }
        }
        Rectangle {
            visible: !studio.available
            objectName: "studioFixButton"
            anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 30 * st.u
            width: 520 * st.u; height: 76 * st.u; radius: 16 * st.u; color: "#1d2a10"; border.width: 4 * st.u; border.color: st.gold
            Text { anchors.centerIn: parent; color: st.gold; font.pixelSize: 30 * st.u; font.bold: true
                   text: studio.fixing ? "Working on it..." : "Fix Studio" }
            MouseArea { anchors.fill: parent; onClicked: studio.fix() }
        }
        Row {
            id: bigRow
            visible: studio.available
            spacing: 22 * st.u
            width: parent.width; height: parent.height * 0.66
            Repeater {
                model: st.cards.slice(0, 3)
                Rectangle {
                    id: card
                    required property var modelData
                    required property int index
                    readonly property bool sel: st.homeIdx === index
                    width: (bigRow.width - 44 * st.u) / 3; height: bigRow.height
                    radius: 22 * st.u
                    color: sel ? "#1d2a10" : "#10170c"
                    border.width: (sel ? 5 : 2) * st.u
                    border.color: sel ? st.gold : "#2b3a1c"
                    scale: sel ? 1.03 : 1.0
                    Behavior on scale { enabled: Theme.anim; NumberAnimation { duration: 120 } }
                    Column {
                        anchors.centerIn: parent; width: parent.width - 50 * st.u; spacing: 16 * st.u
                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter
                            text: card.index === 0 ? "\u25a6" : card.index === 1 ? "\u25cf" : "\u2261"
                            color: card.index === 1 ? "#e0453a" : (card.sel ? st.gold : st.green); font.pixelSize: 90 * st.u }
                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                            text: (card.index + 1) + ".  " + card.modelData.title; color: card.sel ? st.gold : "#f0ecd8"
                            font.pixelSize: 36 * st.u; font.bold: true }
                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                            text: card.modelData.sub; color: "#a8ad98"; font.pixelSize: 20 * st.u }
                    }
                    MouseArea { anchors.fill: parent; onClicked: { st.homeIdx = card.index; st.cardPress(card.index) } }
                }
            }
        }
        Row {
            visible: studio.available
            y: bigRow.height + 24 * st.u
            spacing: 22 * st.u
            Repeater {
                model: st.cards.slice(3)
                Rectangle {
                    id: small
                    required property var modelData
                    required property int index
                    readonly property bool sel: st.homeIdx === index + 3
                    width: 420 * st.u; height: 70 * st.u; radius: 14 * st.u
                    color: sel ? "#1d2a10" : "#10170c"
                    border.width: (sel ? 4 : 2) * st.u; border.color: sel ? st.gold : "#2b3a1c"
                    Text { anchors.centerIn: parent; text: small.modelData.title; color: small.sel ? st.gold : "#d8d4c0"
                        font.pixelSize: 24 * st.u; font.bold: true; elide: Text.ElideRight; width: parent.width - 30 * st.u
                        horizontalAlignment: Text.AlignHCenter }
                    MouseArea { anchors.fill: parent; onClicked: { st.homeIdx = small.index + 3; st.cardPress(small.index + 3) } }
                }
            }
        }
    }

    // ------------------------------------------------------------------ list pages
    Item {
        id: listView
        visible: st.page !== "home"
        x: 40 * st.u; y: 96 * st.u; width: parent.width - 80 * st.u; height: parent.height - 186 * st.u

        Text {
            id: stepsTitle
            text: st.page === "beat" ? "1.  MAKE A BEAT" : st.page === "record" ? "2.  RECORD YOUR VOICE" : "3.  MIX & SHARE"
            color: st.gold; font.pixelSize: 24 * st.u; font.bold: true
        }
        // the step-sequencer grid (kick, snare, ... one little square per 16th note) with a moving playhead
        Rectangle {
            id: gridBox
            visible: st.page === "beat"
            y: 36 * st.u; width: parent.width; height: visible ? 214 * st.u : 0
            radius: 12 * st.u; color: "#0c1209"; border.width: 2 * st.u; border.color: "#2b3a1c"
            property var g: st.page === "beat" ? studio.grid() : []
            Connections { target: studio; function onChanged() { if (st.page === "beat") gridBox.g = studio.grid() } }
            readonly property real labelW: 88 * st.u
            Column {
                x: 10 * st.u; y: 8 * st.u; spacing: 2 * st.u
                Repeater {
                    model: gridBox.g
                    Item {
                        required property var modelData
                        required property int index
                        width: gridBox.width - 20 * st.u; height: 22 * st.u
                        Text { text: modelData.name; color: index < 5 ? st.gold : st.green; font.pixelSize: 15 * st.u
                            width: gridBox.labelW; anchors.verticalCenter: parent.verticalCenter }
                        Row {
                            x: gridBox.labelW; spacing: 1 * st.u; height: parent.height
                            Repeater {
                                model: modelData.cells
                                Rectangle {
                                    required property int modelData
                                    required property int index
                                    readonly property real cw: (gridBox.width - 20 * st.u - gridBox.labelW) / 64 - 1 * st.u
                                    width: cw; height: 20 * st.u; radius: 2
                                    color: modelData ? (index % 16 === 0 ? "#ffd24a" : st.gold) : (index % 4 === 0 ? "#1d2616" : "#141b10")
                                    opacity: modelData ? 1 : 0.9
                                }
                            }
                        }
                    }
                }
            }
            Rectangle {
                id: playhead
                visible: studio.isPlaying
                y: 4 * st.u; height: parent.height - 8 * st.u; width: 3 * st.u; color: st.green
                x: 10 * st.u + gridBox.labelW
                NumberAnimation on x {
                    running: studio.isPlaying
                    from: 10 * st.u + gridBox.labelW; to: gridBox.width - 10 * st.u
                    duration: Math.max(500, studio.loopSeconds * 1000); loops: Animation.Infinite
                }
            }
        }
        Rectangle {
            visible: st.page === "record" && studio.isRecordingNow
            y: 36 * st.u; width: parent.width; height: 54 * st.u; radius: 12 * st.u; color: "#3a0f0c"
            Text { anchors.centerIn: parent; text: "\u25cf  RECORDING - rap or sing now"; color: "#ff6a5a"; font.pixelSize: 28 * st.u; font.bold: true }
        }
        MenuList {
            id: list
            u: st.u
            accent: st.gold; selColor: "#1d2a10"; valueColor: st.gold
            y: (st.page === "beat" ? 258 : 40) * st.u
            width: parent.width; height: parent.height - y
            onClicked: function (i) { list.currentIndex = i; st.press(st.currentId()) }
        }
    }

    // ------------------------------------------------------------------ bottom bar: touch buttons + hint
    Row {
        id: bar
        anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * st.u
        x: 40 * st.u; spacing: 16 * st.u
        Repeater {
            model: [ { t: "\u25c0", k: "less" }, { t: "\u25b6", k: "more" }, { t: "ENTER", k: "ok" }, { t: "BACK", k: "back" } ]
            Rectangle {
                required property var modelData
                visible: st.page !== "home" || modelData.k === "back"
                width: (modelData.k === "less" || modelData.k === "more" ? 90 : 150) * st.u; height: 56 * st.u; radius: 12 * st.u
                color: "#10170c"; border.width: 2 * st.u; border.color: st.gold
                Text { anchors.centerIn: parent; text: modelData.t; color: st.gold; font.pixelSize: 22 * st.u; font.bold: true }
                MouseArea { anchors.fill: parent; onClicked: {
                    if (modelData.k === "less") st.adjust(-1)
                    else if (modelData.k === "more") st.adjust(1)
                    else if (modelData.k === "ok") st.press(st.currentId())
                    else st.handleKey({ key: Qt.Key_Escape })
                } }
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: st.page === "home" ? "Arrows choose  \u00b7  Enter / A opens  \u00b7  Esc / B goes back"
                                     : "Up / Down choose  \u00b7  Left / Right change  \u00b7  Enter / A press  \u00b7  Esc / B back"
            color: "#7d8370"; font.pixelSize: 17 * st.u
        }
    }
}
