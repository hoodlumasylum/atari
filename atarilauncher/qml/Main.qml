import QtQuick
import QtQuick.Window

Window {
    id: win
    visible: true
    width: 1280
    height: 720
    title: "CodeAque"
    color: Theme.bg
    visibility: (backend.fullscreen || (mode === "intro" && Qt.platform.pluginName !== "offscreen")) ? Window.FullScreen : Window.Windowed     // the intro is always full screen (the headless test platform cannot)

    // everything is drawn in "units" that scale with the window (1 unit = 1 pixel at 1920x1080)
    Binding { target: Theme; property: "anim"; value: backend.animations }
    readonly property real u: Math.max(0.4, Math.min(width / 1920, height / 1080))

    // library | search | menu | sort | setup | browse | emulators | controls | update | import
    property string mode: backend.introActive ? "intro" : (backend.firstRun ? "setup" : "library")
    property string introBack: backend.firstRun ? "setup" : "library"     // where to go when the intro ends
    property string area: "grid"        // which part of the library has the highlight: tabs tiles side grid detail
    property int tabFocus: 0            // 0-4 tabs, 5 Add Games, 6 search, 7 WiFi, 8-10 music
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
    property string emuBack: "library"       // where Back from the Emulators page goes, while an import started there
    property string updBack: "library"       // where Back from the Update screen goes: library | setup
    property string ctlBack: "library"       // where Back from the Controls page goes: library | emulators
    property string pageName: "help"          // help | fix | winform | winchoose | winwork (the generic list page)
    property string oskPurpose: "search"      // search | winname (the on-screen keyboard is shared)
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
        if (t.key === "__add") openPage("addgames")
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
        else if (i === 5) openPage("addgames")
        else if (i === 7) openWifi("library")
        else if (i >= 8) backend.media.press(["previous", "play-pause", "next"][i - 8])
        else openSearch()
    }
    function toggleFav() {
        if (grid.count < 1) return
        keepIdx = grid.currentIndex
        backend.toggleFavorite(grid.currentIndex)
        keepIdx = -1
        refreshCur()
    }
    // "Delete game": the page asks first (the highlight starts on No). Steam games only offer to open Steam's own uninstall.
    function openDelete() {
        if (grid.count < 1) return
        if (backend.openDeleteGame(grid.currentIndex)) openPage("deletegame")
    }
    function launchCurrent() { if (grid.count > 0) backend.launch(grid.currentIndex) }

    function openStudio() { studioScreen.open(); mode = "studio" }
    property string wifiReturn: "library"
    function openWifi(from) { wifiReturn = from || "library"; wifiScreen.open(); mode = "wifi" }
    function openOptions() { menuList.model = menuItems(); menuList.currentIndex = 0; mode = "menu" }
    function menuItems() {
        return [
            { kind: "item", id: "resume", title: "Resume" },
            { kind: "item", id: "sort", title: "Sort: " + backend.sortLabel + "  (change)" },
            { kind: "item", id: "add", title: "Add Games (USB stick or folder)" },
            { kind: "item", id: "bios", title: "Add BIOS files (USB stick or folder)" },
            { kind: "item", id: "studio", title: "Studio: make music (beats, voice, mix)" },
            { kind: "item", id: "winadd", title: "Add Windows game (.exe or .zip)" },
            { kind: "item", id: "pickcover", title: "Pick cover for the highlighted game" },
            { kind: "item", id: "record", title: backend.recording ? "Stop recording (F9)" : "Record screen (F9)" },
            { kind: "item", id: "recordings", title: "Recordings (watch your videos)" },
            { kind: "item", id: "fix", title: "Fix my game (checks the highlighted game)" },
            { kind: "item", id: "help", title: "Help & getting started" },
            { kind: "item", id: "rescan", title: "Rescan library" },
            { kind: "item", id: "emus", title: "Emulators" },
            { kind: "item", id: "update", title: backend.updateAvailable ? "Update CodeAque  (" + backend.updateVersion + " is ready)" : "Update CodeAque" },
            { kind: "item", id: "settings", title: "Settings (Steam & ROM folders)" },
            { kind: "item", id: "golive", title: "Go Live: stream to Twitch, TikTok, YouTube with OBS" },
            { kind: "item", id: "downloads", title: "Downloads: web browser, add downloaded files to my games" },
            { kind: "item", id: "files", title: "My files: browse Downloads, Games, Videos (unzip, rename, delete)" },
            { kind: "item", id: "support", title: "Support CodeAque (optional donation page)" },
            { kind: "item", id: "full", title: "Toggle full screen" },
            { kind: "item", id: "power", title: "Power: restart CodeAque, restart device, shut down" }
        ]
    }
    function openSort() {
        var at = 0
        for (var i = 0; i < backend.sortModes.length; i++) if (backend.sortModes[i].key === backend.sortKey) at = i
        sortList.currentIndex = at
        mode = "sort"
    }
    function openOsk(purpose) {
        oskPurpose = purpose
        searchText = purpose === "sgdbkey" ? backend.steamGridKey() : backend.winName()
        typedSearch = false
        oskRow = 0; oskCol = 0
        mode = "search"
    }
    function openSearch() {
        oskPurpose = "search"
        searchText = backend.query
        typedSearch = false
        oskRow = 0; oskCol = 0
        mode = "search"
    }
    function closeSearch() {
        if (oskPurpose === "winname") { oskPurpose = "search"; openPage("winform"); return }
        if (oskPurpose === "sgdbkey") { oskPurpose = "search"; refreshSetup(true); mode = "setup"; return }
        mode = "library"; area = grid.count > 0 ? "grid" : "tiles"
    }
    function setSearch(t) {
        if (oskPurpose === "winname") { searchText = t; backend.winSetName(t); return }
        if (oskPurpose === "sgdbkey") { searchText = t; backend.setSteamGridKey(t); return }
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
    // Esc / B / the DONE rows / the DONE button: leave the setup page for the main screen.
    // On the very first run this also marks the welcome screen as seen, so it never shows again.
    function leaveSetup() {
        if (backend.firstRun) backend.finishSetup()
        else backend.rescan(false, false)
        buildLists()
        mode = "library"
        area = grid.count > 0 ? "grid" : "tiles"
    }
    function refreshEmus(keep) {
        var idx = emuList.currentIndex
        emuList.model = backend.emulatorRows()
        if (keep) emuList.currentIndex = Math.min(idx, emuList.count - 1)
        else emuList.firstSelectable()
    }
    // ---- generic list pages: help, fix my game, add a Windows game
    function openPage(name) {
        pageName = name
        pageList.model = backend.pageRows(name)
        pageList.firstSelectable()
        mode = "page"
    }
    function refreshPage(keep) {
        var idx = pageList.currentIndex
        pageList.model = backend.pageRows(pageName)
        if (keep) pageList.currentIndex = Math.min(idx, pageList.count - 1)
        var r = pageList.model[pageList.currentIndex]
        if (!r || r.kind === "info" || r.kind === "progress") pageList.firstSelectable()
    }
    function leavePage() {
        if (pageName === "winwork") backend.pageActivate("winwork", "cancel")
        mode = "library"
        buildLists()
        area = grid.count > 0 ? "grid" : "tiles"
    }
    function handleAction(a) {
        if (a === "" || a === undefined) return
        if (a === "refresh") refreshPage(true)
        else if (a === "back" || a === "close") leavePage()
        else if (a === "browse:winfile") openBrowser({ kind: "winfile", files: "exe" }, backend.winBrowseStart())
        else if (a === "browse:winaddwizard") openBrowser({ kind: "winfile", files: "exe", wizard: true }, "")
        else if (a === "browse:importfolder") openBrowser({ kind: "importfolder" }, "")
        else if (a === "browse:gamecover") openBrowser({ kind: "gamecover", files: "image", gid: backend.pickGid() }, backend.winBrowseStart())
        else if (a === "browse:wincover") openBrowser({ kind: "wincover", files: "image" }, backend.winBrowseStart())
        else if (a === "osk:winname") openOsk("winname")
        else if (a === "import:games") openImport("page", "games")
        else if (a === "import:bios") openImport("page", "bios")
        else if (a === "import:biospick") { openImport("page", "bios"); backend.importBiosFromPick("") }
        else if (a === "controls") openControls("page")
        else if (a.indexOf("page:") === 0) openPage(a.substring(5))
        else openPage(a)
    }
    function pageActivateRow(i) {
        var r = pageList.model[i]
        if (!r || !r.id) return
        handleAction(backend.pageActivate(pageName, r.id))
    }
    function pageKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape || k === Qt.Key_B) { handleAction(backend.pageEscape(pageName)); return }
        if (k === Qt.Key_Up) pageList.move(-1)
        else if (k === Qt.Key_Down) pageList.move(1)
        else if (isEnter(k) || k === Qt.Key_Space) pageActivateRow(pageList.currentIndex)
    }
    function openEmulators() { refreshEmus(false); mode = "emulators" }
    function openImport(ret, kind) {
        if (ret === "emus") emuBack = importReturn
        importReturn = ret
        importScreen.open(kind || "games")
        mode = "import"
    }
    function openControls(back) {
        ctlBack = back
        ctlList.model = backend.controlsRows()
        ctlList.firstSelectable()
        mode = "controls"
    }
    function openUpdate(back) {
        updBack = back
        backend.openUpdate()
        updNotes.contentY = 0
        mode = "update"
    }
    function leaveUpdate() {
        if (updBack === "setup") { refreshSetup(true); mode = "setup" } else mode = "library"
    }
    function updPrimary() {
        var st = backend.updateState
        if (st === "available") backend.startUpdate()
        else if (st === "done") backend.restartAtari()
        else if (st === "error") backend.recheckUpdate()
        else if (st === "uptodate") leaveUpdate()
    }
    function updKey(e) {
        var k = e.key, st = backend.updateState
        if (k === Qt.Key_Escape || k === Qt.Key_B) {
            if (st === "downloading") backend.cancelUpdate()
            else if (st === "verifying" || st === "installing") return     // too late to stop safely
            else leaveUpdate()
            return
        }
        if (k === Qt.Key_Up) updNotes.contentY = Math.max(0, updNotes.contentY - 60 * win.u)
        else if (k === Qt.Key_Down) updNotes.contentY = Math.max(0, Math.min(updNotes.contentHeight - updNotes.height, updNotes.contentY + 60 * win.u))
        else if (isEnter(k) || k === Qt.Key_Space) updPrimary()
    }
    function leaveControls() {
        if (ctlBack === "emulators") { refreshEmus(true); mode = "emulators" }
        else if (ctlBack === "page") { refreshPage(true); mode = "page" }
        else mode = "library"
    }
    function ctlKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape || k === Qt.Key_B) { leaveControls(); return }
        if (k === Qt.Key_Up) ctlList.move(-1)
        else if (k === Qt.Key_Down) ctlList.move(1)
        else if (isEnter(k) || k === Qt.Key_Space) {
            if (ctlList.model[ctlList.currentIndex].kind === "back") leaveControls()
        }
    }
    function leaveEmus() {
        if (importReturn === "setup") { refreshSetup(true); mode = "setup" } else mode = "library"
    }
    function closeImport() {
        if (importReturn === "emus") { importReturn = emuBack; refreshEmus(true); mode = "emulators" }
        else if (importReturn === "setup") { refreshSetup(true); mode = "setup" }
        else if (importReturn === "page") { refreshPage(true); mode = "page" }
        else { mode = "library"; buildLists(); area = grid.count > 0 ? "grid" : "tiles" }
    }
    function openBrowser(target, startPath) {
        browseTarget = target
        loadDir(startPath)
        mode = "browse"
    }
    function loadDir(path) {
        var picking = !!browseTarget.files
        browseData = picking ? backend.listFiles(path, browseTarget.files) : backend.listDir(path)
        var rows = [{ kind: "back", title: "\u25c0  Back", detail: "" }]
        if (browseData.path !== "" && !picking)
            rows.push({ kind: "use", title: "Use this folder", detail: browseData.path })
        if (browseTarget.kind === "wincover")
            rows.push({ kind: "nocover", title: "No cover picture", detail: "" })
        if (browseData.path !== "")
            rows.push({ kind: "up", title: ".. (go up)", detail: "" })
        for (var i = 0; i < browseData.dirs.length; i++)
            rows.push({ kind: "dir", title: browseData.dirs[i].name, detail: "", path: browseData.dirs[i].path })
        if (picking && browseData.files)
            for (var j = 0; j < browseData.files.length; j++)
                rows.push({ kind: "file", title: browseData.files[j].name, detail: "", path: browseData.files[j].path })
        browseList.model = rows
        browseList.currentIndex = rows.length > 1 ? 1 : 0     // not on Back: the first real choice
    }

    // ------------------------------------------------------------ key handling
    // The little sound for a key press (gamepad buttons arrive here as key presses too).
    function keySound(e) {
        var k = e.key
        if (k === Qt.Key_Up || k === Qt.Key_Down || k === Qt.Key_Left || k === Qt.Key_Right || k === Qt.Key_Tab
                || k === Qt.Key_Backtab || k === Qt.Key_Q || k === Qt.Key_E) {
            if (mode === "search" && (k === Qt.Key_Q || k === Qt.Key_E) ) return ""
            return "tick"
        }
        if (k === Qt.Key_Escape || (k === Qt.Key_B && mode !== "search")) return "back"
        if (k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_F10) return "select"
        return ""
    }
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
            if (tabFocus > 7 && !backend.media.active) tabFocus = 7
            if (k === Qt.Key_Left) tabFocus = Math.max(0, tabFocus - 1)
            else if (k === Qt.Key_Right) tabFocus = Math.min(backend.media.active ? 10 : 7, tabFocus + 1)
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
            if (k === Qt.Key_Left) { if (detailIndex === 1 || detailIndex === 2) detailIndex = 0; else area = "grid" }
            else if (k === Qt.Key_Right) { if (detailIndex === 0) detailIndex = 1 }
            else if (k === Qt.Key_Down) { if (detailIndex < 2 && cur.canDelete === true) detailIndex = 2 }
            else if (k === Qt.Key_Up) { if (detailIndex === 2) detailIndex = 0; else area = "tiles" }
            else if (k === Qt.Key_Delete) openDelete()
            else if (isEnter(k) || k === Qt.Key_Space) { if (detailIndex === 0) launchCurrent(); else if (detailIndex === 1) toggleFav(); else openDelete() }
            return
        }
        // ---- grid
        if (n === 0) {
            var two = backend.totalGames === 0
            if (k === Qt.Key_Up) area = "tiles"
            else if (k === Qt.Key_Left) { if (two && emptyIndex > 0) emptyIndex--; else area = "side" }
            else if (k === Qt.Key_Right) { if (two && emptyIndex < 1) emptyIndex++ }
            else if (isEnter(k) || k === Qt.Key_Space) {
                if (two) { if (emptyIndex === 0) openPage("addgames"); else openSetup() }
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
        else if (k === Qt.Key_Delete) openDelete()
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
        else if (id === "add") openPage("addgames")
        else if (id === "bios") openImport("library", "bios")
        else if (id === "studio") openStudio()
        else if (id === "downloads") openPage("downloads")
        else if (id === "files") { backend.filesReset(); openPage("files") }
        else if (id === "golive") openPage("golive")
        else if (id === "winadd") openBrowser({ kind: "winfile", files: "exe" }, backend.winBrowseStart())
        else if (id === "pickcover") { backend.openCoverPicker(grid.count > 0 ? grid.currentIndex : -1); openPage("coverpick") }
        else if (id === "record") { mode = "library"; backend.toggleRecording() }
        else if (id === "recordings") openPage("recordings")
        else if (id === "fix") { backend.openFix(grid.count > 0 ? grid.currentIndex : -1); openPage("fix") }
        else if (id === "help") openPage("help")
        else if (id === "update") openUpdate("library")
        else if (id === "rescan") { backend.rescan(); buildLists(); mode = "library" }
        else if (id === "emus") { importReturn = "library"; openEmulators() }
        else if (id === "settings") openSetup()
        else if (id === "support") { mode = "library"; backend.supportCode() }
        else if (id === "full") { backend.toggleFullscreen(); mode = "library" }
        else if (id === "power") { backend.powerReset(); openPage("power") }
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
        if (k === Qt.Key_Escape || k === Qt.Key_B) { leaveSetup(); return }
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
        else if (r.kind === "bios") openImport("setup", "bios")
        else if (r.kind === "update") openUpdate("setup")
        else if (r.kind === "updateauto") { backend.toggleUpdateCheck(); refreshSetup(true) }
        else if (r.kind === "sfx") { backend.toggleSoundEffects(); refreshSetup(true) }
        else if (r.kind === "music") { backend.toggleMusic(); refreshSetup(true) }
        else if (r.kind === "volume") { backend.cycleVolume(); refreshSetup(true) }
        else if (r.kind === "recnow") { backend.toggleRecording(); refreshSetup(true) }
        else if (r.kind === "recaudio") { backend.cycleRecAudio(); refreshSetup(true) }
        else if (r.kind === "recquality") { backend.cycleRecQuality(); refreshSetup(true) }
        else if (r.kind === "recfps") { backend.toggleRecFps(); refreshSetup(true) }
        else if (r.kind === "recdir") openBrowser({ kind: "recdir" }, backend.homeDir())
        else if (r.kind === "sgdbkey") openOsk("sgdbkey")
        else if (r.kind === "installmenu") backend.installEmulators()
        else if (r.kind === "steampage") openPage("steam")
        else if (r.kind === "kioskpage") openPage("kiosk")
        else if (r.kind === "quietbootpage") openPage("quietboot")
        else if (r.kind === "bootreport") backend.saveBootReport()
        else if (r.kind === "fixfolder") { if (r.value) { backend.fixGamesFolder(r.id); refreshSetup(true) } }
        else if (r.kind === "kioskupdate") { backend.updateKioskSession(); refreshSetup(true) }
        else if (r.kind === "wifipage") openWifi("setup")
        else if (r.kind === "introvideo") { backend.toggleIntro(); refreshSetup(true) }
        else if (r.kind === "introdefault") { backend.toggleIntroDefault(); refreshSetup(true) }
        else if (r.kind === "support") backend.supportCode()
        else if (r.kind === "introsound") { backend.toggleIntroSound(); refreshSetup(true) }
        else if (r.kind === "introchoose") openBrowser({ kind: "introfile", files: "video" }, backend.introBrowseStart())
        else if (r.kind === "introremove") { backend.removeIntro(); refreshSetup(true) }
        else if (r.kind === "intropreview") backend.previewIntro()
        else if (r.kind === "bigpicture") { backend.toggleSteamBigPicture(); refreshSetup(true) }
        else if (r.kind === "escexit") { backend.toggleEscExit(); refreshSetup(true) }
        else if (r.kind === "anim") { backend.toggleAnimations(); refreshSetup(true) }
        else if (r.kind === "covers") { backend.downloadCoversNow(); refreshSetup(true) }
        else if (r.kind === "coversauto") { backend.toggleCoversAuto(); refreshSetup(true) }
        else if (r.kind === "emulators") { importReturn = "setup"; openEmulators() }
        else if (r.kind === "system") {
            var cur = r.detail && r.detail.indexOf("Not set") !== 0 ? r.detail.split(", ")[0] : backend.homeDir()
            openBrowser({ kind: "system", id: r.id }, cur)
        }
        else if (r.kind === "done") leaveSetup()
    }

    // the on-screen button next to the title of Settings / Folder picker / Emulators (same as Esc / B)
    function overlayBack() {
        if (mode === "setup") leaveSetup()
        else if (mode === "browse") browseCancel()
        else if (mode === "page") leavePage()
        else if (mode === "emulators") leaveEmus()
        else if (mode === "controls") leaveControls()
    }

    function emuKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape || k === Qt.Key_B) { leaveEmus(); return }
        if (k === Qt.Key_Up) emuList.move(-1)
        else if (k === Qt.Key_Down) emuList.move(1)
        else if (isEnter(k) || k === Qt.Key_Space) emuActivate(emuList.currentIndex)
    }
    function emuActivate(i) {
        var r = emuList.model[i]
        if (!r) return
        if (r.kind === "emu") { backend.cycleEmulator(r.id); refreshEmus(true) }
        else if (r.kind === "install" || r.kind === "app") backend.installEmulators()
        else if (r.kind === "bios") openImport("emus", "bios")
        else if (r.kind === "controls") openControls("emulators")
        else if (r.kind === "back") leaveEmus()
    }

    function browseCancel() {
        if (browseTarget.kind === "import" || browseTarget.kind === "biospack") mode = "import"
        else if (browseTarget.kind === "importfolder" || (browseTarget.kind === "winfile" && browseTarget.wizard)) openPage("addgames")
        else if (browseTarget.kind === "winfile") { mode = "library"; buildLists() }
        else if (browseTarget.kind === "wincover") openPage("winform")
        else if (browseTarget.kind === "gamecover") openPage("coverpick")
        else mode = "setup"
    }
    function browseKey(e) {
        var k = e.key
        if (k === Qt.Key_Escape || k === Qt.Key_B) { browseCancel(); return }
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
        else if (r.kind === "back") browseCancel()
        else if (r.kind === "up") loadDir(browseData.parent)
        else if (r.kind === "file" && enter) {
            if (browseTarget.kind === "winfile") handleAction(backend.winPicked(r.path))
            else if (browseTarget.kind === "gamecover") handleAction(backend.coverFromFile(browseTarget.gid, r.path))
            else if (browseTarget.kind === "biospack") { backend.startImportScan(r.path); mode = "import" }
            else if (browseTarget.kind === "introfile") { backend.introPicked(r.path); refreshSetup(true); mode = "setup" }
            else handleAction(backend.winPickedCover(r.path))
        }
        else if (r.kind === "nocover" && enter) handleAction(backend.winPickedCover(""))
        else if (r.kind === "use" && enter) {
            if (browseTarget.kind === "importfolder") { importReturn = "page"; importScreen.open("games"); backend.startImportScan(browseData.path); mode = "import" }
            else if (browseTarget.kind === "import") { backend.startImportScan(browseData.path); mode = "import" }
            else {
                if (browseTarget.kind === "system") backend.setSystemFolder(browseTarget.id, browseData.path)
                else if (browseTarget.kind === "recdir") backend.setRecDir(browseData.path)
                else backend.addSteamLibrary(browseData.path)
                refreshSetup(true)
                mode = "setup"
            }
        }
    }

    FocusScope {
        id: root
        anchors.fill: parent
        focus: true
        Keys.onPressed: function (e) {
            e.accepted = true
            if (e.key === Qt.Key_F11) { backend.toggleFullscreen(); return }
            if (e.key === Qt.Key_Q && (e.modifiers & Qt.ControlModifier)) { backend.quit(); return }
            if (inputDlg.visible) { inputDlg.handleKey(e); return }            // the password / typing box has the keyboard first
            if (win.mode === "intro") { backend.skipIntro(); return }          // any key skips the intro
            if (backend.running) {
                if (backend.runningCancelable && (e.key === Qt.Key_Escape || e.key === Qt.Key_B || e.key === Qt.Key_Backspace)) backend.cancelLaunch()
                return
            }
            var snd = win.keySound(e)
            if (win.mode === "library") libraryKey(e)
            else if (win.mode === "search") searchKey(e)
            else if (win.mode === "menu") menuKey(e)
            else if (win.mode === "sort") sortKey(e)
            else if (win.mode === "setup") setupKey(e)
            else if (win.mode === "emulators") emuKey(e)
            else if (win.mode === "controls") ctlKey(e)
            else if (win.mode === "update") updKey(e)
            else if (win.mode === "browse") browseKey(e)
            else if (win.mode === "page") pageKey(e)
            else if (win.mode === "import") importScreen.handleKey(e)
            else if (win.mode === "studio") studioScreen.handleKey(e)
            else if (win.mode === "wifi") wifiScreen.handleKey(e)
            if (snd !== "" && !backend.running) backend.playSound(snd)
        }

        WaveBackground {
            anchors.fill: parent
            active: !backend.running && win.visibility !== Window.Minimized
                    && (win.mode === "library" || win.mode === "search" || win.mode === "menu" || win.mode === "sort")
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
            onUpdateRequested: win.openUpdate("library")
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
        Rectangle {   // "Covers 12/80" while pictures download in the background
            id: coverPill
            visible: backend.coversBusy && win.mode === "library"
            anchors.right: parent.right
            anchors.rightMargin: 24 * win.u
            anchors.verticalCenter: hints.verticalCenter
            width: coverPillText.implicitWidth + 28 * win.u
            height: 32 * win.u
            radius: 16 * win.u
            color: "#1a1d2c"
            border.width: 1.5 * win.u
            border.color: Theme.red
            Text { id: coverPillText; anchors.centerIn: parent; text: backend.coverStatus; color: "#e6e8f2"
                   font.pixelSize: 16 * win.u; font.bold: true }
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
                onDeleteRequested: { win.detailIndex = 2; win.openDelete() }
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
                            MouseArea { anchors.fill: parent; onClicked: win.openPage("addgames") }
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
            FadeOnShow { target: parent }
            MouseArea { anchors.fill: parent }
            Column {
                anchors.centerIn: parent
                spacing: 18 * win.u
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: win.oskPurpose === "winname" ? "NAME THE GAME" : "SEARCH"
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
                        text: win.searchText === "" ? (win.oskPurpose === "winname" ? "Type the game's name..." : "Type to filter games...") : win.searchText + "\u258c"
                        color: win.searchText === "" ? Theme.faint : Theme.text
                        font.pixelSize: 40 * win.u
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: win.oskPurpose === "search"
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
            FadeOnShow { target: parent }
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
            FadeOnShow { target: parent }
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
            visible: win.mode === "setup" || win.mode === "browse" || win.mode === "emulators" || win.mode === "controls"
            FadeOnShow { target: parent }
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
                        text: win.mode === "emulators" ? "EMULATORS" : win.mode === "controls" ? "CONTROLS" : (win.mode === "browse" && win.browseTarget.files ? "CHOOSE A FILE" : backend.firstRun ? "WELCOME! LET'S SET UP YOUR GAMES" : "SETTINGS")
                        color: Theme.redBright
                        font.pixelSize: 42 * win.u
                        font.bold: true
                        font.letterSpacing: 4 * win.u
                    }
                    Text {
                        text: win.mode === "browse"
                              ? (win.browseTarget.files ? "Choose the file (folders open with Enter, Left = up).  Esc / B = cancel."
                                 : "Pick the folder, then choose \"Use this folder\".  Left = up, Esc / B = cancel.")
                              : win.mode === "emulators"
                              ? "Enter / A switches the emulator for a console, or runs the action.  Esc / B = back."
                              : win.mode === "controls"
                              ? "Keyboard keys inside each emulator.  Up/Down to scroll.  Esc / B = back."
                              : backend.firstRun
                              ? "Up/Down to choose, Enter / A to change.  Choose DONE / CONTINUE (or press Esc / B) to go to your games."
                              : "Up/Down to choose, Enter / A to change.  Delete / X clears a folder.  Esc / B = back."
                        color: "#e6e8f2"
                        font.pixelSize: 21 * win.u
                    }
                }
            }
            Rectangle {  // always-visible button for mouse / touch users (keyboard: Esc / B)
                id: setupBack
                z: 5
                anchors.top: parent.top
                anchors.topMargin: 34 * win.u
                anchors.right: parent.right
                anchors.rightMargin: 48 * win.u
                width: 300 * win.u; height: 60 * win.u; radius: 10 * win.u
                gradient: Gradient {
                    GradientStop { position: 0; color: "#ee2a34" } GradientStop { position: 1; color: "#a8121b" } }
                border.width: 2 * win.u; border.color: "white"
                Text {
                    anchors.centerIn: parent
                    text: win.mode === "setup" ? "DONE / CONTINUE" : (win.mode === "browse" ? "CANCEL" : "BACK")
                    color: "white"; font.pixelSize: 21 * win.u; font.bold: true; font.letterSpacing: 1 * win.u
                }
                MouseArea { anchors.fill: parent; onClicked: win.overlayBack() }
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
                id: ctlList
                u: win.u
                anchors.top: setupLine.bottom
                anchors.topMargin: 16 * win.u
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 20 * win.u
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width - 100 * win.u, 1500 * win.u)
                visible: win.mode === "controls"
                model: []
                onClicked: function (i) { if (ctlList.model[i].kind === "back") win.leaveControls() }
            }
            Connections {
                target: backend
                function onCoversChanged() {
                    if (win.mode === "setup") win.refreshSetup(true)
                }
                function onUpdateChanged() {
                    if (win.mode === "setup") win.refreshSetup(true)
                }
            }
            Timer {   // the emulator list shows live "installed" state while the installer runs in its own window
                interval: 3000
                repeat: true
                running: win.mode === "emulators"
                onTriggered: win.refreshEmus(true)
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

        // ---------------------------------------------------- the music Studio
        StudioScreen {
            id: studioScreen
            objectName: "studioScreen"
            anchors.fill: parent
            u: win.u
            studio: backend.studio
            visible: win.mode === "studio"
            onClosed: { win.mode = "library"; win.buildLists() }
        }
        Connections { target: backend; function onStudioRequested() { win.openStudio() } }

        // ---------------------------------------------------- WiFi
        WifiScreen {
            id: wifiScreen
            objectName: "wifiScreen"
            anchors.fill: parent
            u: win.u
            visible: win.mode === "wifi"
            onClosed: { if (win.wifiReturn === "setup") { win.refreshSetup(true); win.mode = "setup" } else { win.mode = "library"; win.buildLists() } }
        }

        // ---------------------------------------------------- overlay: add games
        ImportScreen {
            id: importScreen
            anchors.fill: parent
            u: win.u
            visible: win.mode === "import"
            onClosed: win.closeImport()
            onBrowseRequested: win.openBrowser({ kind: "import" }, backend.importBrowseStart())
            onPackRequested: win.openBrowser({ kind: "biospack", files: "archive" }, backend.importBrowseStart())
        }

        // ------------------------------------------------- overlay: help / fix my game / add Windows game
        Rectangle {
            anchors.fill: parent
            color: "#08090e"
            visible: win.mode === "page"
            FadeOnShow { target: parent }
            z: 20
            MouseArea { anchors.fill: parent }
            Item {
                id: pageHead
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 128 * win.u
                clip: true
                Image { anchors.fill: parent; source: Qt.resolvedUrl("../assets/banner.jpg"); fillMode: Image.PreserveAspectCrop
                        asynchronous: true; sourceSize.width: 1920 }
                Rectangle { anchors.fill: parent; color: "#88000000" }
                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 48 * win.u
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6 * win.u
                    Text { text: backend.pageTitle(win.pageName); color: Theme.redBright; font.pixelSize: 42 * win.u
                           font.bold: true; font.letterSpacing: 4 * win.u }
                    Text { text: backend.pageSub(win.pageName); color: "#e6e8f2"; font.pixelSize: 21 * win.u }
                }
            }
            Rectangle {
                z: 5
                anchors.top: parent.top
                anchors.topMargin: 34 * win.u
                anchors.right: parent.right
                anchors.rightMargin: 48 * win.u
                width: 300 * win.u; height: 60 * win.u; radius: 10 * win.u
                gradient: Gradient { GradientStop { position: 0; color: "#ee2a34" } GradientStop { position: 1; color: "#a8121b" } }
                border.width: 2 * win.u; border.color: "white"
                Text { anchors.centerIn: parent; text: win.pageName === "help" || win.pageName === "fix" ? "BACK" : "CANCEL"
                       color: "white"; font.pixelSize: 21 * win.u; font.bold: true }
                MouseArea { anchors.fill: parent; onClicked: win.leavePage() }
            }
            Rectangle { id: pageLine; anchors.top: pageHead.bottom; width: parent.width; height: 3 * win.u; color: Theme.red }
            MenuList {
                id: pageList
                u: win.u
                anchors.top: pageLine.bottom
                anchors.topMargin: 16 * win.u
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 20 * win.u
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width - 100 * win.u, 1500 * win.u)
                model: []
                onClicked: function (i) { win.pageActivateRow(i) }
            }
            Connections {
                target: backend
                function onPageChanged() { if (win.mode === "page") win.refreshPage(true) }
                function onPageRequested(name) {
                    if (name === "close") { if (win.mode === "page" || win.mode === "browse") win.leavePage() }
                    else win.openPage(name)
                }
                function onCoversChanged() { if (win.mode === "page" && win.pageName === "help") win.refreshPage(true) }
            }
        }

        FadeOnShow { target: importScreen }
        Connections {   // the games list fades in when you switch system / tab
            target: backend
            function onCurrentFilterChanged() { if (Theme.anim) gridFade.restart() }
        }
        NumberAnimation { id: gridFade; target: grid; property: "opacity"; from: 0.2; to: 1.0; duration: 200; easing.type: Easing.OutQuad }

        // ------------------------------------------------- the start-up intro (on top of everything)
        Intro {
            id: introScreen
            anchors.fill: parent
            z: 1000
            u: win.u
            visible: win.mode === "intro"
        }
        Connections {
            target: backend
            function onIntroChanged() {
                if (backend.introActive && win.mode !== "intro") { win.introBack = win.mode; win.mode = "intro" }
                else if (!backend.introActive && win.mode === "intro") {
                    win.mode = win.introBack
                    if (win.mode === "setup") win.refreshSetup(true)
                    root.forceActiveFocus()
                    Qt.callLater(win.ensureFocus)
                }
            }
        }

        // ------------------------------------------------- overlay: update CodeAque
        Rectangle {
            id: updScreen
            anchors.fill: parent
            color: "#08090e"
            visible: win.mode === "update"
            FadeOnShow { target: parent }
            z: 20
            MouseArea { anchors.fill: parent }
            readonly property string st: backend.updateState
            readonly property bool working: st === "downloading" || st === "verifying" || st === "installing" || st === "checking"
            Item {
                id: updHead
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 128 * win.u
                clip: true
                Image { anchors.fill: parent; source: Qt.resolvedUrl("../assets/banner.jpg"); fillMode: Image.PreserveAspectCrop
                        asynchronous: true; sourceSize.width: 1920 }
                Rectangle { anchors.fill: parent; color: "#88000000" }
                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 48 * win.u
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6 * win.u
                    Text { text: "UPDATE CODE"; color: Theme.redBright; font.pixelSize: 42 * win.u; font.bold: true
                           font.letterSpacing: 4 * win.u }
                    Text { text: "You have version " + backend.version + ". Your games, settings and favourites are never touched."
                           color: "#e6e8f2"; font.pixelSize: 21 * win.u }
                }
            }
            Rectangle { id: updLine; anchors.top: updHead.bottom; width: parent.width; height: 3 * win.u; color: Theme.red }
            Column {
                anchors.top: updLine.bottom
                anchors.topMargin: 24 * win.u
                anchors.bottom: updButtons.top
                anchors.bottomMargin: 20 * win.u
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width - 100 * win.u, 1300 * win.u)
                spacing: 16 * win.u
                Text {
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: backend.updateText
                    color: updScreen.st === "error" ? Theme.yellow : (updScreen.st === "done" ? Theme.green : "#e6e8f2")
                    font.pixelSize: 28 * win.u
                    font.bold: true
                }
                Rectangle {   // progress bar while downloading / installing
                    visible: updScreen.working && updScreen.st !== "checking"
                    width: parent.width; height: 14 * win.u; radius: 7 * win.u; color: "#1a1d2c"; clip: true
                    Rectangle {
                        id: updFill
                        width: backend.updateFraction >= 0 ? parent.width * backend.updateFraction : 180 * win.u
                        height: parent.height; radius: 7 * win.u; color: Theme.red
                        SequentialAnimation on x {
                            running: updScreen.visible && backend.updateFraction < 0 && updScreen.working
                            loops: Animation.Infinite
                            NumberAnimation { from: -180 * win.u; to: 1300 * win.u; duration: 1300; easing.type: Easing.InOutQuad }
                        }
                    }
                }
                Text {
                    visible: updScreen.st === "available" || updScreen.st === "downloading" || updScreen.st === "verifying"
                    text: "What's new in " + backend.updateVersion + "  (Up / Down to scroll)"
                    color: Theme.dim; font.pixelSize: 18 * win.u; font.letterSpacing: 1 * win.u
                }
                Flickable {
                    id: updNotes
                    visible: updScreen.st === "available" || updScreen.st === "downloading" || updScreen.st === "verifying"
                    width: parent.width
                    height: parent.height - y
                    clip: true
                    contentWidth: width
                    contentHeight: notesText.implicitHeight + 10 * win.u
                    boundsBehavior: Flickable.StopAtBounds
                    Text { id: notesText; width: updNotes.width; wrapMode: Text.Wrap; text: backend.updateNotes
                           color: "#c4c8da"; font.pixelSize: 19 * win.u; lineHeight: 1.15 }
                }
            }
            Row {
                id: updButtons
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 30 * win.u
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 20 * win.u
                Rectangle {
                    visible: !updScreen.working || updScreen.st === "checking" ? true : false
                    width: updPrimaryText.implicitWidth + 70 * win.u; height: 62 * win.u; radius: 10 * win.u
                    gradient: Gradient { GradientStop { position: 0; color: "#ee2a34" } GradientStop { position: 1; color: "#a8121b" } }
                    border.width: 3 * win.u; border.color: "white"
                    opacity: updScreen.st === "checking" ? 0.4 : 1
                    Text { id: updPrimaryText; anchors.centerIn: parent; color: "white"; font.pixelSize: 22 * win.u; font.bold: true
                           text: updScreen.st === "available" ? "INSTALL UPDATE  (Enter)"
                               : updScreen.st === "done" ? "RESTART CODE NOW  (Enter)"
                               : updScreen.st === "error" ? "TRY AGAIN  (Enter)"
                               : updScreen.st === "uptodate" ? "OK  (Enter)" : "PLEASE WAIT ..." }
                    MouseArea { anchors.fill: parent; onClicked: win.updPrimary() }
                }
                Rectangle {
                    visible: updScreen.st !== "verifying" && updScreen.st !== "installing"
                    width: updBackText.implicitWidth + 70 * win.u; height: 62 * win.u; radius: 10 * win.u
                    color: "#1a1d2c"; border.width: 2 * win.u; border.color: "#3a3f58"
                    Text { id: updBackText; anchors.centerIn: parent; color: "#e6e8f2"; font.pixelSize: 22 * win.u; font.bold: true
                           text: updScreen.st === "downloading" ? "CANCEL  (Esc)"
                               : updScreen.st === "done" ? "LATER  (Esc)"
                               : updScreen.st === "available" ? "NOT NOW  (Esc)" : "BACK  (Esc)" }
                    MouseArea { anchors.fill: parent; onClicked: { if (updScreen.st === "downloading") backend.cancelUpdate(); else win.leaveUpdate() } }
                }
            }
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
                    objectName: "runningStatus"
                    width: Math.min(implicitWidth, root.width - 160 * win.u)
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    text: backend.runningStatus !== "" ? backend.runningStatus : "Starting up... this screen returns when you quit the game."
                    color: Theme.dim
                    font.pixelSize: 26 * win.u
                }
                Rectangle {
                    objectName: "cancelLaunch"
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: backend.runningCancelable
                    width: 420 * win.u; height: 64 * win.u; radius: height / 2
                    color: "#26ffffff"; border.color: Theme.redBright; border.width: 2
                    Text { anchors.centerIn: parent; text: "Cancel - back to CodeAque  (Esc / B)"; color: "white"; font.pixelSize: 24 * win.u; font.bold: true }
                    MouseArea { anchors.fill: parent; onClicked: backend.cancelLaunch() }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: backend.runningHint !== ""
                    width: Math.min(implicitWidth, root.width - 160 * win.u)
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    text: backend.runningHint
                    color: Theme.yellow
                    font.pixelSize: 24 * win.u
                    font.bold: true
                }
            }
        }
    }

    // the password / typing dialog (administrator password for Quiet boot etc., new file names): above everything
    InputDialog {
        id: inputDlg
        objectName: "inputDialog"
        anchors.fill: parent
        u: win.u
        z: 100
    }

    // ---- keyboard focus: the key handler lives on `root`, so make sure `root` really owns the focus.
    // (Real desktops activate the window after it is shown, switch away with Alt-Tab, etc.)
    function ensureFocus() {
        if (!root.activeFocus) root.forceActiveFocus()
    }
    onActiveChanged: if (active) ensureFocus()
    onVisibleChanged: if (visible) ensureFocus()
    onVisibilityChanged: ensureFocus()
    onActiveFocusItemChanged: if (active && activeFocusItem !== root) ensureFocus()
    Timer {   // safety net: if anything ever steals the focus, take it back
        interval: 700; repeat: true; running: win.visible
        onTriggered: if (win.active) win.ensureFocus()
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
        Qt.callLater(win.ensureFocus)
        refreshCur()
    }
}
