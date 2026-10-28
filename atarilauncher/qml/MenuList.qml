import QtQuick

// A simple vertical list of rows (title, optional value on the right, optional small detail line).
// Rows with kind "info" are plain text (skipped by the cursor).
Item {
    id: ml
    property real u: 1
    property alias model: lv.model
    property alias currentIndex: lv.currentIndex
    property alias count: lv.count
    signal clicked(int index)
    function move(delta) {
        var n = lv.count
        if (n === 0) return
        var i = lv.currentIndex
        var step = delta < 0 ? -1 : 1
        var j = i
        for (var tries = 0; tries < n; tries++) {
            j += step
            if (j < 0 || j >= n) { j = i; break }
            var row = lv.model[j]
            if (row && row.kind !== "info") break
        }
        lv.currentIndex = j
    }
    function firstSelectable() {
        for (var i = 0; i < lv.count; i++) {
            if (lv.model[i] && lv.model[i].kind !== "info") { lv.currentIndex = i; return }
        }
    }
    ListView {
        id: lv
        anchors.fill: parent
        clip: true
        spacing: 8 * ml.u
        highlightMoveDuration: 80
        keyNavigationEnabled: false
        delegate: Rectangle {
            id: row
            required property var modelData
            required property int index
            readonly property bool isInfo: modelData.kind === "info"
            readonly property bool sel: ListView.isCurrentItem && !isInfo
            readonly property bool two: !!modelData.detail
            width: lv.width
            height: isInfo ? Math.max(34 * ml.u, infoText.implicitHeight + 12 * ml.u)
                           : (two ? 56 * ml.u + detailText.implicitHeight : 62 * ml.u)
            radius: 10 * ml.u
            color: sel ? "#2a0b10" : (isInfo ? "transparent" : "#121420")
            border.width: sel ? 3 * ml.u : (isInfo ? 0 : 1.5 * ml.u)
            border.color: sel ? Theme.redBright : "#262a3c"
            Text {
                id: infoText
                visible: row.isInfo
                anchors.left: parent.left
                anchors.leftMargin: 14 * ml.u
                anchors.right: parent.right
                anchors.rightMargin: 14 * ml.u
                anchors.verticalCenter: parent.verticalCenter
                wrapMode: Text.Wrap
                text: modelData.title
                color: Theme.dim
                font.pixelSize: 18 * ml.u
            }
            Text {
                id: titleText
                visible: !row.isInfo
                anchors.left: parent.left
                anchors.leftMargin: 22 * ml.u
                anchors.right: valueText.left
                anchors.rightMargin: 12 * ml.u
                anchors.top: parent.top
                anchors.topMargin: (row.two ? 9 : 0) * ml.u
                height: row.two ? 36 * ml.u : parent.height
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                text: modelData.title
                color: row.sel ? "white" : "#e6e8f2"
                font.pixelSize: 24 * ml.u
                font.bold: true
            }
            Text {
                id: valueText
                visible: !row.isInfo && !!modelData.value
                anchors.right: parent.right
                anchors.rightMargin: 22 * ml.u
                anchors.top: parent.top
                anchors.topMargin: (row.two ? 9 : 0) * ml.u
                height: row.two ? 36 * ml.u : parent.height
                verticalAlignment: Text.AlignVCenter
                text: modelData.value ? modelData.value : ""
                color: modelData.value === "Not installed" ? Theme.yellow : (modelData.value === "Ready" ? Theme.green : Theme.redBright)
                font.pixelSize: 20 * ml.u
                font.bold: true
            }
            Text {
                id: detailText
                visible: !row.isInfo && row.two
                anchors.left: parent.left
                anchors.leftMargin: 22 * ml.u
                anchors.right: parent.right
                anchors.rightMargin: 22 * ml.u
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 9 * ml.u
                text: modelData.detail ? modelData.detail : ""
                wrapMode: Text.Wrap
                maximumLineCount: 3
                elide: Text.ElideRight
                color: Theme.dim
                font.pixelSize: 16 * ml.u
            }
            MouseArea {
                anchors.fill: parent
                enabled: !row.isInfo
                onClicked: { lv.currentIndex = row.index; ml.clicked(row.index) }
            }
        }
    }
}
