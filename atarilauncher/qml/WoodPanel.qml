import QtQuick

// Dark wood-grain panel made of gradient + thin grain lines.
Rectangle {
    id: panel
    gradient: Gradient {
        GradientStop { position: 0.0; color: Theme.wood }
        GradientStop { position: 1.0; color: Theme.woodDark }
    }
    clip: true
    Repeater {
        model: Math.max(8, Math.floor(panel.height / 5))
        Rectangle {
            required property int index
            x: -((index * 53) % 120)
            y: index * 5 + ((index * 7) % 3)
            width: panel.width + 140
            height: 1 + (index % 3 === 0 ? 1 : 0)
            color: index % 4 === 0 ? "#38000000" : (index % 3 === 0 ? "#22ffb066" : "#26000000")
        }
    }
}
