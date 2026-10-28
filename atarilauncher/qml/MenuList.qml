import QtQuick

// A simple vertical list of rows (title, optional value on the right, optional small detail line).
Item {
    id: ml
    property real u: 1
    property alias model: lv.model
    property alias currentIndex: lv.currentIndex
    property alias count: lv.count
    function move(delta) {
        var n = lv.count
        if (n === 0) return
        var i = lv.currentIndex
        for (var tries = 0; tries < n; tries++) {
            i = Math.max(0, Math.min(n - 1, i + delta))
            var row = lv.model[i]
            if (!row || row.kind !== "info") break
            if (i === 0 || i === n - 1) break
        }
        lv.currentIndex = i
    }
    ListView {
        id: lv
        anchors.fill: parent
        clip: true
        spacing: 8 * ml.u
        highlightMoveDuration: 60
        keyNavigationEnabled: false
        delegate: Rectangle {
            id: row
            required property var modelData
            required property int index
            readonly property bool isInfo: modelData.kind === "info"
            readonly property bool sel: ListView.isCurrentItem && !isInfo
            width: lv.width
            height: (modelData.detail ? 96 : 66) * ml.u
            radius: 8 * ml.u
            color: sel ? "#3b2413" : (isInfo ? "transparent" : "#18110c")
            border.width: sel ? 4 * ml.u : 0
            border.color: Theme.orange
            Text {
                id: titleText
                anchors.left: parent.left
                anchors.leftMargin: 24 * ml.u
                anchors.top: parent.top
                anchors.topMargin: (modelData.detail ? 10 : 0) * ml.u
                height: modelData.detail ? 44 * ml.u : parent.height
                verticalAlignment: Text.AlignVCenter
                text: modelData.title
                color: row.isInfo ? Theme.dim : (row.sel ? Theme.yellow : Theme.text)
                font.pixelSize: 32 * ml.u
                font.bold: !row.isInfo
            }
            Text {
                anchors.right: parent.right
                anchors.rightMargin: 24 * ml.u
                anchors.top: parent.top
                anchors.topMargin: 10 * ml.u
                height: 44 * ml.u
                verticalAlignment: Text.AlignVCenter
                visible: !!modelData.value
                text: modelData.value ? modelData.value : ""
                color: Theme.orange
                font.pixelSize: 28 * ml.u
                font.bold: true
            }
            Text {
                visible: !!modelData.detail
                anchors.left: parent.left
                anchors.leftMargin: 24 * ml.u
                anchors.right: parent.right
                anchors.rightMargin: 24 * ml.u
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 8 * ml.u
                text: modelData.detail ? modelData.detail : ""
                elide: Text.ElideMiddle
                color: Theme.dim
                font.pixelSize: 22 * ml.u
            }
        }
    }
}
