import QtQuick

// "Add Games": pick a USB stick (or a folder), tick the games found, copy them into the library.
Item {
    id: imp
    property real u: 1
    property string zone: "buttons"     // list state: buttons | list
    property int btn: 0
    property string summary: ""
    property int tick: 0
    property var rows: []
    readonly property string st: backend.importState
    signal closed()
    signal browseRequested()

    readonly property bool bios: backend.importKind === "bios"
    function open(kind) {
        backend.openImportKind(kind || "games")
        refreshDrives()
    }
    function refreshDrives() {
        rows = backend.importRows()
        driveList.model = rows
        driveList.firstSelectable()
    }
    function updateSummary() { summary = backend.importItems.selectedSizeText(); tick++ }
    function enterList() { zone = "buttons"; btn = 0; list.currentIndex = 0; updateSummary() }
    function startCopy() { if (backend.importItems.selectedCount() > 0) backend.startImportCopy() }
    function toggleAll() { backend.setAllImport(!backend.importItems.allSelected()); updateSummary() }
    function backToDrives() { backend.backToDrives(); refreshDrives() }
    function isEnter(k) { return k === Qt.Key_Return || k === Qt.Key_Enter }

    function handleKey(e) {
        var k = e.key
        if (st === "drives") {
            if (k === Qt.Key_Escape) { closed(); return }
            if (k === Qt.Key_Up) driveList.move(-1)
            else if (k === Qt.Key_Down) driveList.move(1)
            else if (k === Qt.Key_F || k === Qt.Key_F5) refreshDrives()
            else if (isEnter(k) || k === Qt.Key_Space) activateRow(driveList.currentIndex)
        } else if (st === "scanning" || st === "copying") {
            if (k === Qt.Key_Escape || isEnter(k)) {
                var copying = st === "copying"
                backend.cancelImport()
                if (!copying) refreshDrives()
            }
        } else if (st === "list") {
            if (k === Qt.Key_Escape) { backToDrives(); return }
            if (zone === "buttons") {
                if (k === Qt.Key_Left) btn = Math.max(0, btn - 1)
                else if (k === Qt.Key_Right) btn = Math.min(2, btn + 1)
                else if (k === Qt.Key_Down && list.count > 0) zone = "list"
                else if (k === Qt.Key_F) toggleAll()
                else if (isEnter(k) || k === Qt.Key_Space) {
                    if (btn === 0) startCopy()
                    else if (btn === 1) toggleAll()
                    else backToDrives()
                }
            } else {
                var i = list.currentIndex
                if (k === Qt.Key_Up) { if (i > 0) list.currentIndex = i - 1; else zone = "buttons" }
                else if (k === Qt.Key_Down) list.currentIndex = Math.min(list.count - 1, i + 1)
                else if (k === Qt.Key_PageUp) list.currentIndex = Math.max(0, i - 8)
                else if (k === Qt.Key_PageDown) list.currentIndex = Math.min(list.count - 1, i + 8)
                else if (k === Qt.Key_F) toggleAll()
                else if (isEnter(k) || k === Qt.Key_Space) { backend.toggleImportItem(i); updateSummary() }
            }
        } else if (st === "done") {
            if (k === Qt.Key_Left) btn = 0
            else if (k === Qt.Key_Right) btn = 1
            else if (k === Qt.Key_Escape) closed()
            else if (isEnter(k)) { if (btn === 0) closed(); else backToDrives() }
        }
    }
    function activateRow(i) {
        var r = rows[i]
        if (!r) return
        if (r.kind === "drive") backend.startImportScan(r.path)
        else if (r.kind === "refresh") refreshDrives()
        else if (r.kind === "browse") browseRequested()
        else closed()
    }

    Connections {
        target: backend
        function onImportChanged() {
            if (backend.importState === "list") imp.enterList()
            if (backend.importState === "done") imp.btn = 0
        }
    }
    Connections { target: backend.importItems; function onSelectionChanged() { imp.updateSummary() } }

    Rectangle { anchors.fill: parent; color: "#08090e" }
    Item {
        id: head
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 120 * imp.u
        clip: true
        Image {
            anchors.fill: parent
            source: Qt.resolvedUrl("../assets/banner.jpg")
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            sourceSize.width: 1920
        }
        Rectangle { anchors.fill: parent; color: "#88000000" }
        Icon { id: hicon; name: "usb"; size: 58 * imp.u; color: Theme.redBright; stroke: 1.8
               anchors.left: parent.left; anchors.leftMargin: 48 * imp.u; anchors.verticalCenter: parent.verticalCenter }
        Column {
            anchors.left: hicon.right
            anchors.leftMargin: 20 * imp.u
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4 * imp.u
            Text { text: imp.bios ? "ADD BIOS FILES" : "ADD GAMES"; color: Theme.redBright; font.pixelSize: 42 * imp.u; font.bold: true; font.letterSpacing: 4 * imp.u }
            Text {
                color: "#e6e8f2"
                font.pixelSize: 20 * imp.u
                text: imp.st === "drives" ? (imp.bios ? "Copy BIOS / firmware from your own consoles (on a USB stick or folder) to the emulators. Your stick is only read."
                                                   : "Copy games from a USB stick into your library. Your stick is only read, never changed.")
                    : imp.st === "scanning" ? (imp.bios ? "Looking for BIOS files..." : "Looking for games...")
                    : imp.st === "list" ? (imp.bios ? "Tick the files to copy. Each goes to the right folder for its emulator."
                                                    : "Tick the games to copy. They go to ~/Games/Atari/<console> (or your folder for that console).")
                    : imp.st === "copying" ? "Copying - please don't unplug the stick yet." : "All done."
            }
        }
    }
    Rectangle { id: headline; anchors.top: head.bottom; width: parent.width; height: 3 * imp.u; color: Theme.red }

    // ---- step 1: drives
    Item {
        anchors.top: headline.bottom
        anchors.topMargin: 20 * imp.u
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 20 * imp.u
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(parent.width - 100 * imp.u, 1400 * imp.u)
        visible: imp.st === "drives"
        Item {
            id: noUsb
            width: parent.width
            height: backend.importMessage !== "" ? noUsbText.implicitHeight + 16 * imp.u : 0
            Text {
                id: noUsbText
                width: parent.width
                wrapMode: Text.Wrap
                text: backend.importMessage
                color: Theme.yellow
                font.pixelSize: 24 * imp.u
                font.bold: true
            }
        }
        MenuList {
            id: driveList
            u: imp.u
            anchors.top: noUsb.bottom
            anchors.bottom: parent.bottom
            width: parent.width
            model: []
            onClicked: function (i) { imp.activateRow(i) }
        }
    }

    // ---- scanning
    Item {
        anchors.fill: parent
        anchors.topMargin: 200 * imp.u
        visible: imp.st === "scanning"
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 24 * imp.u
            Rectangle {
                width: 420 * imp.u; height: 10 * imp.u; radius: 5 * imp.u; color: "#1a1d2c"
                clip: true
                Rectangle {
                    id: sweep
                    width: 130 * imp.u; height: parent.height; radius: 5 * imp.u; color: Theme.red
                    SequentialAnimation on x {
                        running: imp.st === "scanning"
                        loops: Animation.Infinite
                        NumberAnimation { from: -130 * imp.u; to: 420 * imp.u; duration: 1100; easing.type: Easing.InOutQuad }
                    }
                }
            }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: backend.importMessage; color: "#e6e8f2"
                   font.pixelSize: 24 * imp.u; elide: Text.ElideMiddle; width: 1000 * imp.u; horizontalAlignment: Text.AlignHCenter }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "Esc / B to cancel"; color: Theme.dim; font.pixelSize: 20 * imp.u }
        }
    }

    // ---- step 2: checklist
    Item {
        anchors.top: headline.bottom
        anchors.topMargin: 18 * imp.u
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 18 * imp.u
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(parent.width - 100 * imp.u, 1500 * imp.u)
        visible: imp.st === "list"
        Text {
            id: listMsg
            width: parent.width
            wrapMode: Text.Wrap
            text: backend.importMessage
            color: list.count > 0 ? "#e6e8f2" : Theme.yellow
            font.pixelSize: 20 * imp.u
        }
        Row {
            id: btnRow
            anchors.top: listMsg.bottom
            anchors.topMargin: 12 * imp.u
            spacing: 14 * imp.u
            Repeater {
                model: [
                    { t: (imp.tick, "COPY ") + backend.importItems.selectedCount() + " (" + imp.summary + ")", primary: true },
                    { t: (imp.tick, backend.importItems.allSelected()) ? "SELECT NONE" : "SELECT ALL", primary: false },
                    { t: "BACK", primary: false }
                ]
                Rectangle {
                    required property var modelData
                    required property int index
                    readonly property bool sel: imp.zone === "buttons" && imp.btn === index
                    width: (index === 0 ? 400 : 230) * imp.u
                    height: 56 * imp.u
                    radius: 10 * imp.u
                    opacity: index === 0 && (imp.tick, backend.importItems.selectedCount()) === 0 ? 0.45 : 1
                    gradient: Gradient {
                        GradientStop { position: 0; color: modelData.primary ? (sel ? "#ff4a52" : "#ee2a34") : "#1a1d2c" }
                        GradientStop { position: 1; color: modelData.primary ? (sel ? "#c4161f" : "#a8121b") : "#141622" }
                    }
                    border.width: sel ? 3 * imp.u : 1.5 * imp.u
                    border.color: sel ? "white" : (modelData.primary ? "transparent" : "#3a4260")
                    Text { anchors.centerIn: parent; text: modelData.t; color: "white"
                           font.pixelSize: 19 * imp.u; font.bold: true; font.letterSpacing: 1 * imp.u }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            imp.zone = "buttons"; imp.btn = index
                            if (index === 0) imp.startCopy(); else if (index === 1) imp.toggleAll(); else imp.backToDrives()
                        }
                    }
                }
            }
        }
        ListView {
            id: list
            anchors.top: btnRow.bottom
            anchors.topMargin: 14 * imp.u
            anchors.bottom: parent.bottom
            width: parent.width
            clip: true
            spacing: 6 * imp.u
            model: backend.importItems
            highlightMoveDuration: 60
            delegate: Rectangle {
                id: item
                required property int index
                required property string name
                required property string systemName
                required property string sizeText
                required property bool checked
                required property string rel
                required property string kind
                required property string extra
                readonly property bool sel: imp.zone === "list" && ListView.isCurrentItem
                width: list.width
                height: 52 * imp.u
                radius: 8 * imp.u
                color: sel ? "#2a0b10" : "#121420"
                border.width: sel ? 3 * imp.u : 1 * imp.u
                border.color: sel ? Theme.redBright : "#262a3c"
                Rectangle {
                    id: box
                    anchors.left: parent.left
                    anchors.leftMargin: 16 * imp.u
                    anchors.verticalCenter: parent.verticalCenter
                    width: 28 * imp.u; height: 28 * imp.u; radius: 6 * imp.u
                    color: item.checked ? Theme.red : "transparent"
                    border.width: 2 * imp.u
                    border.color: item.checked ? Theme.red : "#5a6080"
                    Icon { anchors.centerIn: parent; visible: item.checked; name: "check"; size: 20 * imp.u; stroke: 3; color: "white" }
                }
                Text {
                    anchors.left: box.right
                    anchors.leftMargin: 16 * imp.u
                    anchors.right: pill.left
                    anchors.rightMargin: 12 * imp.u
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: item.name + (item.kind === "folder" ? "  (folder)" : "") + (item.extra !== "" ? "   \u2014  " + item.extra : "")
                    color: "white"
                    font.pixelSize: 21 * imp.u
                    font.bold: true
                }
                Rectangle {
                    id: pill
                    anchors.right: sz.left
                    anchors.rightMargin: 14 * imp.u
                    anchors.verticalCenter: parent.verticalCenter
                    width: pillText.implicitWidth + 24 * imp.u
                    height: 30 * imp.u
                    radius: 15 * imp.u
                    color: "#1d2236"
                    border.width: 1; border.color: "#3a4260"
                    Text { id: pillText; anchors.centerIn: parent; text: item.systemName; color: "#cfd3e6"; font.pixelSize: 15 * imp.u }
                }
                Text {
                    id: sz
                    anchors.right: parent.right
                    anchors.rightMargin: 18 * imp.u
                    anchors.verticalCenter: parent.verticalCenter
                    width: 100 * imp.u
                    horizontalAlignment: Text.AlignRight
                    text: item.sizeText
                    color: Theme.dim
                    font.pixelSize: 18 * imp.u
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: { imp.zone = "list"; list.currentIndex = item.index; backend.toggleImportItem(item.index); imp.updateSummary() }
                }
            }
        }
    }

    // ---- step 3: copying
    Item {
        anchors.fill: parent
        anchors.topMargin: 190 * imp.u
        visible: imp.st === "copying"
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 22 * imp.u
            width: Math.min(parent.width - 160 * imp.u, 1100 * imp.u)
            Text { width: parent.width; text: backend.importMessage; color: "#e6e8f2"; font.pixelSize: 26 * imp.u; font.bold: true
                   horizontalAlignment: Text.AlignHCenter }
            Rectangle {
                width: parent.width; height: 30 * imp.u; radius: 15 * imp.u; color: "#161828"
                border.width: 1; border.color: "#3a4260"
                Rectangle {
                    width: Math.max(parent.height, parent.width * backend.importProgress)
                    height: parent.height; radius: parent.radius
                    gradient: Gradient { orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: "#a8121b" } GradientStop { position: 1; color: "#ff3a43" } }
                    Behavior on width { NumberAnimation { duration: 120 } }
                }
            }
            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideMiddle
                   text: Math.round(backend.importProgress * 100) + "%   " + backend.importCurrent; color: Theme.dim; font.pixelSize: 21 * imp.u }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 260 * imp.u; height: 56 * imp.u; radius: 10 * imp.u
                color: "#2a0b10"; border.width: 3 * imp.u; border.color: "white"
                Text { anchors.centerIn: parent; text: "CANCEL"; color: "white"; font.pixelSize: 20 * imp.u; font.bold: true }
                MouseArea { anchors.fill: parent; onClicked: backend.cancelImport() }
            }
        }
    }

    // ---- done
    Item {
        anchors.fill: parent
        anchors.topMargin: 190 * imp.u
        visible: imp.st === "done"
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 30 * imp.u
            width: Math.min(parent.width - 160 * imp.u, 1100 * imp.u)
            Icon { anchors.horizontalCenter: parent.horizontalCenter; name: "check"; size: 80 * imp.u; stroke: 2.4; color: Theme.green }
            Text { width: parent.width; text: backend.importMessage; color: "white"; font.pixelSize: 26 * imp.u; font.bold: true
                   wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 16 * imp.u
                Repeater {
                    model: ["DONE", "ADD MORE"]
                    Rectangle {
                        required property string modelData
                        required property int index
                        readonly property bool sel: imp.btn === index
                        width: 240 * imp.u; height: 58 * imp.u; radius: 10 * imp.u
                        color: index === 0 ? (sel ? "#d8222c" : "#a8121b") : "#171a28"
                        border.width: sel ? 3 * imp.u : 1.5 * imp.u
                        border.color: sel ? "white" : "#3a4260"
                        Text { anchors.centerIn: parent; text: modelData; color: "white"; font.pixelSize: 20 * imp.u; font.bold: true }
                        MouseArea { anchors.fill: parent; onClicked: { if (index === 0) imp.closed(); else imp.backToDrives() } }
                    }
                }
            }
        }
    }
}
