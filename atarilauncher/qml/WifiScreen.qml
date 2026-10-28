import QtQuick

// WiFi: nearby networks with signal strength, a full on-screen keyboard (works with the D-pad + A, a mouse / touch, or a real
// keyboard) for the password, connected / failed messages, hidden networks and Forget. Talks to backend.wifi (nmcli).
Item {
    id: ws
    property real u: 1
    property var wifi: backend.wifi
    property string page: "list"            // list | pass | ssid
    property int idx: 0                     // highlighted row in the list
    property string target: ""              // network being joined
    property bool hidden: false
    property string text: ""                // what is being typed
    property bool reveal: false
    property int kset: 0                   // 0 abc  1 ABC  2 symbols
    property int kr: 0
    property int kc: 0
    property string confirmForget: ""
    signal closed()

    readonly property var ksets: [
        ["1234567890", "qwertyuiop", "asdfghjkl.", "zxcvbnm-_@"],
        ["1234567890", "QWERTYUIOP", "ASDFGHJKL,", "ZXCVBNM-_@"],
        ["!@#$%^&*()", "-_=+[]{};:", "'\",.<>/?\\|", "~`"]
    ]
    readonly property var actions: ["ABC / abc", "123 #+=", "SPACE", "DELETE", "SHOW", "DONE"]
    readonly property var rows: {
        var r = wifi.networks.slice()
        r.push({ ssid: "Join a hidden network...", special: "hidden" })
        return r
    }
    readonly property bool unavailable: wifi.state === "unavailable"
    readonly property bool working: wifi.state === "connecting" || wifi.state === "scanning"

    function isEnter(k) { return k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space }
    function open() {
        page = "list"; idx = 0; text = ""; confirmForget = ""
        wifi.refresh()
    }
    function close() { page = "list"; closed() }
    function rowLen(r) { return r < 4 ? ksets[kset][r].length : actions.length }
    function typeChar(c) { text += c }
    function pressKey(r, c) {
        if (r < 4) { var s = ksets[kset][r]; if (c < s.length) typeChar(s.charAt(c)); return }
        var a = actions[c]
        if (a === "ABC / abc") kset = kset === 0 ? 1 : 0
        else if (a === "123 #+=") kset = kset === 2 ? 0 : 2
        else if (a === "SPACE") typeChar(" ")
        else if (a === "DELETE") text = text.slice(0, -1)
        else if (a === "SHOW") reveal = !reveal
        else if (a === "DONE") finish()
    }
    function finish() {
        if (page === "ssid") {
            if (text.trim() === "") return
            target = text.trim(); hidden = true; text = ""; page = "pass"; kr = 0; kc = 0
        } else if (page === "pass") {
            if (text === "" && !hidden) return
            var s = target, p = text
            text = ""; reveal = false; page = "list"
            wifi.connect(s, p, hidden)
        }
    }
    function activateRow(i) {
        var r = rows[i]
        if (!r) return
        confirmForget = ""
        if (r.special === "hidden") { target = ""; hidden = true; text = ""; kset = 0; kr = 0; kc = 0; page = "ssid"; return }
        if (r.inUse) return
        if (!r.secure || r.known) { wifi.connect(r.ssid, "", false); return }
        target = r.ssid; hidden = false; text = ""; reveal = false; kset = 0; kr = 0; kc = 0; page = "pass"
    }
    function forgetRow(i) {
        var r = rows[i]
        if (!r || !r.known) return
        if (confirmForget !== r.ssid) { confirmForget = r.ssid; return }
        confirmForget = ""
        wifi.forget(r.ssid)
    }
    function handleKey(e) {
        var k = e.key
        if (unavailable) {
            if (k === Qt.Key_Escape || k === Qt.Key_B) close()
            else if (isEnter(k) || k === Qt.Key_Tab) { if (wifi.adapterState === "radio_off") wifi.turnOn(); else wifi.refresh() }
            return
        }
        if (page === "list") {
            if (k === Qt.Key_Escape || k === Qt.Key_B) { close(); return }
            if (working) return
            if (k === Qt.Key_Up) idx = Math.max(0, idx - 1)
            else if (k === Qt.Key_Down) idx = Math.min(rows.length - 1, idx + 1)
            else if (isEnter(k)) activateRow(idx)
            else if (k === Qt.Key_F || k === Qt.Key_Delete) forgetRow(idx)
            else if (k === Qt.Key_Tab || k === Qt.Key_R || k === Qt.Key_F5) { confirmForget = ""; wifi.refresh() }
            return
        }
        // typing pages
        if (k === Qt.Key_Escape) {
            if (page === "pass" && hidden && target !== "") { page = "ssid"; text = target } else { page = "list"; text = "" }
            return
        }
        var printable = e.text !== undefined && e.text.length === 1 && e.text.charCodeAt(0) >= 32 && !(e.modifiers & Qt.ControlModifier)
        if (printable && k !== Qt.Key_Space) { typeChar(e.text); return }
        if (printable && k === Qt.Key_Space) { typeChar(" "); return }
        if (k === Qt.Key_Backspace) { text = text.slice(0, -1); return }
        if ((k === Qt.Key_Return || k === Qt.Key_Enter) && e.text !== undefined && e.text.length > 0) { finish(); return }   // a real keyboard's Enter
        // controller / arrow navigation of the on-screen keyboard
        if (k === Qt.Key_Left) kc = Math.max(0, kc - 1)
        else if (k === Qt.Key_Right) kc = Math.min(rowLen(kr) - 1, kc + 1)
        else if (k === Qt.Key_Up) { if (kr === 4) { kr = 3; kc = Math.min(ksets[kset][3].length - 1, Math.floor((kc + 0.5) * ksets[kset][3].length / actions.length)) } else kr = Math.max(0, kr - 1)
                                    kc = Math.min(kc, rowLen(kr) - 1) }
        else if (k === Qt.Key_Down) { if (kr === 3) { kc = Math.min(actions.length - 1, Math.floor(kc * actions.length / ksets[kset][3].length)); kr = 4 } else if (kr < 3) { kr++; kc = Math.min(kc, rowLen(kr) - 1) } }
        else if (isEnter(k)) pressKey(kr, kc)
        else if (k === Qt.Key_Q) text = text.slice(0, -1)                         // controller L1: backspace
        else if (k === Qt.Key_E) kset = (kset + 1) % 3                          // controller R1: next key set
        else if (k === Qt.Key_Slash) reveal = !reveal                             // controller "search": show / hide
        else if (k === Qt.Key_B) handleKey({ key: Qt.Key_Escape, text: "" })
    }

    Connections {
        target: ws.wifi
        function onChanged() {
            if (ws.idx >= ws.rows.length) ws.idx = Math.max(0, ws.rows.length - 1)
        }
    }

    Rectangle { anchors.fill: parent; color: "#06080d" }
    Image {
        anchors.fill: parent
        source: Qt.resolvedUrl("../assets/banner.jpg")
        fillMode: Image.PreserveAspectCrop
        opacity: 0.16
        asynchronous: true
    }

    // ---- header
    Item {
        id: head
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 120 * ws.u
        Icon { id: hIc; name: "wifi"; size: 54 * ws.u; color: Theme.redBright; stroke: 2.2
               anchors.left: parent.left; anchors.leftMargin: 64 * ws.u; anchors.verticalCenter: parent.verticalCenter }
        Column {
            anchors.left: hIc.right
            anchors.leftMargin: 22 * ws.u
            anchors.verticalCenter: parent.verticalCenter
            Text { text: "WIFI"; color: "white"; font.pixelSize: 44 * ws.u; font.bold: true; font.letterSpacing: 6 * ws.u }
            Text { objectName: "wifiStatus"; text: ws.wifi.statusText; color: ws.wifi.statusText.indexOf("Connected") === 0 ? Theme.green : Theme.dim
                   font.pixelSize: 24 * ws.u }
        }
        Rectangle {   // the visible Back button for mouse / touch (keyboard: Esc, controller: B)
            anchors.right: parent.right
            anchors.rightMargin: 64 * ws.u
            anchors.verticalCenter: parent.verticalCenter
            width: 190 * ws.u; height: 60 * ws.u; radius: height / 2
            color: "#26ffffff"
            Text { anchors.centerIn: parent; text: "\u25c0  Back"; color: "white"; font.pixelSize: 26 * ws.u; font.bold: true }
            MouseArea { anchors.fill: parent; onClicked: { if (ws.page === "list" || ws.unavailable) ws.close(); else { ws.page = "list"; ws.text = "" } } }
        }
    }

    // ---- no adapter / radio off / NetworkManager missing
    Column {
        visible: ws.unavailable
        anchors.centerIn: parent
        width: 1100 * ws.u
        spacing: 30 * ws.u
        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
               text: ws.wifi.adapterState === "noadapter" ? "No WiFi adapter found" : ws.wifi.adapterState === "radio_off" ? "WiFi is switched off" : "WiFi is not available"
               color: Theme.redBright; font.pixelSize: 46 * ws.u; font.bold: true }
        Text { objectName: "wifiUnavailable"; width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
               text: ws.wifi.message; color: Theme.text; font.pixelSize: 30 * ws.u }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 420 * ws.u; height: 84 * ws.u; radius: 12 * ws.u; color: Theme.red
            Text { anchors.centerIn: parent; font.pixelSize: 30 * ws.u; font.bold: true; color: "white"
                   text: ws.wifi.adapterState === "radio_off" ? "TURN WIFI ON" : "SCAN AGAIN" }
            MouseArea { anchors.fill: parent; onClicked: { if (ws.wifi.adapterState === "radio_off") ws.wifi.turnOn(); else ws.wifi.refresh() } }
        }
    }

    // ---- list page
    Item {
        visible: !ws.unavailable && ws.page === "list"
        anchors.top: head.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 64 * ws.u
        anchors.topMargin: 10 * ws.u

        Rectangle {   // result of the last try: green = connected, red = failed
            id: banner
            visible: ws.wifi.message !== "" && ws.wifi.state !== "connecting"
            anchors.top: parent.top
            width: parent.width
            height: visible ? 70 * ws.u : 0
            radius: 12 * ws.u
            color: ws.wifi.messageOk ? "#13301a" : "#3a1015"
            border.width: 2 * ws.u
            border.color: ws.wifi.messageOk ? Theme.green : Theme.redBright
            Text { objectName: "wifiMessage"; anchors.fill: parent; anchors.margins: 14 * ws.u; verticalAlignment: Text.AlignVCenter
                   text: ws.wifi.message; color: "white"; font.pixelSize: 26 * ws.u; elide: Text.ElideRight }
        }
        ListView {
            id: list
            objectName: "wifiList"
            anchors.top: banner.bottom
            anchors.topMargin: 14 * ws.u
            anchors.bottom: hints.top
            anchors.bottomMargin: 10 * ws.u
            width: parent.width
            clip: true
            spacing: 8 * ws.u
            model: ws.rows
            currentIndex: ws.idx
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
            delegate: Rectangle {
                id: row
                required property var modelData
                required property int index
                readonly property bool sel: index === ws.idx
                width: list.width
                height: 82 * ws.u
                radius: 12 * ws.u
                color: sel ? "#3a0a10" : "#0f111a"
                border.width: sel ? 3 * ws.u : 1.5 * ws.u
                border.color: sel ? Theme.redBright : "#272b3d"
                Row {   // signal bars
                    id: bars
                    visible: !modelData.special
                    anchors.left: parent.left
                    anchors.leftMargin: 26 * ws.u
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 5 * ws.u
                    Repeater {
                        model: 4
                        Rectangle {
                            required property int index
                            width: 9 * ws.u
                            height: (12 + index * 9) * ws.u
                            anchors.bottom: parent.bottom
                            radius: 2 * ws.u
                            color: index < row.modelData.bars ? (row.modelData.inUse ? Theme.green : "white") : "#3a3f55"
                        }
                    }
                }
                Text {
                    anchors.left: bars.visible ? bars.right : parent.left
                    anchors.leftMargin: bars.visible ? 26 * ws.u : 28 * ws.u
                    anchors.right: tags.left
                    anchors.rightMargin: 16 * ws.u
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.ssid
                    elide: Text.ElideRight
                    color: modelData.special ? Theme.dim : "white"
                    font.pixelSize: 32 * ws.u
                    font.bold: !modelData.special
                }
                Row {
                    id: tags
                    anchors.right: parent.right
                    anchors.rightMargin: 24 * ws.u
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 12 * ws.u
                    Rectangle { visible: modelData.inUse === true; height: 40 * ws.u; width: ct.implicitWidth + 28 * ws.u; radius: height / 2; color: "#13301a"; border.color: Theme.green; border.width: 1.5 * ws.u
                                Text { id: ct; anchors.centerIn: parent; text: "Connected"; color: "#bff0c0"; font.pixelSize: 20 * ws.u; font.bold: true } }
                    Rectangle { visible: modelData.known === true && modelData.inUse !== true; height: 40 * ws.u; width: st.implicitWidth + 28 * ws.u; radius: height / 2; color: "#1b2036"; border.color: Theme.blue; border.width: 1.5 * ws.u
                                Text { id: st; anchors.centerIn: parent; text: "Saved"; color: "#b9d4ff"; font.pixelSize: 20 * ws.u; font.bold: true } }
                    Text { visible: !modelData.special; anchors.verticalCenter: parent.verticalCenter; text: modelData.security || ""; color: Theme.dim; font.pixelSize: 22 * ws.u }
                }
                MouseArea { anchors.fill: parent; onClicked: { ws.idx = index; ws.activateRow(index) } }
            }
        }
        Text {
            visible: ws.wifi.state === "ready" && ws.wifi.networks.length === 0
            anchors.centerIn: list
            text: "No networks found. Move closer to the router and press Scan."
            color: Theme.dim
            font.pixelSize: 28 * ws.u
        }
        Rectangle {   // busy overlay
            visible: ws.working
            anchors.fill: list
            radius: 12 * ws.u
            color: "#cc06080d"
            Text { objectName: "wifiBusy"; anchors.centerIn: parent; color: "white"; font.pixelSize: 36 * ws.u; font.bold: true
                   text: ws.wifi.state === "connecting" ? ws.wifi.message : "Looking for networks..." }
        }
        Row {
            id: hints
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 18 * ws.u
            Repeater {
                model: [
                    { t: "Connect  (A / Enter)", f: function () { ws.activateRow(ws.idx) } },
                    { t: "Scan  (Tab / R)", f: function () { ws.wifi.refresh() } },
                    { t: ws.confirmForget !== "" ? "Press again to forget" : "Forget  (F / Delete)", f: function () { ws.forgetRow(ws.idx) } },
                    { t: "Back  (B / Esc)", f: function () { ws.close() } }
                ]
                Rectangle {
                    required property var modelData
                    height: 56 * ws.u; width: ht.implicitWidth + 36 * ws.u; radius: height / 2
                    color: "#1b1e2e"; border.color: "#33384f"; border.width: 1.5 * ws.u
                    Text { id: ht; anchors.centerIn: parent; text: modelData.t; color: "#d6d9e6"; font.pixelSize: 21 * ws.u; font.bold: true }
                    MouseArea { anchors.fill: parent; onClicked: modelData.f() }
                }
            }
        }
    }

    // ---- typing pages (password / hidden network name)
    Column {
        visible: !ws.unavailable && ws.page !== "list"
        anchors.top: head.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: 16 * ws.u
        spacing: 16 * ws.u
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: ws.page === "ssid" ? "NAME OF THE HIDDEN NETWORK" : (ws.hidden && ws.target !== "" ? "PASSWORD FOR " + ws.target + " (leave empty if open)" : "PASSWORD FOR " + ws.target)
            color: Theme.redBright; font.pixelSize: 32 * ws.u; font.bold: true; font.letterSpacing: 3 * ws.u
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 1100 * ws.u; height: 84 * ws.u; radius: 12 * ws.u; color: "#121420"; border.color: Theme.red; border.width: 3 * ws.u
            Text {
                objectName: "wifiField"
                anchors.left: parent.left; anchors.leftMargin: 26 * ws.u; anchors.right: parent.right; anchors.rightMargin: 26 * ws.u
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideLeft
                text: (ws.page === "pass" && !ws.reveal ? ws.text.replace(/./g, "\u2022") : ws.text) + "\u258c"
                color: Theme.text; font.pixelSize: 42 * ws.u
            }
        }
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8 * ws.u
            Repeater {
                model: 4
                Row {
                    required property int index
                    readonly property int r: index
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8 * ws.u
                    Repeater {
                        model: ws.ksets[ws.kset][r].length
                        Rectangle {
                            required property int index
                            readonly property bool sel: ws.kr === r && ws.kc === index
                            width: 96 * ws.u; height: 76 * ws.u; radius: 8 * ws.u
                            color: sel ? Theme.red : "#121420"; border.color: "#2c3044"; border.width: sel ? 0 : 1.5 * ws.u
                            Text { anchors.centerIn: parent; text: ws.ksets[ws.kset][r].charAt(index); color: "white"; font.pixelSize: 36 * ws.u; font.bold: true }
                            MouseArea { anchors.fill: parent; onClicked: { ws.kr = r; ws.kc = index; ws.pressKey(r, index) } }
                        }
                    }
                }
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 8 * ws.u
                Repeater {
                    model: ws.actions
                    Rectangle {
                        required property string modelData
                        required property int index
                        readonly property bool sel: ws.kr === 4 && ws.kc === index
                        width: 178 * ws.u; height: 76 * ws.u; radius: 8 * ws.u
                        color: sel ? Theme.red : (modelData === "DONE" ? "#13301a" : "#121420")
                        border.color: modelData === "DONE" ? Theme.green : "#2c3044"; border.width: sel ? 0 : 1.5 * ws.u
                        Text { anchors.centerIn: parent; font.pixelSize: 22 * ws.u; font.bold: true; color: "white"
                               text: modelData === "SHOW" && ws.reveal ? "HIDE" : (modelData === "DONE" ? (ws.page === "ssid" ? "NEXT" : "CONNECT") : modelData) }
                        MouseArea { anchors.fill: parent; onClicked: { ws.kr = 4; ws.kc = index; ws.pressKey(4, index) } }
                    }
                }
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Keyboard: just type, Enter = connect, Esc = back.   Controller: D-pad + A,  L1 = delete,  R1 = abc/ABC/123,  B = back"
            color: Theme.dim; font.pixelSize: 21 * ws.u
        }
    }
}
