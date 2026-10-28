pragma Singleton
import QtQuick

QtObject {
    readonly property color bg: "#0b0907"
    readonly property color panel: "#17110d"
    readonly property color wood: "#4a2c18"
    readonly property color woodDark: "#2b190d"
    readonly property color text: "#f6ecd9"
    readonly property color dim: "#b3a38a"
    readonly property color orange: "#f39a2b"
    readonly property color redOrange: "#e5602a"
    readonly property color red: "#c8352c"
    readonly property color maroon: "#8e2b2b"
    readonly property color yellow: "#f7c244"
    readonly property color overlay: "#ee0b0907"

    function platformColor(p) {
        var m = {
            "steam": "#2a6f97", "atari2600": "#c8352c", "atari7800": "#b8581f", "nes": "#a02c33",
            "snes": "#6b5b95", "genesis": "#1f3a5f", "mastersystem": "#2f5f8a", "gb": "#4f6d2f",
            "gba": "#4b3f8f", "n64": "#2e7d5b", "ps1": "#555a66", "pce": "#a0522d", "nds": "#6d6d6d"
        }
        return m[p] !== undefined ? m[p] : "#5a4a3a"
    }
}
