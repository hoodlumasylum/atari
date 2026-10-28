import QtQuick

// Two slow, soft neon waves drifting sideways behind the library. Two pictures slid with plain GPU transforms: no shaders,
// no per-frame drawing, so it costs next to nothing. It stands still while a game runs or when "Reduce animations" is ON.
Item {
    id: wb
    property bool active: true
    clip: true
    opacity: 0.55

    Repeater {
        model: [ { src: "wave1.png", period: 90000, bobMs: 7000, top: 0.52, dir: 1 },
                 { src: "wave2.png", period: 140000, bobMs: 9500, top: 0.40, dir: -1 } ]
        Item {
            id: lay
            required property var modelData
            anchors.fill: parent
            property real shift: 0
            NumberAnimation on shift {
                from: 0; to: 1; loops: Animation.Infinite; duration: lay.modelData.period
                running: wb.active && Theme.anim
            }
            property real bob: 0
            SequentialAnimation on bob {
                loops: Animation.Infinite
                running: wb.active && Theme.anim
                NumberAnimation { to: 1; duration: lay.modelData.bobMs; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0; duration: lay.modelData.bobMs; easing.type: Easing.InOutSine }
            }
            Repeater {
                model: 2
                Image {
                    required property int index
                    source: Qt.resolvedUrl("../assets/" + lay.modelData.src)
                    width: wb.width
                    height: wb.height * 0.5
                    fillMode: Image.Stretch
                    smooth: true
                    asynchronous: true
                    x: lay.modelData.dir === 1 ? (index - lay.shift) * wb.width : (index + lay.shift - 1) * wb.width
                    y: wb.height * lay.modelData.top + lay.bob * 14
                }
            }
        }
    }
}
