import QtQuick

// One text / password box with a full on-screen keyboard, used for the administrator password (Quiet boot, Code-only mode, installs)
// and for typing a new file name. Keyboard: just type, Enter = OK, Esc = cancel. Controller: D-pad + A, L1 = delete, R1 = abc/ABC/123,
// B = cancel. Mouse / touch: click the keys. Talks to backend.input* (the text goes back with backend.submitInput, nowhere else).
Item {
    id: dlg
    property real u: 1
    property string text: ""
    property bool reveal: false
    property int kset: 0
    property int kr: 0
    property int kc: 0
    readonly property bool secret: backend.inputSecret
    readonly property bool active: backend.inputActive

    readonly property var ksets: [
        ["1234567890", "qwertyuiop", "asdfghjkl.", "zxcvbnm-_@"],
        ["1234567890", "QWERTYUIOP", "ASDFGHJKL,", "ZXCVBNM-_@"],
        ["!@#$%^&*()", "-_=+[]{};:", "'\",.<>/?\\|", "~`"]
    ]
    readonly property var actions: ["ABC / abc", "123 #+=", "SPACE", "DELETE", "SHOW", "OK"]

    visible: active
    onActiveChanged: if (active) { text = backend.inputInitial; reveal = false; kset = 0; kr = 0; kc = 0 }

    function rowLen(r) { return r < 4 ? ksets[kset][r].length : actions.length }
    function pressKey(r, c) {
        if (r < 4) { var s = ksets[kset][r]; if (c < s.length) text += s.charAt(c); return }
        var a = actions[c]
        if (a === "ABC / abc") kset = kset === 0 ? 1 : 0
        else if (a === "123 #+=") kset = kset === 2 ? 0 : 2
        else if (a === "SPACE") text += " "
        else if (a === "DELETE") text = text.slice(0, -1)
        else if (a === "SHOW") reveal = !reveal
        else if (a === "OK") submit()
    }
    function submit() { var t = text; text = ""; reveal = false; backend.submitInput(t) }
    function cancel() { text = ""; reveal = false; backend.cancelInput() }
    function isEnter(k) { return k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space }
    function handleKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape) { cancel(); return }
        var printable = e.text !== undefined && e.text.length === 1 && e.text.charCodeAt(0) >= 32 && !(e.modifiers & Qt.ControlModifier)
        if (printable) { text += e.text; return }
        if (k === Qt.Key_Backspace) { text = text.slice(0, -1); return }
        if ((k === Qt.Key_Return || k === Qt.Key_Enter) && e.text !== undefined && e.text.length > 0) { submit(); return }
        if (k === Qt.Key_Left) kc = Math.max(0, kc - 1)
        else if (k === Qt.Key_Right) kc = Math.min(rowLen(kr) - 1, kc + 1)
        else if (k === Qt.Key_Up) { if (kr === 4) { kr = 3; kc = Math.min(ksets[kset][3].length - 1, Math.floor((kc + 0.5) * ksets[kset][3].length / actions.length)) } else kr = Math.max(0, kr - 1)
                                    kc = Math.min(kc, rowLen(kr) - 1) }
        else if (k === Qt.Key_Down) { if (kr === 3) { kc = Math.min(actions.length - 1, Math.floor(kc * actions.length / ksets[kset][3].length)); kr = 4 } else if (kr < 3) { kr++; kc = Math.min(kc, rowLen(kr) - 1) } }
        else if (isEnter(k)) pressKey(kr, kc)
        else if (k === Qt.Key_Q) text = text.slice(0, -1)
        else if (k === Qt.Key_E) kset = (kset + 1) % 3
        else if (k === Qt.Key_Slash) reveal = !reveal
        else if (k === Qt.Key_B) cancel()
    }

    Rectangle { anchors.fill: parent; color: "#f2040508" }
    MouseArea { anchors.fill: parent }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        spacing: 14 * dlg.u
        Text {
            objectName: "inputTitle"
            anchors.horizontalCenter: parent.horizontalCenter
            text: backend.inputTitle
            color: Theme.redBright; font.pixelSize: 34 * dlg.u; font.bold: true; font.letterSpacing: 4 * dlg.u
        }
        Text {
            objectName: "inputPrompt"
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(implicitWidth, 1100 * dlg.u)
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
            text: backend.inputPrompt
            color: Theme.text; font.pixelSize: 24 * dlg.u
        }
        Text {
            objectName: "inputError"
            anchors.horizontalCenter: parent.horizontalCenter
            visible: backend.inputError !== ""
            text: backend.inputError
            color: Theme.yellow; font.pixelSize: 26 * dlg.u; font.bold: true
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 1100 * dlg.u; height: 80 * dlg.u; radius: 12 * dlg.u; color: "#121420"; border.color: Theme.red; border.width: 3 * dlg.u
            Text {
                objectName: "inputField"
                anchors.left: parent.left; anchors.leftMargin: 26 * dlg.u; anchors.right: parent.right; anchors.rightMargin: 26 * dlg.u
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideLeft
                text: (dlg.secret && !dlg.reveal ? dlg.text.replace(/./g, "\u2022") : dlg.text) + "\u258c"
                color: Theme.text; font.pixelSize: 40 * dlg.u
            }
        }
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8 * dlg.u
            Repeater {
                model: 4
                Row {
                    required property int index
                    readonly property int r: index
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8 * dlg.u
                    Repeater {
                        model: dlg.ksets[dlg.kset][r].length
                        Rectangle {
                            required property int index
                            readonly property bool sel: dlg.kr === r && dlg.kc === index
                            width: 96 * dlg.u; height: 70 * dlg.u; radius: 8 * dlg.u
                            color: sel ? Theme.red : "#121420"; border.color: "#2c3044"; border.width: sel ? 0 : 1.5 * dlg.u
                            Text { anchors.centerIn: parent; text: dlg.ksets[dlg.kset][r].charAt(index); color: "white"; font.pixelSize: 34 * dlg.u; font.bold: true }
                            MouseArea { anchors.fill: parent; onClicked: { dlg.kr = r; dlg.kc = index; dlg.pressKey(r, index) } }
                        }
                    }
                }
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 8 * dlg.u
                Repeater {
                    model: dlg.actions
                    Rectangle {
                        required property string modelData
                        required property int index
                        readonly property bool sel: dlg.kr === 4 && dlg.kc === index
                        width: 178 * dlg.u; height: 70 * dlg.u; radius: 8 * dlg.u
                        color: sel ? Theme.red : (modelData === "OK" ? "#13301a" : "#121420")
                        border.color: modelData === "OK" ? Theme.green : "#2c3044"; border.width: sel ? 0 : 1.5 * dlg.u
                        Text { anchors.centerIn: parent; font.pixelSize: 22 * dlg.u; font.bold: true; color: "white"
                               text: modelData === "SHOW" && dlg.reveal ? "HIDE" : modelData }
                        MouseArea { anchors.fill: parent; onClicked: { dlg.kr = 4; dlg.kc = index; dlg.pressKey(4, index) } }
                    }
                }
            }
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 24 * dlg.u
            Rectangle {
                objectName: "inputCancel"
                width: 300 * dlg.u; height: 58 * dlg.u; radius: height / 2; color: "#26ffffff"
                Text { anchors.centerIn: parent; text: "Cancel  (Esc / B)"; color: "white"; font.pixelSize: 24 * dlg.u; font.bold: true }
                MouseArea { anchors.fill: parent; onClicked: dlg.cancel() }
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Keyboard: just type, Enter = OK, Esc = cancel.   Controller: D-pad + A,  L1 = delete,  R1 = abc/ABC/123,  B = cancel"
            color: Theme.dim; font.pixelSize: 20 * dlg.u
        }
    }
}
