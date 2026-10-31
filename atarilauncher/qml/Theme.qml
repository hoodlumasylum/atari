pragma Singleton
import QtQuick

QtObject {
    property var pal: ({})              // the chosen theme (atarilauncher/themes/<id>.toml), set from Main.qml; empty = the standard look
    property color gradTop: pal.gradTop !== undefined ? pal.gradTop : bg
    property color gradBottom: pal.gradBottom !== undefined ? pal.gradBottom : bg
    property real waveOpacity: pal.waveOpacity !== undefined ? pal.waveOpacity : 0.55
    property bool rain: pal.rain === true
    property bool anim: true            // false = "Reduce animations": nothing moves on its own (set from Main.qml)
    property color bg: pal.bg !== undefined ? pal.bg : "#08090e"
    property color panel: pal.panel !== undefined ? pal.panel : "#0f111a"
    property color card: pal.card !== undefined ? pal.card : "#151826"
    property color line: pal.line !== undefined ? pal.line : "#272b3d"
    property color text: pal.text !== undefined ? pal.text : "#f3f4f8"
    property color dim: pal.dim !== undefined ? pal.dim : "#9aa1b6"
    property color faint: pal.faint !== undefined ? pal.faint : "#5c6279"
    property color red: pal.red !== undefined ? pal.red : "#e0202a"
    property color redBright: pal.redBright !== undefined ? pal.redBright : "#ff3a43"
    property color redDark: pal.redDark !== undefined ? pal.redDark : "#5a0b11"
    property color yellow: pal.yellow !== undefined ? pal.yellow : "#f2c230"
    property color green: pal.green !== undefined ? pal.green : "#3fae49"
    property color blue: pal.blue !== undefined ? pal.blue : "#2f7de1"
    property color overlay: pal.overlay !== undefined ? pal.overlay : "#ee06070b"

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
        "back": "<path d='M15 5l-7 7 7 7' />",
        "music": "<path d='M9 18V5.5l11-2.5v12.5' /><circle cx='6.5' cy='18' r='2.6' /><circle cx='17.5' cy='15.5' r='2.6' />",
        "chat": "<path d='M4 5.5h16a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H10l-4.5 3.5V17.5H4A1.5 1.5 0 0 1 2.5 16V7A1.5 1.5 0 0 1 4 5.5z' /><circle cx='8' cy='11.5' r='1' fill='@C' /><circle cx='12' cy='11.5' r='1' fill='@C' /><circle cx='16' cy='11.5' r='1' fill='@C' />",
        "globe": "<circle cx='12' cy='12' r='9' /><path d='M3 12h18M12 3c2.6 2.5 3.8 5.5 3.8 9s-1.2 6.5-3.8 9c-2.6-2.5-3.8-5.5-3.8-9S9.4 5.5 12 3z' />",
        "live": "<circle cx='12' cy='12' r='2.6' fill='@C' /><path d='M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M4.9 4.9a10 10 0 0 0 0 14.2M19.1 4.9a10 10 0 0 1 0 14.2' />",
        "mic": "<rect x='9' y='2.5' width='6' height='11' rx='3' /><path d='M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7' />",
        "app": "<rect x='3' y='4' width='18' height='16' rx='2.5' /><path d='M3 8.5h18' /><circle cx='6' cy='6.3' r='.7' fill='@C' /><circle cx='8.4' cy='6.3' r='.7' fill='@C' /><path d='M8 13h8M8 16.5h5' />",
        "list": "<path d='M8 6h12M8 12h12M8 18h12' /><circle cx='4' cy='6' r='1' fill='@C' /><circle cx='4' cy='12' r='1' fill='@C' /><circle cx='4' cy='18' r='1' fill='@C' />",
        "filter": "<path d='M3.5 5h17l-6.5 7.5v6l-4 2v-8z' />",
        "fire": "<path d='M12 21c-4 0-6.5-2.6-6.5-6.2 0-3.6 2.6-5.6 3.6-8.8 1.8 1.4 2.4 3.2 2.4 4.6 1-1 1.6-2.4 1.6-4.1 2.9 2.1 5.4 5.1 5.4 8.3 0 3.6-2.5 6.2-6.5 6.2z' />",
        "c_nes": "<rect x='2.5' y='7' width='19' height='10.5' rx='1.2' /><path d='M2.5 12.5h19' /><rect x='9.5' y='8.8' width='9' height='2' rx='.3' /><path d='M5 15h2.5M9.5 15h2.5' />",
        "c_snes": "<path d='M7 7h10a5 5 0 0 1 0 10H7A5 5 0 0 1 7 7z' /><path d='M6.2 10.5v3M4.7 12h3' /><circle cx='16.2' cy='10.4' r='.95' fill='@C' /><circle cx='18.4' cy='12.2' r='.95' fill='@C' /><circle cx='14.2' cy='12.2' r='.95' fill='@C' /><circle cx='16.2' cy='14' r='.95' fill='@C' />",
        "c_n64": "<path d='M3.5 9.5C3.5 8 5 7 7 7h10c2 0 3.5 1 3.5 2.5 0 1.8-1.2 3.3-3 3.6L15 14l-1.3 6h-3.4L9 14l-2.5-.9c-1.8-.3-3-1.8-3-3.6z' /><circle cx='12' cy='11.5' r='1.3' fill='@C' /><path d='M6 10h2.5M7.25 8.8v2.5' />",
        "c_gb": "<rect x='6' y='2.5' width='12' height='19' rx='1.6' /><rect x='8' y='4.6' width='8' height='6.6' rx='.6' /><path d='M8.4 15.6h3M9.9 14.1v3' /><circle cx='14.3' cy='16.2' r='.95' fill='@C' /><circle cx='16' cy='14.7' r='.95' fill='@C' />",
        "c_gba": "<path d='M2.5 9a3 3 0 0 1 3-3h13a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3h-13a3 3 0 0 1-3-3z' /><rect x='7.5' y='8' width='9' height='8' rx='.6' /><path d='M3.9 12h2.4M5.1 10.8v2.4' /><circle cx='18.8' cy='10.9' r='.8' fill='@C' /><circle cx='19.6' cy='13.1' r='.8' fill='@C' />",
        "c_ds": "<rect x='5' y='2.5' width='14' height='8.6' rx='1.2' /><rect x='5' y='12.4' width='14' height='9.1' rx='1.2' /><rect x='7.6' y='4.3' width='8.8' height='5' rx='.4' /><rect x='8.6' y='14.2' width='6.8' height='5.2' rx='.4' />",
        "c_gc": "<rect x='4' y='5.5' width='16' height='14.5' rx='2' /><path d='M7.5 5.5V3.5h9v2' /><circle cx='12' cy='12.8' r='3.6' /><circle cx='12' cy='12.8' r='1' fill='@C' />",
        "c_wii": "<rect x='5' y='2.5' width='6.5' height='19' rx='1.4' /><path d='M6.8 6h3' /><rect x='14.5' y='6' width='4.5' height='14.5' rx='2.2' /><circle cx='16.75' cy='9.2' r='.85' fill='@C' /><path d='M16.75 12.5v2' />",
        "c_switch": "<rect x='2' y='5.5' width='4.6' height='13' rx='2.3' /><rect x='17.4' y='5.5' width='4.6' height='13' rx='2.3' /><rect x='6.6' y='5.5' width='10.8' height='13' rx='.6' /><circle cx='4.3' cy='9.2' r='.85' fill='@C' /><circle cx='19.7' cy='14.3' r='.85' fill='@C' />",
        "c_ps1": "<rect x='2.5' y='8' width='19' height='9.5' rx='1.5' /><circle cx='12' cy='12.75' r='3.2' /><circle cx='12' cy='12.75' r='.8' fill='@C' /><path d='M4.5 15.5h2' />",
        "c_ps2": "<path d='M3 8.5 17.5 6 21 7.5v9L6.5 19 3 17.5z' /><path d='M6.5 19v-9L21 7.5M3 8.5l3.5 1.5' /><path d='M9 13.5l9-1.6' />",
        "c_psp": "<rect x='1.8' y='7' width='20.4' height='10' rx='5' /><rect x='7' y='8.7' width='10' height='6.6' rx='.6' /><path d='M3.6 12h2.2M4.7 10.9v2.2' /><circle cx='19.5' cy='11' r='.75' fill='@C' /><circle cx='19.5' cy='13.2' r='.75' fill='@C' />",
        "c_dc": "<rect x='3.5' y='6' width='17' height='13' rx='2.2' /><path d='M14.8 10.2a3.2 3.2 0 1 0-.8 4.4' /><path d='M6.5 16.5h3' />",
        "c_xbox": "<rect x='2.5' y='6.5' width='19' height='11.5' rx='2.2' /><circle cx='12' cy='12.25' r='3.3' /><circle cx='12' cy='12.25' r='1.1' fill='@C' /><path d='M5 15.5h2.2' />",
        "c_arcade": "<path d='M7 2.5h10l-1.2 4.5V21.5H8.2V7z' /><rect x='9.2' y='8.3' width='5.6' height='4.6' rx='.5' /><path d='M9.6 16h2.2M10.7 14.9v2.2' /><circle cx='14' cy='16' r='.8' fill='@C' />",
        "c_atari": "<path d='M3 11.5 5 8h14l2 3.5V18H3z' /><path d='M3 11.5h18M6 14.5h12' /><path d='M8 8V5.5M8 5.5h0' /><circle cx='8' cy='4.6' r='1.1' />",
        "c_cloud": "<path d='M7 18.5a4.5 4.5 0 0 1-.6-9 6 6 0 0 1 11.4 1.6 3.8 3.8 0 0 1-.3 7.4z' /><path fill='@C' d='M10.6 11.8v4.6l3.9-2.3z' />",
        "c_pc": "<rect x='2.5' y='4' width='14' height='10.5' rx='1.5' /><path d='M6.5 18.5h6M9.5 14.5v4' /><rect x='18.5' y='4' width='3' height='14.5' rx='.8' /><path d='M19.2 7h1.6' />"
    })

    // An original picture for an app tile (no company logos): what kind of thing it is.
    function glyphFor(gid) {
        var kind = gid.split(":")[0], id = gid.substring(kind.length + 1)
        if (kind === "web") {
            if (/^(xcloud|geforcenow|luna|boosteroid|antstream|blacknut)$/.test(id)) return "c_cloud"
            if (/live$/.test(id)) return "live"
            if (id === "spotify") return "music"
            if (id === "bandlab") return "mic"
            if (id === "instagram" || id === "facebook" || id === "tiktok") return "chat"
            if (id === "browser" || id === "support" || id === "unrealpage" || id === "xemuhdd") return "globe"
            return "monitor"
        }
        if (kind === "app") {
            if (id === "eaapp" || id === "rockstar") return "c_pc"
            if (/steam|heroic|lutris|bottles|umu|wine|proton|roblox|sober/.test(id)) return "pad"
            if (/obs|record/.test(id)) return "live"
            if (/chrome|firefox|browser/.test(id)) return "globe"
            if (/kodi|vlc|mpv|plex|jellyfin/.test(id)) return "monitor"
            if (/audac|lmms|ardour|music|spot/.test(id)) return "music"
            if (/discord|chat/.test(id)) return "chat"
            return "app"
        }
        return ""
    }
    // the original vector drawing for a system (not a logo: a plain line picture of that kind of machine)
    function consoleFor(key, glyph) {
        var m = { nes: "c_nes", famicom: "c_nes", snes: "c_snes", n64: "c_n64", gb: "c_gb", gbc: "c_gb", gba: "c_gba",
                  nds: "c_ds", n3ds: "c_ds", gamecube: "c_gc", wii: "c_wii", wiiu: "c_wii", switch: "c_switch",
                  ps1: "c_ps1", ps2: "c_ps2", ps3: "c_ps2", psp: "c_psp", dreamcast: "c_dc", saturn: "c_ps1",
                  xbox: "c_xbox", arcade: "c_arcade", atari2600: "c_atari", atari5200: "c_atari", atari7800: "c_atari",
                  atarijaguar: "c_atari", studio: "music", neogeo: "c_arcade", cloud: "c_cloud", steam: "c_pc",
                  windows: "c_pc", dos: "c_pc", apps: "c_pc", heroic: "c_pc", lutris: "c_pc" }
        return m[key] !== undefined ? m[key] : (glyph ? glyph : "pad")
    }
    // the highlight colour of the home screen (gold), and its glow
    property color accent: pal.accent !== undefined ? pal.accent : "#e8c25a"
    property color accentGlow: pal.accentGlow !== undefined ? pal.accentGlow : "#66e8c25a"
    readonly property color gold: "#e8c25a"
    readonly property color emerald: "#0f6b4f"
    readonly property color emeraldDark: "#062a1f"

    function svg(name, color, stroke, px) {
        var body = icons[name] !== undefined ? icons[name] : icons["pad"]
        var c = String(color)
        body = body.replace(/@C/g, c)
        return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'" + (px ? " width='" + px + "' height='" + px + "'" : "")
             + " fill='none' stroke='" + c
             + "' stroke-width='" + stroke + "' stroke-linecap='round' stroke-linejoin='round'>" + body + "</svg>"
    }
    function svgUrl(name, color, stroke, px) {
        return "data:image/svg+xml;utf8," + encodeURIComponent(svg(name, color, stroke, px))
    }
}
