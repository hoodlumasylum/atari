import QtQuick
import QtQuick.Window

Window {
    id: win
    visible: true
    width: 1280
    height: 720
    title: "Atari"
    color: Theme.bg
    visibility: backend.fullscreen ? Window.FullScreen : Window.Windowed

    readonly property real u: Math.max(0.5, Math.min(width / 1920, height / 1080))

    // library | search | menu | setup | browse
    property string mode: backend.firstRun ? "setup" : "library"
    property string area: "grid"      // which part of the library screen has the highlight: tabs | grid
    property int tabIndex: 0
    property var tabs: []
    property int keepIdx: -1
    property string searchText: ""
    property bool typedSearch: false
    property int oskRow: 0
    property int oskCol: 0
    property var browseTarget: ({})
    property var browseData: ({ path: "", parent: "", dirs: [] })
    property bool setupWasFirstRun: false

    readonly property string oskChars: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-'"
    readonly property var oskActions: ["SPACE", "DELETE", "CLEAR", "DONE"]

    // ---------------------------------------------------------------- helpers
    function buildTabs() {
        var out = []
        var f = backend.filters
        for (var i = 0; i < f.length; i++) out.push(f[i])
        out.push({ key: "__search", label: backend.query ? ("Search: " + backend.query) : "Search", count: -1 })
        tabs = out
        syncTab()
    }
    function syncTab() {
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].key === backend.currentFilter) { tabIndex = i; return }
        }
    }
    function selectTab(i, skipSearch) {
        var last = skipSearch ? tabs.length - 2 : tabs.length - 1
        i = Math.max(0, Math.min(last, i))
        tabIndex = i
        var t = tabs[i]
        if (t.key !== "__search") {
            backend.setQuery("")
            backend.setFilter(t.key)
            grid.currentIndex = 0
            grid.positionViewAtBeginning()
        }
    }
    function openMenu() { menuList.currentIndex = 0; mode = "menu" }
    function openSearch() {
        searchText = backend.query
        typedSearch = false
        oskRow = 0; oskCol = 0
        mode = "search"
    }
    function closeSearch() {
        mode = "library"
        area = grid.count > 0 ? "grid" : "tabs"
        buildTabs()
    }
    function setSearch(t) {
        searchText = t
        backend.setQuery(t)
        grid.currentIndex = 0
    }
    function refreshSetup(keep) {
        var idx = setupList.currentIndex
        setupList.model = backend.setupRows()
        setupList.currentIndex = keep ? Math.min(idx, setupList.count - 1) : 0
    }
    function openSetup() {
        refreshSetup(false)
        setupList.currentIndex = 0
        mode = "setup"
    }
    function openBrowser(target, startPath) {
        browseTarget = target
        loadDir(startPath)
        mode = "browse"
    }
    function loadDir(path) {
        browseData = backend.listDir(path)
        var rows = []
        if (browseData.path !== "")
            rows.push({ kind: "use", title: "Use this folder", detail: browseData.path })
        if (browseData.path !== "")
            rows.push({ kind: "up", title: ".. (go up)", detail: "" })
        for (var i = 0; i < browseData.dirs.length; i++)
            rows.push({ kind: "dir", title: browseData.dirs[i].name, detail: "", path: browseData.dirs[i].path })
        browseList.model = rows
        browseList.currentIndex = 0
    }

    // ------------------------------------------------------------ key handling
    function isEnter(k) { return k === Qt.Key_Return || k === Qt.Key_Enter }

    function libraryKey(e) {
        var k = e.key
        if (k === Qt.Key_F10 || k === Qt.Key_Menu || k === Qt.Key_M) { openMenu(); return }
        if (k === Qt.Key_Slash || k === Qt.Key_Find || (k === Qt.Key_F && (e.modifiers & Qt.ControlModifier))) { openSearch(); return }
        if (k === Qt.Key_Escape) { if (backend.query !== "") { backend.setQuery(""); buildTabs() } else openMenu(); return }
        if (k === Qt.Key_PageUp || k === Qt.Key_Q) { selectTab(tabIndex - 1, true); return }
        if (k === Qt.Key_PageDown || k === Qt.Key_E || k === Qt.Key_Tab) { selectTab(tabIndex + 1, true); return }
        var n = grid.count, cols = grid.cols, i = grid.currentIndex
        if (area === "tabs") {
            if (k === Qt.Key_Left) selectTab(tabIndex - 1, false)
            else if (k === Qt.Key_Right) selectTab(tabIndex + 1, false)
            else if (k === Qt.Key_Down && n > 0) area = "grid"
            else if (isEnter(k) || k === Qt.Key_Space) {
                if (tabs[tabIndex].key === "__search") openSearch()
                else if (n > 0) area = "grid"
            }
            return
        }
        // grid
        if (k === Qt.Key_Left) { if (i > 0) grid.currentIndex = i - 1 }
        else if (k === Qt.Key_Right) { if (i < n - 1) grid.currentIndex = i + 1 }
        else if (k === Qt.Key_Up) { if (i - cols >= 0) grid.currentIndex = i - cols; else area = "tabs" }
        else if (k === Qt.Key_Down) {
            if (i + cols < n) grid.currentIndex = i + cols
            else if (Math.floor(i / cols) < Math.floor((n - 1) / cols)) grid.currentIndex = n - 1
        }
        else if (k === Qt.Key_Home) grid.currentIndex = 0
        else if (k === Qt.Key_End) grid.currentIndex = n - 1
        else if (k === Qt.Key_F) { if (n > 0) { keepIdx = i; backend.toggleFavorite(i); keepIdx = -1; buildTabs() } }
        else if (isEnter(k) || k === Qt.Key_Space) { if (n > 0) backend.launch(i) }
    }

    function searchKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape || k === Qt.Key_F10) { closeSearch(); return }
        if (k === Qt.Key_Backspace) { typedSearch = true; setSearch(searchText.slice(0, -1)); return }
        var printable = e.text.length === 1 && e.text >= " " && !(e.modifiers & Qt.ControlModifier)
        if (printable) { typedSearch = true; setSearch(searchText + e.text); return }
        if (k === Qt.Key_Left) { oskCol = Math.max(0, oskCol - 1) }
        else if (k === Qt.Key_Right) { oskCol = Math.min(oskRow < 4 ? 9 : 3, oskCol + 1) }
        else if (k === Qt.Key_Up) {
            if (oskRow === 4) { oskRow = 3; oskCol = Math.min(9, Math.floor((oskCol + 0.5) * 10 / 4)) }
            else oskRow = Math.max(0, oskRow - 1)
        }
        else if (k === Qt.Key_Down) {
            if (oskRow === 3) { oskRow = 4; oskCol = Math.min(3, Math.floor(oskCol * 4 / 10)) }
            else if (oskRow < 3) oskRow++
        }
        else if (isEnter(k)) {
            if (typedSearch && searchText !== "") { closeSearch(); return }
            if (oskRow < 4) setSearch(searchText + oskChars.charAt(oskRow * 10 + oskCol))
            else if (oskCol === 0) setSearch(searchText + " ")
            else if (oskCol === 1) setSearch(searchText.slice(0, -1))
            else if (oskCol === 2) setSearch("")
            else closeSearch()
        }
        else if (k === Qt.Key_F) { setSearch(searchText.slice(0, -1)) }   // gamepad Y = backspace
        else if (k === Qt.Key_PageUp || k === Qt.Key_PageDown) { setSearch(searchText + " ") }
    }

    function menuKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape || k === Qt.Key_F10 || k === Qt.Key_Menu) { mode = "library"; return }
        if (k === Qt.Key_Up) menuList.move(-1)
        else if (k === Qt.Key_Down) menuList.move(1)
        else if (isEnter(k)) {
            var i = menuList.currentIndex
            if (i === 0) mode = "library"
            else if (i === 1) { backend.rescan(); buildTabs(); mode = "library" }
            else if (i === 2) openSetup()
            else if (i === 3) { backend.toggleFullscreen(); mode = "library" }
            else backend.quit()
        }
    }

    function setupKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape) { backend.rescan(); buildTabs(); mode = "library"; return }
        if (k === Qt.Key_Up) setupList.move(-1)
        else if (k === Qt.Key_Down) setupList.move(1)
        else if (k === Qt.Key_Delete || k === Qt.Key_Backspace || k === Qt.Key_F) {
            var row = setupList.model[setupList.currentIndex]
            if (row && row.kind === "system") { backend.clearSystemFolder(row.id); refreshSetup(true) }
        }
        else if (isEnter(k) || k === Qt.Key_Space) {
            var r = setupList.model[setupList.currentIndex]
            if (!r) return
            if (r.kind === "steam") { backend.toggleSteam(); refreshSetup(true) }
            else if (r.kind === "steamlib") openBrowser({ kind: "steamlib" }, backend.homeDir())
            else if (r.kind === "system") {
                var cur = r.detail && r.detail.indexOf("Not set") !== 0 ? r.detail.split(", ")[0] : backend.homeDir()
                openBrowser({ kind: "system", id: r.id }, cur)
            }
            else if (r.kind === "done") { backend.finishSetup(); buildTabs(); mode = "library"; area = "grid" }
        }
    }

    function browseKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape) { mode = "setup"; return }
        if (k === Qt.Key_Up) browseList.move(-1)
        else if (k === Qt.Key_Down) browseList.move(1)
        else if (k === Qt.Key_Left || k === Qt.Key_Backspace) {
            if (browseData.path !== "") loadDir(browseData.parent)
        }
        else if (isEnter(k) || k === Qt.Key_Right) {
            var r = browseList.model[browseList.currentIndex]
            if (!r) return
            if (r.kind === "dir") loadDir(r.path)
            else if (r.kind === "up") loadDir(browseData.parent)
            else if (r.kind === "use" && isEnter(k)) {
                if (browseTarget.kind === "system") backend.setSystemFolder(browseTarget.id, browseData.path)
                else backend.addSteamLibrary(browseData.path)
                refreshSetup(true)
                mode = "setup"
            }
        }
    }

    Item {
        id: root
        anchors.fill: parent
        focus: true
        Keys.onPressed: function (e) {
            e.accepted = true
            if (e.key === Qt.Key_F11) { backend.toggleFullscreen(); return }
            if (e.key === Qt.Key_Q && (e.modifiers & Qt.ControlModifier)) { backend.quit(); return }
            if (backend.running) return
            if (win.mode === "library") libraryKey(e)
            else if (win.mode === "search") searchKey(e)
            else if (win.mode === "menu") menuKey(e)
            else if (win.mode === "setup") setupKey(e)
            else if (win.mode === "browse") browseKey(e)
        }

        // ---------------------------------------------------------- header
        WoodPanel {
            id: header
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 112 * win.u
            Text {
                id: wordmark
                anchors.left: parent.left
                anchors.leftMargin: 48 * win.u
                anchors.verticalCenter: parent.verticalCenter
                text: "ATARI"
                color: Theme.orange
                font.pixelSize: 78 * win.u
                font.bold: true
                font.letterSpacing: 14 * win.u
                style: Text.Raised
                styleColor: "#000000"
            }
            Text {
                anchors.left: wordmark.right
                anchors.leftMargin: 30 * win.u
                anchors.baseline: wordmark.baseline
                text: backend.demo ? "GAME LAUNCHER  \u00b7  DEMO" : "GAME LAUNCHER"
                color: Theme.dim
                font.pixelSize: 28 * win.u
                font.letterSpacing: 5 * win.u
            }
            Text {
                anchors.right: parent.right
                anchors.rightMargin: 48 * win.u
                anchors.verticalCenter: parent.verticalCenter
                text: backend.totalGames + (backend.totalGames === 1 ? " game" : " games")
                color: Theme.text
                font.pixelSize: 32 * win.u
            }
        }
        StripeBar {
            id: stripes
            anchors.top: header.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            stripe: 7 * win.u
        }

        // ------------------------------------------------------------ tabs
        ListView {
            id: tabBar
            anchors.top: stripes.bottom
            anchors.topMargin: 14 * win.u
            anchors.left: parent.left
            anchors.leftMargin: 40 * win.u
            anchors.right: parent.right
            anchors.rightMargin: 40 * win.u
            height: 66 * win.u
            orientation: ListView.Horizontal
            spacing: 14 * win.u
            clip: true
            model: win.tabs
            currentIndex: win.tabIndex
            highlightFollowsCurrentItem: true
            highlightMoveDuration: 80
            preferredHighlightBegin: width * 0.25
            preferredHighlightEnd: width * 0.75
            highlightRangeMode: ListView.ApplyRange
            delegate: Rectangle {
                id: pill
                required property var modelData
                required property int index
                readonly property bool cur: index === win.tabIndex
                readonly property bool focused: cur && win.area === "tabs" && win.mode === "library"
                height: tabBar.height
                width: pillText.implicitWidth + 44 * win.u
                radius: height / 2
                color: cur ? (focused ? Theme.orange : Theme.redOrange) : "#1c1510"
                border.width: cur ? 0 : 2 * win.u
                border.color: "#4a3626"
                Text {
                    id: pillText
                    anchors.centerIn: parent
                    text: modelData.label + (modelData.count >= 0 ? "  " + modelData.count : "")
                    color: pill.cur ? "#140d08" : Theme.text
                    font.pixelSize: 30 * win.u
                    font.bold: pill.cur
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        win.area = "tabs"
                        if (modelData.key === "__search") win.openSearch()
                        else win.selectTab(index, false)
                    }
                }
            }
        }

        // ------------------------------------------------------------ grid
        Item {
            id: gridArea
            anchors.top: tabBar.bottom
            anchors.topMargin: 10 * win.u
            anchors.bottom: detail.top
            anchors.left: parent.left
            anchors.right: parent.right

            GridView {
                id: grid
                readonly property int cols: Math.max(1, Math.floor(gridArea.width / cellWidth))
                anchors.horizontalCenter: parent.horizontalCenter
                width: cols * cellWidth
                height: parent.height
                cellWidth: 244 * win.u
                cellHeight: 332 * win.u
                clip: true
                model: backend.games
                keyNavigationEnabled: false
                highlightMoveDuration: 0
                onCountChanged: if (count === 0) win.area = "tabs"
                delegate: GameTile {
                    width: grid.cellWidth
                    height: grid.cellHeight
                    u: win.u
                    current: GridView.isCurrentItem && win.area === "grid" && win.mode === "library"
                    onClicked: { win.area = "grid"; grid.currentIndex = index }
                    onActivated: { grid.currentIndex = index; backend.launch(index) }
                }
            }
            Connections {
                target: backend.games
                function onModelReset() {
                    if (win.keepIdx >= 0) grid.currentIndex = Math.max(0, Math.min(win.keepIdx, grid.count - 1))
                    else { grid.currentIndex = 0; grid.positionViewAtBeginning() }
                    if (grid.count > 0 && win.area === "tabs" && win.mode === "library" && false) win.area = "grid"
                }
            }
            Text {
                anchors.centerIn: parent
                width: parent.width * 0.7
                visible: grid.count === 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                color: Theme.dim
                font.pixelSize: 38 * win.u
                lineHeight: 1.2
                text: {
                    backend.currentFilter; backend.query; backend.totalGames
                    return backend.emptyMessage()
                }
            }
        }

        // ----------------------------------------------------- detail + hints
        WoodPanel {
            id: detail
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: hints.top
            height: 118 * win.u
            readonly property var cur: grid.currentItem
            Rectangle { anchors.top: parent.top; width: parent.width; height: 4 * win.u; color: Theme.orange }
            Column {
                anchors.left: parent.left
                anchors.leftMargin: 48 * win.u
                anchors.right: parent.right
                anchors.rightMargin: 48 * win.u
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4 * win.u
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: detail.cur ? detail.cur.title : "Atari"
                    color: Theme.text
                    font.pixelSize: 44 * win.u
                    font.bold: true
                }
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: detail.cur
                          ? (detail.cur.platformName + "   \u00b7   Played: " + detail.cur.playtime
                             + "   \u00b7   Last: " + detail.cur.lastPlayed)
                          : backend.steamStatus
                    color: Theme.dim
                    font.pixelSize: 26 * win.u
                }
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    visible: detail.cur && detail.cur.note !== ""
                    text: detail.cur ? detail.cur.note : ""
                    color: Theme.yellow
                    font.pixelSize: 24 * win.u
                    height: visible ? implicitHeight : 0
                }
            }
        }
        Rectangle {
            id: hints
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 46 * win.u
            color: "#0f0b08"
            Text {
                anchors.centerIn: parent
                text: "Arrows / D-pad  Move      Enter / A  Play      F / Y  Favorite      / or X  Search      Q E / LB RB  Switch list      F10 / Start  Menu"
                color: Theme.dim
                font.pixelSize: 21 * win.u
            }
        }

        // ------------------------------------------------------------ toast
        Rectangle {
            id: toast
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: detail.top
            anchors.bottomMargin: 18 * win.u
            width: Math.min(parent.width - 80 * win.u, toastText.implicitWidth + 60 * win.u)
            height: toastText.implicitHeight + 28 * win.u
            radius: 12 * win.u
            color: "#f0201710"
            border.color: Theme.orange
            border.width: 3 * win.u
            opacity: backend.toast !== "" ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Text {
                id: toastText
                anchors.centerIn: parent
                width: parent.width - 40 * win.u
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                text: backend.toast
                color: Theme.text
                font.pixelSize: 28 * win.u
            }
        }

        // ---------------------------------------------------- overlay: search
        Rectangle {
            anchors.fill: parent
            color: Theme.overlay
            visible: win.mode === "search"
            MouseArea { anchors.fill: parent }
            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 90 * win.u
                spacing: 26 * win.u
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "SEARCH"
                    color: Theme.orange
                    font.pixelSize: 40 * win.u
                    font.bold: true
                    font.letterSpacing: 8 * win.u
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 1000 * win.u
                    height: 92 * win.u
                    radius: 10 * win.u
                    color: "#1c1510"
                    border.color: Theme.orange
                    border.width: 3 * win.u
                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: 28 * win.u
                        verticalAlignment: Text.AlignVCenter
                        text: win.searchText === "" ? "Type or pick letters..." : win.searchText + "\u258c"
                        color: win.searchText === "" ? Theme.dim : Theme.text
                        font.pixelSize: 46 * win.u
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: grid.count + (grid.count === 1 ? " match" : " matches")
                    color: Theme.dim
                    font.pixelSize: 28 * win.u
                }
                Grid {
                    anchors.horizontalCenter: parent.horizontalCenter
                    columns: 10
                    spacing: 10 * win.u
                    Repeater {
                        model: 40
                        Rectangle {
                            required property int index
                            readonly property bool sel: win.oskRow === Math.floor(index / 10) && win.oskCol === index % 10
                            width: 88 * win.u
                            height: 78 * win.u
                            radius: 8 * win.u
                            color: sel ? Theme.orange : "#1c1510"
                            border.color: "#4a3626"
                            border.width: sel ? 0 : 2 * win.u
                            Text {
                                anchors.centerIn: parent
                                text: win.oskChars.charAt(index) === " " ? "\u2423" : win.oskChars.charAt(index)
                                color: parent.sel ? "#140d08" : Theme.text
                                font.pixelSize: 38 * win.u
                                font.bold: true
                            }
                        }
                    }
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 10 * win.u
                    Repeater {
                        model: win.oskActions
                        Rectangle {
                            required property string modelData
                            required property int index
                            readonly property bool sel: win.oskRow === 4 && win.oskCol === index
                            width: 220 * win.u
                            height: 78 * win.u
                            radius: 8 * win.u
                            color: sel ? Theme.orange : "#1c1510"
                            border.color: "#4a3626"
                            border.width: sel ? 0 : 2 * win.u
                            Text {
                                anchors.centerIn: parent
                                text: modelData
                                color: parent.sel ? "#140d08" : Theme.text
                                font.pixelSize: 30 * win.u
                                font.bold: true
                            }
                        }
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Keyboard: just type, Enter = done.   Gamepad: D-pad + A,  Y = backspace,  B = close"
                    color: Theme.dim
                    font.pixelSize: 24 * win.u
                }
            }
        }

        // ----------------------------------------------------- overlay: menu
        Rectangle {
            anchors.fill: parent
            color: Theme.overlay
            visible: win.mode === "menu"
            MouseArea { anchors.fill: parent }
            Column {
                anchors.centerIn: parent
                spacing: 24 * win.u
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "MENU"
                    color: Theme.orange
                    font.pixelSize: 54 * win.u
                    font.bold: true
                    font.letterSpacing: 10 * win.u
                }
                MenuList {
                    id: menuList
                    u: win.u
                    width: 760 * win.u
                    height: 5 * 74 * win.u
                    model: [
                        { kind: "item", title: "Resume" },
                        { kind: "item", title: "Rescan library" },
                        { kind: "item", title: "Set up folders (Steam & ROMs)" },
                        { kind: "item", title: "Toggle full screen" },
                        { kind: "item", title: "Quit Atari" }
                    ]
                }
            }
        }

        // ---------------------------------------------------- overlay: setup
        Rectangle {
            anchors.fill: parent
            color: "#0b0907"
            visible: win.mode === "setup" || win.mode === "browse"
            MouseArea { anchors.fill: parent }
            WoodPanel {
                id: setupHead
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 130 * win.u
                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 48 * win.u
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6 * win.u
                    Text {
                        text: backend.firstRun ? "WELCOME! LET'S SET UP YOUR GAMES" : "SET UP FOLDERS"
                        color: Theme.orange
                        font.pixelSize: 46 * win.u
                        font.bold: true
                        font.letterSpacing: 4 * win.u
                    }
                    Text {
                        text: win.mode === "browse"
                              ? "Pick the folder, then choose \"Use this folder\".  Left = up, Esc / B = cancel."
                              : "Up/Down to choose, Enter / A to change.  Delete / Y clears a folder.  Esc / B = back."
                        color: Theme.text
                        font.pixelSize: 26 * win.u
                    }
                }
            }
            StripeBar {
                id: setupStripes
                anchors.top: setupHead.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                stripe: 6 * win.u
            }
            MenuList {
                id: setupList
                u: win.u
                anchors.top: setupStripes.bottom
                anchors.topMargin: 20 * win.u
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 20 * win.u
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width - 100 * win.u, 1500 * win.u)
                visible: win.mode === "setup"
                model: []
            }
            Item {
                anchors.fill: setupList
                visible: win.mode === "browse"
                Text {
                    id: browsePath
                    width: parent.width
                    elide: Text.ElideMiddle
                    text: win.browseData.path === "" ? "Choose a place" : win.browseData.path
                    color: Theme.yellow
                    font.pixelSize: 30 * win.u
                    height: 50 * win.u
                }
                MenuList {
                    id: browseList
                    u: win.u
                    anchors.top: browsePath.bottom
                    anchors.bottom: parent.bottom
                    width: parent.width
                    model: []
                }
            }
        }

        // ------------------------------------------------- overlay: running
        Rectangle {
            anchors.fill: parent
            color: "#f50b0907"
            visible: backend.running
            MouseArea { anchors.fill: parent }
            Column {
                anchors.centerIn: parent
                spacing: 18 * win.u
                StripeBar { width: 420 * win.u; stripe: 12 * win.u; anchors.horizontalCenter: parent.horizontalCenter }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "NOW PLAYING"
                    color: Theme.orange
                    font.pixelSize: 40 * win.u
                    font.bold: true
                    font.letterSpacing: 8 * win.u
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: backend.runningTitle
                    color: Theme.text
                    font.pixelSize: 62 * win.u
                    font.bold: true
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Starting up... this screen returns when you quit the game."
                    color: Theme.dim
                    font.pixelSize: 28 * win.u
                }
            }
        }
    }

    Connections {
        target: backend
        function onFiltersChanged() { win.buildTabs() }
        function onCurrentFilterChanged() { win.syncTab() }
        function onQueryChanged() { win.buildTabs() }
    }
    Component.onCompleted: {
        buildTabs()
        if (backend.firstRun) refreshSetup(false)
        area = grid.count > 0 ? "grid" : "tabs"
        root.forceActiveFocus()
    }
}
