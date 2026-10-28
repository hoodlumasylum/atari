pragma Singleton
import QtQuick

QtObject {
    property bool anim: true            // false = "Reduce animations": nothing moves on its own (set from Main.qml)
    readonly property color bg: "#08090e"
    readonly property color panel: "#0f111a"
    readonly property color card: "#151826"
    readonly property color line: "#272b3d"
    readonly property color text: "#f3f4f8"
    readonly property color dim: "#9aa1b6"
    readonly property color faint: "#5c6279"
    readonly property color red: "#e0202a"
    readonly property color redBright: "#ff3a43"
    readonly property color redDark: "#5a0b11"
    readonly property color yellow: "#f2c230"
    readonly property color green: "#3fae49"
    readonly property color blue: "#2f7de1"
    readonly property color overlay: "#ee06070b"

    // ---- original line icons (24x24), built as SVG text so they can take any colour -------------
    readonly property var icons: ({
        "home": "<path d='M3 11.5 12 4l9 7.5' /><path d='M5.5 10v10h5v-6h3v6h5V10' />",
        "star": "<path d='M12 3.2l2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 17l-5.4 2.9 1.1-6.1L3.2 9.6l6.1-.8z' />",
        "starfill": "<path fill='@C' d='M12 3.2l2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 17l-5.4 2.9 1.1-6.1L3.2 9.6l6.1-.8z' />",
        "clock": "<circle cx='12' cy='12' r='9' /><path d='M12 7v5.5l3.5 2' />",
        "pad": "<path d='M7 8h10a5 5 0 0 1 5 5v2a3 3 0 0 1-5.2 2L15 15H9l-1.8 2A3 3 0 0 1 2 15v-2a5 5 0 0 1 5-5z' /><path d='M7 10.5v3M5.5 12h3' /><circle cx='16.5' cy='11' r='.9' fill='@C' /><circle cx='18.5' cy='13' r='.9' fill='@C' />",
        "gear": "<circle cx='12' cy='12' r='6.5' /><circle cx='12' cy='12' r='2.4' /><circle cx='12' cy='12' r='9.6' stroke-width='3' stroke-dasharray='2.2 5.1' />",
        "wifi": "<path d='M2.5 9.2a14 14 0 0 1 19 0M5.6 12.6a9.5 9.5 0 0 1 12.8 0M8.8 16a5 5 0 0 1 6.4 0' /><circle cx='12' cy='19.4' r='1.3' fill='@C' />",
        "search": "<circle cx='10.5' cy='10.5' r='6.5' /><path d='M15.5 15.5 21 21' />",
        "plus": "<path d='M12 4v16M4 12h16' />",
        "grid": "<rect x='4' y='4' width='6.5' height='6.5' rx='1.2' fill='@C' /><rect x='13.5' y='4' width='6.5' height='6.5' rx='1.2' fill='@C' /><rect x='4' y='13.5' width='6.5' height='6.5' rx='1.2' fill='@C' /><rect x='13.5' y='13.5' width='6.5' height='6.5' rx='1.2' fill='@C' />",
        "more": "<circle cx='5' cy='12' r='1.8' fill='@C' /><circle cx='12' cy='12' r='1.8' fill='@C' /><circle cx='19' cy='12' r='1.8' fill='@C' />",
        "heart": "<path d='M12 20.5s-8-4.9-8-10.7A4.6 4.6 0 0 1 12 7a4.6 4.6 0 0 1 8 2.8c0 5.8-8 10.7-8 10.7z' />",
        "chevron": "<path d='M6 9l6 6 6-6' />",
        "play": "<path fill='@C' d='M7 4.5v15l12.5-7.5z' />",
        "check": "<path d='M5 12.5l4.5 4.5L19 7.5' />",
        "usb": "<path d='M12 3v14M12 17a2.2 2.2 0 1 0 .01 0M12 9l-4-2.5M8 6.5v-1.5M12 12l4-2.5M16 9.5v-2h2v2z' />",
        "folder": "<path d='M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z' />",
        "cart": "<path d='M6.5 3h11v13.5L15.5 21h-7l-2-4.5z' /><rect x='9' y='6' width='6' height='5' rx='.8' />",
        "console": "<rect x='2.5' y='8.5' width='19' height='8.5' rx='2' /><path d='M6 13h8' /><circle cx='18' cy='13' r='1' fill='@C' />",
        "handheld": "<rect x='6' y='2.5' width='12' height='19' rx='2.2' /><rect x='8.5' y='5' width='7' height='7' rx='.8' /><circle cx='9.5' cy='16.5' r='1.2' fill='@C' /><circle cx='14.5' cy='15.5' r='1.2' fill='@C' />",
        "disc": "<circle cx='12' cy='12' r='9' /><circle cx='12' cy='12' r='2.6' />",
        "rings": "<circle cx='12' cy='12' r='9' /><circle cx='12' cy='12' r='5.5' /><circle cx='12' cy='12' r='1.8' fill='@C' />",
        "cube": "<path d='M12 2.5l8.5 4.8v9.4L12 21.5l-8.5-4.8V7.3z' /><path d='M12 12L3.5 7.3M12 12l8.5-4.7M12 12v9.5' />",
        "monitor": "<rect x='2.5' y='4' width='19' height='12.5' rx='2' /><path d='M8 20.5h8M12 16.5v4' /><path fill='@C' d='M10.2 7.5v5.5l4.6-2.75z' />",
        "bars": "<path d='M6.5 21 9.2 3M12 21V3M17.5 21 14.8 3' stroke-width='3' />",
        "back": "<path d='M15 5l-7 7 7 7' />"
    })

    function svg(name, color, stroke) {
        var body = icons[name] !== undefined ? icons[name] : icons["pad"]
        var c = String(color)
        body = body.replace(/@C/g, c)
        return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='" + c
             + "' stroke-width='" + stroke + "' stroke-linecap='round' stroke-linejoin='round'>" + body + "</svg>"
    }
    function svgUrl(name, color, stroke) {
        return "data:image/svg+xml;utf8," + encodeURIComponent(svg(name, color, stroke))
    }
}
