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

    // everything is drawn in "units" that scale with the window (1 unit = 1 pixel at 1920x1080)
    readonly property real u: Math.max(0.4, Math.min(width / 1920, height / 1080))

    // library | search | menu | sort | setup | browse | emulators | import
    property string mode: backend.firstRun ? "setup" : "library"
    property string area: "grid"        // which part of the library has the highlight: tabs tiles side grid detail
    property int tabFocus: 0            // 0-4 tabs, 5 Add Games, 6 search
    property int tileIndex: 0
    property int sideIndex: 0
    property int detailIndex: 0
    property int emptyIndex: 0
    property int keepIdx: -1
    property var cur: ({})
    property var tileList: []
    property var sideList: []
    property string searchText: ""
    property bool typedSearch: false
    property int oskRow: 0
    property int oskCol: 0
    property string importReturn: "library"
    property var browseTarget: ({})
    property var browseData: ({ path: "", parent: "", dirs: [] })

    readonly property string oskChars: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-'"
    readonly property var oskActions: ["SPACE", "DELETE", "CLEAR", "DONE"]
    readonly property int activeTab: backend.currentFilter === "all" ? 0 : backend.currentFilter === "favorites" ? 1
                                    : backend.currentFilter === "recent" ? 2 : 3

    // ---------------------------------------------------------------- helpers
    function buildLists() {
        var t = []
        var src = backend.tiles
        for (var i = 0; i < src.length; i++) t.push(src[i])
        if (backend.totalGames === 0)
            t.push({ key: "__add", label: "Add Games", short: "Add Games", glyph: "plus", c1: "#8a1620", c2: "#2a0508", count: -1 })
        t.push({ key: "__more", label: backend.showAllSystems ? "Show fewer systems" : "Show all systems",
                 short: backend.showAllSystems ? "Show fewer systems" : "Show all systems",
                 glyph: "grid", c1: "#2a3050", c2: "#10121d", count: -1 })
        tileList = t
        var s = [{ key: "all", label: "All Games", icon: "grid" }]
        for (var j = 0; j < src.length; j++) s.push({ key: src[j].key, label: src[j].short, icon: src[j].glyph })
        s.push({ key: "__more", label: backend.showAllSystems ? "Show fewer systems" : "Show all systems", icon: "more" })
        s.push({ key: "favorites", label: "Favourites", icon: "heart" })
        s.push({ key: "recent", label: "Recent", icon: "clock" })
        s.push({ key: "__settings", label: "Settings", icon: "gear" })
        sideList = s
        tileIndex = Math.max(0, Math.min(tileIndex, tileList.length - 1))
        sideIndex = Math.max(0, Math.min(sideIndex, sideList.length - 1))
        syncSelection()
    }
    function syncSelection() {
        for (var i = 0; i < tileList.length; i++) if (tileList[i].key === backend.currentFilter) { tileIndex = i; break }
        for (var j = 0; j < sideList.length; j++) if (sideList[j].key === backend.currentFilter) { sideIndex = j; break }
    }
    function refreshCur() { cur = grid.count > 0 ? backend.games.get(grid.currentIndex) : ({}) }

    function selectFilter(key, focusGrid) {
        if (backend.query !== "") backend.setQuery("")
        backend.setFilter(key)
        grid.currentIndex = 0
        grid.positionViewAtBeginning()
        syncSelection()
        if (focusGrid) area = "grid"
    }
    function systemKeys() {
        var k = ["all"]
        for (var i = 0; i < backend.tiles.length; i++) k.push(backend.tiles[i].key)
        return k
    }
    function cycleSystem(delta) {
        var k = systemKeys()
        var i = k.indexOf(backend.currentFilter)
        if (i < 0) i = 0
        i = (i + delta + k.length) % k.length
        selectFilter(k[i], false)
    }
    function activateTile(i) {
        var t = tileList[i]
        if (!t) return
        if (t.key === "__add") openImport("library")
        else if (t.key === "__more") backend.toggleShowAllSystems()
        else selectFilter(t.key, true)
    }
    function activateSide(i) {
        var s = sideList[i]
        if (!s) return
        if (s.key === "__settings") openSetup()
        else if (s.key === "__more") backend.toggleShowAllSystems()
        else selectFilter(s.key, true)
    }
    function activateTab(i) {
        if (i <= 2) selectFilter(["all", "favorites", "recent"][i], grid.count > 0)
        else if (i === 3) area = "tiles"
        else if (i === 4) openSetup()
        else if (i === 5) openImport("library")
        else openSearch()
    }
    function toggleFav() {
        if (grid.count < 1) return
        keepIdx = grid.currentIndex
        backend.toggleFavorite(grid.currentIndex)
        keepIdx = -1
        refreshCur()
    }
    function launchCurrent() { if (grid.count > 0) backend.launch(grid.currentIndex) }

    function openOptions() { menuList.model = menuItems(); menuList.currentIndex = 0; mode = "menu" }
    function menuItems() {
        return [
            { kind: "item", id: "resume", title: "Resume" },
            { kind: "item", id: "sort", title: "Sort: " + backend.sortLabel + "  (change)" },
            { kind: "item", id: "add", title: "Add Games (USB stick or folder)" },
            { kind: "item", id: "rescan", title: "Rescan library" },
            { kind: "item", id: "emus", title: "Emulators" },
            { kind: "item", id: "settings", title: "Settings (Steam & ROM folders)" },
            { kind: "item", id: "full", title: "Toggle full screen" },
            { kind: "item", id: "quit", title: "Quit Atari" }
        ]
    }
    function openSort() {
        var at = 0
        for (var i = 0; i < backend.sortModes.length; i++) if (backend.sortModes[i].key === backend.sortKey) at = i
        sortList.currentIndex = at
        mode = "sort"
    }
    function openSearch() {
        searchText = backend.query
        typedSearch = false
        oskRow = 0; oskCol = 0
        mode = "search"
    }
    function closeSearch() { mode = "library"; area = grid.count > 0 ? "grid" : "tiles" }
    function setSearch(t) {
        searchText = t
        backend.setQuery(t)
        grid.currentIndex = 0
    }
    function refreshSetup(keep) {
        var idx = setupList.currentIndex
        setupList.model = backend.setupRows()
        if (keep) setupList.currentIndex = Math.min(idx, setupList.count - 1)
        else setupList.firstSelectable()
    }
    function openSetup() { refreshSetup(false); mode = "setup" }
    function leaveSetup() {
        if (backend.firstRun) return
        backend.rescan(false, false); buildLists(); mode = "library"
    }
    function refreshEmus(keep) {
        var idx = emuList.currentIndex
        emuList.model = backend.emulatorRows()
        if (keep) emuList.currentIndex = Math.min(idx, emuList.count - 1)
        else emuList.firstSelectable()
    }
    function openEmulators() { refreshEmus(false); mode = "emulators" }
    function openImport(ret) {
        importReturn = ret
        importScreen.open()
        mode = "import"
    }
    function closeImport() {
        if (importReturn === "setup") { refreshSetup(true); mode = "setup" }
        else { mode = "library"; buildLists(); area = grid.count > 0 ? "grid" : "tiles" }
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

    function goBack() {
        if (backend.query !== "") { backend.setQuery(""); return }
        if (area !== "grid" && grid.count > 0) { area = "grid"; return }
        if (backend.currentFilter !== "all") { selectFilter("all", true); return }
        openOptions()
    }

    function libraryKey(e) {
        var k = e.key
        var n = grid.count
        if (k === Qt.Key_F10 || k === Qt.Key_Menu || k === Qt.Key_M || k === Qt.Key_O) { openOptions(); return }
        if (k === Qt.Key_Slash || k === Qt.Key_Find || (k === Qt.Key_F && (e.modifiers & Qt.ControlModifier))) { openSearch(); return }
        if (k === Qt.Key_Tab || k === Qt.Key_Backtab) { area = area === "tiles" ? (n > 0 ? "grid" : "tiles") : "tiles"; return }
        if (k === Qt.Key_PageUp || k === Qt.Key_Q) { cycleSystem(-1); return }
        if (k === Qt.Key_PageDown || k === Qt.Key_E) { cycleSystem(1); return }
        if (k === Qt.Key_Escape || k === Qt.Key_Backspace) { goBack(); return }
        if (k === Qt.Key_S && !(e.modifiers & Qt.ControlModifier)) { openSort(); return }
        if (k === Qt.Key_F) { toggleFav(); return }
        if (area === "tabs") {
            if (k === Qt.Key_Left) tabFocus = Math.max(0, tabFocus - 1)
            else if (k === Qt.Key_Right) tabFocus = Math.min(6, tabFocus + 1)
            else if (k === Qt.Key_Down) area = "tiles"
            else if (isEnter(k) || k === Qt.Key_Space) activateTab(tabFocus)
            return
        }
        if (area === "tiles") {
            if (k === Qt.Key_Left || k === Qt.Key_Right) {
                tileIndex = Math.max(0, Math.min(tileList.length - 1, tileIndex + (k === Qt.Key_Left ? -1 : 1)))
                var t = tileList[tileIndex]
                if (t && t.key.indexOf("__") !== 0) selectFilter(t.key, false)
            }
            else if (k === Qt.Key_Up) { tabFocus = 3; area = "tabs" }
            else if (k === Qt.Key_Down) area = "grid"
            else if (isEnter(k) || k === Qt.Key_Space) activateTile(tileIndex)
            return
        }
        if (area === "side") {
            if (k === Qt.Key_Up) { if (sideIndex > 0) sideIndex--; else area = "tiles" }
            else if (k === Qt.Key_Down) sideIndex = Math.min(sideList.length - 1, sideIndex + 1)
            else if (k === Qt.Key_Right) area = "grid"
            else if (isEnter(k) || k === Qt.Key_Space) activateSide(sideIndex)
            return
        }
        if (area === "detail") {
            if (k === Qt.Key_Left) { if (detailIndex > 0) detailIndex--; else area = "grid" }
            else if (k === Qt.Key_Right) detailIndex = 1
            else if (k === Qt.Key_Up) area = "tiles"
            else if (isEnter(k) || k === Qt.Key_Space) { if (detailIndex === 0) launchCurrent(); else toggleFav() }
            return
        }
        // ---- grid
        if (n === 0) {
            var two = backend.totalGames === 0
            if (k === Qt.Key_Up) area = "tiles"
            else if (k === Qt.Key_Left) { if (two && emptyIndex > 0) emptyIndex--; else area = "side" }
            else if (k === Qt.Key_Right) { if (two && emptyIndex < 1) emptyIndex++ }
            else if (isEnter(k) || k === Qt.Key_Space) {
                if (two) { if (emptyIndex === 0) openImport("library"); else openSetup() }
            }
            return
        }
        var cols = grid.cols, i = grid.currentIndex
        if (k === Qt.Key_Left) { if (i % cols > 0) grid.currentIndex = i - 1; else area = "side" }
        else if (k === Qt.Key_Right) { if (i % cols < cols - 1 && i < n - 1) grid.currentIndex = i + 1; else { detailIndex = 0; area = "detail" } }
        else if (k === Qt.Key_Up) { if (i - cols >= 0) grid.currentIndex = i - cols; else area = "tiles" }
        else if (k === Qt.Key_Down) {
            if (i + cols < n) grid.currentIndex = i + cols
            else if (Math.floor(i / cols) < Math.floor((n - 1) / cols)) grid.currentIndex = n - 1
        }
        else if (k === Qt.Key_Home) grid.currentIndex = 0
        else if (k === Qt.Key_End) grid.currentIndex = n - 1
        else if (isEnter(k) || k === Qt.Key_Space) launchCurrent()
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
    }

    function menuKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape || k === Qt.Key_F10 || k === Qt.Key_Menu) { mode = "library"; return }
        if (k === Qt.Key_Up) menuList.move(-1)
        else if (k === Qt.Key_Down) menuList.move(1)
        else if (isEnter(k)) menuActivate(menuList.currentIndex)
    }
    function menuActivate(i) {
        var id = menuList.model[i].id
        if (id === "resume") mode = "library"
        else if (id === "sort") openSort()
        else if (id === "add") openImport("library")
        else if (id === "rescan") { backend.rescan(); buildLists(); mode = "library" }
        else if (id === "emus") { importReturn = "library"; openEmulators() }
        else if (id === "settings") openSetup()
        else if (id === "full") { backend.toggleFullscreen(); mode = "library" }
        else backend.quit()
    }
    function sortKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape || k === Qt.Key_S) { mode = "library"; return }
        if (k === Qt.Key_Up) sortList.currentIndex = Math.max(0, sortList.currentIndex - 1)
        else if (k === Qt.Key_Down) sortList.currentIndex = Math.min(sortList.count - 1, sortList.currentIndex + 1)
        else if (isEnter(k)) sortChoose(sortList.currentIndex)
    }
    function sortChoose(i) {
        backend.setSort(backend.sortModes[i].key)
        grid.currentIndex = 0
        grid.positionViewAtBeginning()
        mode = "library"
    }

    function setupKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape) { leaveSetup(); return }
        if (k === Qt.Key_Up) setupList.move(-1)
        else if (k === Qt.Key_Down) setupList.move(1)
        else if (k === Qt.Key_Delete || k === Qt.Key_Backspace || k === Qt.Key_F) {
            var row = setupList.model[setupList.currentIndex]
            if (row && row.kind === "system") { backend.clearSystemFolder(row.id); refreshSetup(true) }
        }
        else if (isEnter(k) || k === Qt.Key_Space) setupActivate(setupList.currentIndex)
    }
    function setupActivate(i) {
        var r = setupList.model[i]
        if (!r) return
        if (r.kind === "steam") { backend.toggleSteam(); refreshSetup(true) }
        else if (r.kind === "steamlib") openBrowser({ kind: "steamlib" }, backend.homeDir())
        else if (r.kind === "import") openImport("setup")
        else if (r.kind === "emulators") { importReturn = "setup"; openEmulators() }
        else if (r.kind === "system") {
            var cur = r.detail && r.detail.indexOf("Not set") !== 0 ? r.detail.split(", ")[0] : backend.homeDir()
            openBrowser({ kind: "system", id: r.id }, cur)
        }
        else if (r.kind === "done") { backend.finishSetup(); buildLists(); mode = "library"; area = grid.count > 0 ? "grid" : "tiles" }
    }

    function emuKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape) { if (importReturn === "setup") { refreshSetup(true); mode = "setup" } else mode = "library"; return }
        if (k === Qt.Key_Up) emuList.move(-1)
        else if (k === Qt.Key_Down) emuList.move(1)
        else if (isEnter(k) || k === Qt.Key_Space) emuActivate(emuList.currentIndex)
    }
    function emuActivate(i) {
        var r = emuList.model[i]
        if (!r) return
        if (r.kind === "emu") { backend.cycleEmulator(r.id); refreshEmus(true) }
        else if (r.kind === "back") { if (importReturn === "setup") { refreshSetup(true); mode = "setup" } else mode = "library" }
    }

    function browseKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape) { mode = browseTarget.kind === "import" ? "import" : "setup"; return }
        if (k === Qt.Key_Up) browseList.move(-1)
        else if (k === Qt.Key_Down) browseList.move(1)
        else if (k === Qt.Key_Left || k === Qt.Key_Backspace) {
            if (browseData.path !== "") loadDir(browseData.parent)
        }
        else if (isEnter(k) || k === Qt.Key_Right) browseActivate(browseList.currentIndex, isEnter(k))
    }
    function browseActivate(i, enter) {
        var r = browseList.model[i]
        if (!r) return
        if (r.kind === "dir") loadDir(r.path)
        else if (r.kind === "up") loadDir(browseData.parent)
        else if (r.kind === "use" && enter) {
            if (browseTarget.kind === "import") { backend.startImportScan(browseData.path); mode = "import" }
            else {
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
            else if (win.mode === "sort") sortKey(e)
            else if (win.mode === "setup") setupKey(e)
            else if (win.mode === "emulators") emuKey(e)
            else if (win.mode === "browse") browseKey(e)
            else if (win.mode === "import") importScreen.handleKey(e)
        }

        // ------------------------------------------------------------ banner + tabs
        TopBar {
            id: top
            u: win.u
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 104 * win.u
            activeTab: win.activeTab
            focusIndex: win.area === "tabs" && win.mode === "library" ? win.tabFocus : -1
            onActivated: function (i) { win.area = "tabs"; win.tabFocus = i; win.activateTab(i) }
        }

        // ------------------------------------------------------------ system tiles
        ListView {
            id: tileView
            anchors.top: top.bottom
            anchors.topMargin: 10 * win.u
            anchors.left: parent.left
            anchors.leftMargin: 10 * win.u
            anchors.right: parent.right
            anchors.rightMargin: 10 * win.u
            height: 196 * win.u
            orientation: ListView.Horizontal
            clip: true
            model: win.tileList
            currentIndex: win.tileIndex
            highlightFollowsCurrentItem: true
            highlightRangeMode: ListView.ApplyRange
            preferredHighlightBegin: width * 0.2
            preferredHighlightEnd: width * 0.8
            highlightMoveDuration: 160
            boundsBehavior: Flickable.StopAtBounds
            delegate: SystemTile {
                required property var modelData
                required property int index
                width: Math.floor((tileView.width) / 7)
                height: tileView.height
                u: win.u
                info: modelData
                selected: index === win.tileIndex && modelData.key.indexOf("__") !== 0
                focused: win.area === "tiles" && win.mode === "library" && index === win.tileIndex
                onClicked: { win.area = "tiles"; win.tileIndex = index; win.activateTile(index) }
            }
        }

        // ------------------------------------------------------------ bottom hints
        HintBar {
            id: hints
            u: win.u
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 56 * win.u
        }

        // ------------------------------------------------------------ main area
        Item {
            id: main
            anchors.top: tileView.bottom
            anchors.topMargin: 8 * win.u
            anchors.bottom: hints.top
            anchors.bottomMargin: 10 * win.u
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 14 * win.u
            anchors.rightMargin: 14 * win.u

            // ---- left sidebar
            Rectangle {
                id: side
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                width: 310 * win.u
                radius: 14 * win.u
                color: "#0d0f18"
                border.width: 1.5 * win.u
                border.color: win.area === "side" ? "#80e0202a" : Theme.line
                SideItem {
                    id: sideAll
                    anchors.top: parent.top
                    anchors.topMargin: 12 * win.u
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 10 * win.u
                    anchors.rightMargin: 10 * win.u
                    u: win.u
                    icon: win.sideList.length ? win.sideList[0].icon : "grid"
                    label: win.sideList.length ? win.sideList[0].label : ""
                    active: backend.currentFilter === "all"
                    focused: win.area === "side" && win.sideIndex === 0
                    onClicked: { win.area = "side"; win.sideIndex = 0; win.activateSide(0) }
                }
                Column {
                    id: sideFoot
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 12 * win.u
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 10 * win.u
                    anchors.rightMargin: 10 * win.u
                    spacing: 4 * win.u
                    Rectangle { width: parent.width; height: 1; color: Theme.line }
                    Repeater {
                        model: 3
                        SideItem {
                            required property int index
                            readonly property int gi: win.sideList.length - 3 + index
                            width: sideFoot.width
                            u: win.u
                            icon: win.sideList.length ? win.sideList[gi].icon : "grid"
                            label: win.sideList.length ? win.sideList[gi].label : ""
                            active: win.sideList.length > 0 && backend.currentFilter === win.sideList[gi].key
                            focused: win.area === "side" && win.sideIndex === gi
                            onClicked: { win.area = "side"; win.sideIndex = gi; win.activateSide(gi) }
                        }
                    }
                }
                ListView {
                    id: sideView
                    anchors.top: sideAll.bottom
                    anchors.topMargin: 4 * win.u
                    anchors.bottom: sideFoot.top
                    anchors.bottomMargin: 6 * win.u
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 10 * win.u
                    anchors.rightMargin: 10 * win.u
                    clip: true
                    spacing: 4 * win.u
                    model: Math.max(0, win.sideList.length - 4)
                    boundsBehavior: Flickable.StopAtBounds
                    currentIndex: win.sideIndex - 1
                    highlightMoveDuration: 0
                    delegate: SideItem {
                        required property int index
                        readonly property int gi: index + 1
                        width: sideView.width
                        u: win.u
                        icon: win.sideList[gi].icon
                        label: win.sideList[gi].label
                        active: backend.currentFilter === win.sideList[gi].key
                        focused: win.area === "side" && win.sideIndex === gi
                        onClicked: { win.area = "side"; win.sideIndex = gi; win.activateSide(gi) }
                    }
                }
            }

            // ---- right detail panel
            DetailPanel {
                id: detail
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: parent.right
                width: 440 * win.u
                u: win.u
                game: win.cur
                focused: win.area === "detail" && win.mode === "library"
                focusIndex: win.detailIndex
                onPlay: win.launchCurrent()
                onToggleFavorite: win.toggleFav()
            }

            // ---- centre: heading + grid
            Item {
                id: centre
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.left: side.right
                anchors.right: detail.left
                anchors.leftMargin: 18 * win.u
                anchors.rightMargin: 18 * win.u

                Item {
                    id: heading
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 48 * win.u
                    Row {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 10 * win.u
                        Text {
                            text: backend.query !== "" ? "SEARCH: " + backend.query.toUpperCase() : backend.currentLabel.toUpperCase()
                            color: "white"
                            font.pixelSize: 24 * win.u
                            font.bold: true
                            font.letterSpacing: 1.5 * win.u
                            elide: Text.ElideRight
                        }
                        Text {
                            text: "(" + grid.count.toLocaleString(Qt.locale("en_GB"), "f", 0) + ")"
                            color: Theme.redBright
                            font.pixelSize: 24 * win.u
                            font.bold: true
                        }
                    }
                    Rectangle {
                        id: sortBtn
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        height: 36 * win.u
                        width: sortRow.implicitWidth + 28 * win.u
                        radius: 8 * win.u
                        color: "#121420"
                        border.width: 1.5 * win.u
                        border.color: win.mode === "sort" ? Theme.red : "#2c3044"
                        Row {
                            id: sortRow
                            anchors.centerIn: parent
                            spacing: 8 * win.u
                            Text { text: "Sort: " + backend.sortLabel; color: "#dfe2ee"; font.pixelSize: 17 * win.u
                                   anchors.verticalCenter: parent.verticalCenter }
                            Icon { name: "chevron"; size: 18 * win.u; color: Theme.redBright; stroke: 2.6
                                   anchors.verticalCenter: parent.verticalCenter }
                        }
                        MouseArea { anchors.fill: parent; onClicked: win.openSort() }
                    }
                }

                GridView {
                    id: grid
                    readonly property int cols: Math.max(2, Math.round(width / (216 * win.u)))
                    anchors.top: heading.bottom
                    anchors.topMargin: 6 * win.u
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    cellWidth: Math.floor(width / cols)
                    cellHeight: cellWidth * 0.86 + 36 * win.u
                    clip: true
                    model: backend.games
                    keyNavigationEnabled: false
                    boundsBehavior: Flickable.StopAtBounds
                    highlight: Item {}
                    highlightMoveDuration: 140
                    onCurrentIndexChanged: Qt.callLater(win.refreshCur)
                    onCountChanged: Qt.callLater(win.refreshCur)
                    delegate: GameTile {
                        width: grid.cellWidth
                        height: grid.cellHeight
                        u: win.u
                        current: GridView.isCurrentItem
                        focused: win.area === "grid" && win.mode === "library"
                        onClicked: { win.area = "grid"; grid.currentIndex = index }
                        onActivated: { grid.currentIndex = index; backend.launch(index) }
                    }
                }
                Connections {
                    target: backend.games
                    function onModelReset() {
                        if (win.keepIdx >= 0) grid.currentIndex = Math.max(0, Math.min(win.keepIdx, grid.count - 1))
                        else { grid.currentIndex = 0; grid.positionViewAtBeginning() }
                        Qt.callLater(win.refreshCur)
                    }
                    function onDataChanged() { Qt.callLater(win.refreshCur) }
                }

                // ---- friendly empty state
                Column {
                    anchors.centerIn: grid
                    width: grid.width * 0.86
                    spacing: 18 * win.u
                    visible: grid.count === 0
                    Icon { anchors.horizontalCenter: parent.horizontalCenter; name: backend.totalGames === 0 ? "pad" : "search"
                           size: 70 * win.u; color: "#4a5170"; stroke: 1.5 }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        color: "#c4c8da"
                        font.pixelSize: 22 * win.u
                        lineHeight: 1.15
                        text: {
                            backend.currentFilter; backend.query; backend.totalGames; backend.showAllSystems
                            return backend.emptyMessage()
                        }
                    }
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 16 * win.u
                        visible: backend.totalGames === 0
                        Rectangle {
                            readonly property bool sel: win.area === "grid" && win.emptyIndex === 0
                            width: 250 * win.u; height: 58 * win.u; radius: 10 * win.u
                            gradient: Gradient {
                                GradientStop { position: 0; color: "#ee2a34" } GradientStop { position: 1; color: "#a8121b" } }
                            border.width: sel ? 3 * win.u : 0
                            border.color: "white"
                            Row { anchors.centerIn: parent; spacing: 8 * win.u
                                Icon { name: "plus"; size: 22 * win.u; stroke: 2.8; color: "white"; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: "ADD GAMES"; color: "white"; font.pixelSize: 19 * win.u; font.bold: true
                                       anchors.verticalCenter: parent.verticalCenter } }
                            MouseArea { anchors.fill: parent; onClicked: win.openImport("library") }
                        }
                        Rectangle {
                            readonly property bool sel: win.area === "grid" && win.emptyIndex === 1
                            width: 250 * win.u; height: 58 * win.u; radius: 10 * win.u
                            color: "#171a28"
                            border.width: sel ? 3 * win.u : 1.5 * win.u
                            border.color: sel ? "white" : "#4a5170"
                            Row { anchors.centerIn: parent; spacing: 8 * win.u
                                Icon { name: "gear"; size: 22 * win.u; color: "white"; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: "OPEN SETTINGS"; color: "white"; font.pixelSize: 19 * win.u; font.bold: true
                                       anchors.verticalCenter: parent.verticalCenter } }
                            MouseArea { anchors.fill: parent; onClicked: win.openSetup() }
                        }
                    }
                }
            }
        }

        // ------------------------------------------------------------ toast
        Rectangle {
            id: toast
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: hints.top
            anchors.bottomMargin: 18 * win.u
            width: Math.min(parent.width - 80 * win.u, toastText.implicitWidth + 60 * win.u)
            height: toastText.implicitHeight + 28 * win.u
            radius: 12 * win.u
            color: "#f0101320"
            border.color: Theme.red
            border.width: 2.5 * win.u
            opacity: backend.toast !== "" ? 1 : 0
            visible: opacity > 0
            z: 20
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Text {
                id: toastText
                anchors.centerIn: parent
                width: Math.min(implicitWidth, toast.parent.width - 140 * win.u)
                text: backend.toast
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                color: Theme.text
                font.pixelSize: 24 * win.u
            }
        }

        // ------------------------------------------------- overlay: search
        Rectangle {
            anchors.fill: parent
            color: "#e606070b"
            visible: win.mode === "search"
            MouseArea { anchors.fill: parent }
            Column {
                anchors.centerIn: parent
                spacing: 18 * win.u
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "SEARCH"
                    color: Theme.redBright
                    font.pixelSize: 40 * win.u
                    font.bold: true
                    font.letterSpacing: 8 * win.u
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 1000 * win.u
                    height: 84 * win.u
                    radius: 12 * win.u
                    color: "#121420"
                    border.color: Theme.red
                    border.width: 3 * win.u
                    Icon { id: sIc; name: "search"; size: 34 * win.u; color: Theme.dim; anchors.left: parent.left
                           anchors.leftMargin: 22 * win.u; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        anchors.left: sIc.right
                        anchors.leftMargin: 16 * win.u
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: win.searchText === "" ? "Type to filter games..." : win.searchText + "\u258c"
                        color: win.searchText === "" ? Theme.faint : Theme.text
                        font.pixelSize: 40 * win.u
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: grid.count + (grid.count === 1 ? " match" : " matches")
                    color: Theme.dim
                    font.pixelSize: 24 * win.u
                }
                Grid {
                    anchors.horizontalCenter: parent.horizontalCenter
                    columns: 10
                    spacing: 8 * win.u
                    Repeater {
                        model: 40
                        Rectangle {
                            required property int index
                            readonly property bool sel: win.oskRow === Math.floor(index / 10) && win.oskCol === index % 10
                            width: 84 * win.u
                            height: 72 * win.u
                            radius: 8 * win.u
                            color: sel ? Theme.red : "#121420"
                            border.color: "#2c3044"
                            border.width: sel ? 0 : 1.5 * win.u
                            Text {
                                anchors.centerIn: parent
                                text: win.oskChars.charAt(index) === " " ? "\u2423" : win.oskChars.charAt(index)
                                color: "white"
                                font.pixelSize: 34 * win.u
                                font.bold: true
                            }
                        }
                    }
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8 * win.u
                    Repeater {
                        model: win.oskActions
                        Rectangle {
                            required property string modelData
                            required property int index
                            readonly property bool sel: win.oskRow === 4 && win.oskCol === index
                            width: 210 * win.u
                            height: 72 * win.u
                            radius: 8 * win.u
                            color: sel ? Theme.red : "#121420"
                            border.color: "#2c3044"
                            border.width: sel ? 0 : 1.5 * win.u
                            Text { anchors.centerIn: parent; text: modelData; color: "white"; font.pixelSize: 26 * win.u; font.bold: true }
                        }
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Keyboard: just type, Enter = done.   Gamepad: D-pad + A,  X = backspace,  B = close"
                    color: Theme.dim
                    font.pixelSize: 22 * win.u
                }
            }
        }

        // ------------------------------------------------- overlay: options menu
        Rectangle {
            anchors.fill: parent
            color: Theme.overlay
            visible: win.mode === "menu"
            MouseArea { anchors.fill: parent; onClicked: win.mode = "library" }
            Column {
                anchors.centerIn: parent
                spacing: 20 * win.u
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "OPTIONS"
                    color: Theme.redBright
                    font.pixelSize: 48 * win.u
                    font.bold: true
                    font.letterSpacing: 10 * win.u
                }
                MenuList {
                    id: menuList
                    u: win.u
                    width: 820 * win.u
                    height: 8 * 70 * win.u
                    model: win.menuItems()
                    onClicked: function (i) { win.menuActivate(i) }
                }
            }
        }

        // ------------------------------------------------- overlay: sort dropdown
        Rectangle {
            anchors.fill: parent
            color: "#66000000"
            visible: win.mode === "sort"
            MouseArea { anchors.fill: parent; onClicked: win.mode = "library" }
            Rectangle {
                x: Math.min(parent.width - width - 20 * win.u, main.x + centre.x + centre.width - width)
                y: main.y + heading.height + 6 * win.u
                width: 300 * win.u
                height: sortList.height + 20 * win.u
                radius: 12 * win.u
                color: "#10121c"
                border.width: 2 * win.u
                border.color: Theme.red
                MenuList {
                    id: sortList
                    u: win.u
                    anchors.centerIn: parent
                    width: parent.width - 20 * win.u
                    height: 4 * 70 * win.u
                    model: {
                        var m = []
                        for (var i = 0; i < backend.sortModes.length; i++)
                            m.push({ kind: "item", title: backend.sortModes[i].label,
                                     value: backend.sortModes[i].key === backend.sortKey ? "\u2713" : "" })
                        return m
                    }
                    onClicked: function (i) { win.sortChoose(i) }
                }
            }
        }

        // ---------------------------------------------------- overlay: settings
        Rectangle {
            anchors.fill: parent
            color: "#08090e"
            visible: win.mode === "setup" || win.mode === "browse" || win.mode === "emulators"
            MouseArea { anchors.fill: parent }
            Item {
                id: setupHead
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 128 * win.u
                clip: true
                Image {
                    anchors.fill: parent
                    source: Qt.resolvedUrl("../assets/banner.jpg")
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    sourceSize.width: 1920
                }
                Rectangle { anchors.fill: parent; color: "#88000000" }
                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 48 * win.u
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6 * win.u
                    Text {
                        text: win.mode === "emulators" ? "EMULATORS" : (backend.firstRun ? "WELCOME! LET'S SET UP YOUR GAMES" : "SETTINGS")
                        color: Theme.redBright
                        font.pixelSize: 42 * win.u
                        font.bold: true
                        font.letterSpacing: 4 * win.u
                    }
                    Text {
                        text: win.mode === "browse"
                              ? "Pick the folder, then choose \"Use this folder\".  Left = up, Esc / B = cancel."
                              : win.mode === "emulators"
                              ? "Enter / A switches the emulator for a console.  Esc / B = back."
                              : "Up/Down to choose, Enter / A to change.  Delete / X clears a folder.  Esc / B = back."
                        color: "#e6e8f2"
                        font.pixelSize: 21 * win.u
                    }
                }
            }
            Rectangle { id: setupLine; anchors.top: setupHead.bottom; width: parent.width; height: 3 * win.u; color: Theme.red }
            Item {
                id: ntfs
                anchors.top: setupLine.bottom
                anchors.topMargin: 12 * win.u
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width - 100 * win.u, 1500 * win.u)
                height: win.mode === "setup" ? ntfsText.implicitHeight : 0
                visible: win.mode === "setup"
                Text {
                    id: ntfsText
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: backend.ntfsNote
                    color: Theme.yellow
                    font.pixelSize: 18 * win.u
                }
            }
            MenuList {
                id: setupList
                u: win.u
                anchors.top: ntfs.bottom
                anchors.topMargin: 14 * win.u
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 20 * win.u
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width - 100 * win.u, 1500 * win.u)
                visible: win.mode === "setup"
                model: []
                onClicked: function (i) { win.setupActivate(i) }
            }
            MenuList {
                id: emuList
                u: win.u
                anchors.top: setupLine.bottom
                anchors.topMargin: 16 * win.u
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 20 * win.u
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width - 100 * win.u, 1500 * win.u)
                visible: win.mode === "emulators"
                model: []
                onClicked: function (i) { win.emuActivate(i) }
            }
            Item {
                anchors.fill: setupList
                anchors.topMargin: -ntfs.height - 14 * win.u + 16 * win.u
                visible: win.mode === "browse"
                Text {
                    id: browsePath
                    width: parent.width
                    elide: Text.ElideMiddle
                    text: win.browseData.path === "" ? "Choose a place" : win.browseData.path
                    color: Theme.yellow
                    font.pixelSize: 26 * win.u
                    height: 46 * win.u
                }
                MenuList {
                    id: browseList
                    u: win.u
                    anchors.top: browsePath.bottom
                    anchors.bottom: parent.bottom
                    width: parent.width
                    model: []
                    onClicked: function (i) { win.browseActivate(i, true) }
                }
            }
        }

        // ---------------------------------------------------- overlay: add games
        ImportScreen {
            id: importScreen
            anchors.fill: parent
            u: win.u
            visible: win.mode === "import"
            onClosed: win.closeImport()
            onBrowseRequested: win.openBrowser({ kind: "import" }, backend.importBrowseStart())
        }

        // ------------------------------------------------- overlay: running
        Rectangle {
            anchors.fill: parent
            color: "#f506070b"
            visible: backend.running
            z: 30
            MouseArea { anchors.fill: parent }
            Column {
                anchors.centerIn: parent
                spacing: 18 * win.u
                Wordmark { anchors.horizontalCenter: parent.horizontalCenter; u: win.u }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "NOW PLAYING"
                    color: Theme.redBright
                    font.pixelSize: 36 * win.u
                    font.bold: true
                    font.letterSpacing: 8 * win.u
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: backend.runningTitle
                    color: Theme.text
                    font.pixelSize: 58 * win.u
                    font.bold: true
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Starting up... this screen returns when you quit the game."
                    color: Theme.dim
                    font.pixelSize: 26 * win.u
                }
            }
        }
    }

    Connections {
        target: backend
        function onFiltersChanged() { win.buildLists() }
        function onTilesChanged() { win.buildLists() }
        function onCurrentFilterChanged() { win.syncSelection() }
        function onLibraryChanged() { win.buildLists() }
    }
    Component.onCompleted: {
        buildLists()
        if (backend.firstRun) refreshSetup(false)
        area = grid.count > 0 ? "grid" : "tiles"
        root.forceActiveFocus()
        refreshCur()
    }
}
