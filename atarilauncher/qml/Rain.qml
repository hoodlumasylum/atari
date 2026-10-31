import QtQuick

// Soft rain for the "Hoodlum Asylum" theme: 70 thin streaks falling with plain GPU transforms (no shaders, no per-frame drawing).
// Off with Settings > Theme > Rain, with "Reduce animations", and while a game runs.
Item {
    id: rain
    property bool active: false
    visible: active
    clip: true
    Repeater {
        model: rain.active ? 70 : 0
        Rectangle {
            objectName: "rainDrop"
            required property int index
            readonly property real seed: (index * 7919) % 1000 / 1000
            x: rain.width * ((index * 0.6180339) % 1)
            width: 1.5
            height: 18 + 26 * seed
            radius: 1
            color: index % 5 === 0 ? Theme.yellow : Theme.blue
            opacity: 0.10 + 0.18 * seed
            rotation: 12
            NumberAnimation on y {
                from: -60 - rain.height * ((index * 0.37) % 1); to: rain.height + 60
                duration: 1100 + 1300 * (1 - (index * 0.53) % 1)
                loops: Animation.Infinite
                running: rain.active
            }
        }
    }
}
