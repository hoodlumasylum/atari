import QtQuick

// The four classic orange-to-maroon stripes (original artwork, drawn from plain rectangles).
Column {
    id: bar
    property real stripe: 8
    readonly property var cols: [Theme.yellow, Theme.orange, Theme.redOrange, Theme.red]
    Repeater {
        model: bar.cols
        Rectangle {
            required property color modelData
            width: bar.width
            height: bar.stripe
            color: modelData
        }
    }
}
