// The native shell of Mac Cleaner.app: one window showing the dashboard.
//
// It starts the bundled Python engine (Contents/Resources/python + app) on a
// free localhost port, waits for it, and shows it in a WKWebView. When the
// engine exits with code 75 it is handing over to the updater, which swaps
// the app bundle and reopens it, so the app quits quietly.
import Cocoa
import WebKit

let updateExitCode: Int32 = 75

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var engine: Process?
    var port = 0
    var quitting = false
    var log: FileHandle?

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        startEngine()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        if let e = engine, e.isRunning { e.terminate() }
    }

    // MARK: window & menu

    func buildWindow() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 13.3, *) { webView.isInspectable = true }

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Mac Cleaner"
        window.minSize = NSSize(width: 900, height: 600)
        window.contentView = webView
        window.center()
        window.setFrameAutosaveName("MainWindow")
        window.makeKeyAndOrderFront(nil)
        showMessage("Starting…", detail: "")
        NSApp.activate(ignoringOtherApps: true)
    }

    func buildMenu() {
        let main = NSMenu()

        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Mac Cleaner", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(withTitle: "Check for Updates…", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Mac Cleaner", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = appMenu.addItem(withTitle: "Hide Others",
                                         action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Mac Cleaner", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        addSubmenu(appMenu, to: main, title: "Mac Cleaner")

        // Without an Edit menu, copy/paste shortcuts don't reach the web view.
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        addSubmenu(edit, to: main, title: "Edit")

        let view = NSMenu(title: "View")
        view.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r")
        addSubmenu(view, to: main, title: "View")

        let win = NSMenu(title: "Window")
        win.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        addSubmenu(win, to: main, title: "Window")
        NSApp.windowsMenu = win

        NSApp.mainMenu = main
    }

    func addSubmenu(_ menu: NSMenu, to main: NSMenu, title: String) {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.submenu = menu
        main.addItem(item)
    }

    @objc func showAbout() {
        window.makeKeyAndOrderFront(nil)
        webView.evaluateJavaScript("typeof showAbout === 'function' && showAbout()", completionHandler: nil)
    }

    @objc func reload() {
        if port > 0 { load() }
    }

    func showMessage(_ title: String, detail: String) {
        let html = """
        <html><body style="font:14px -apple-system;display:flex;height:100vh;margin:0;align-items:center;
        justify-content:center;flex-direction:column;color:#52514e;background:#f9f9f7">
        <h2 style="color:#0b0b0b;font-weight:600">\(title)</h2><p style="max-width:520px;text-align:center">\(detail)</p>
        <style>@media (prefers-color-scheme: dark){body{background:#0d0d0d!important;color:#c3c2b7!important}
        h2{color:#f0efec!important}}</style></body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    // MARK: engine

    func logPath() -> URL {
        let dir = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("Mac Cleaner.log")
    }

    func startEngine() {
        guard let res = Bundle.main.resourceURL else { return }
        let python = res.appendingPathComponent("python/bin/python3")
        port = freePort()

        let logURL = logPath()
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        log = try? FileHandle(forWritingTo: logURL)
        _ = log?.seekToEndOfFile()

        let p = Process()
        p.executableURL = python
        p.arguments = ["-m", "macclean", "serve", "--no-browser", "--port", String(port)]
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = res.appendingPathComponent("app").path
        env["PYTHONHOME"] = res.appendingPathComponent("python").path
        env["PYTHONDONTWRITEBYTECODE"] = "1"  // never write into the (signed) bundle
        env["PYTHONNOUSERSITE"] = "1"
        env["MACCLEAN_APP_BUNDLE"] = Bundle.main.bundlePath
        p.environment = env
        p.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
        if let log = log {
            p.standardOutput = log
            p.standardError = log
        }
        p.terminationHandler = { proc in
            DispatchQueue.main.async { self.engineExited(proc.terminationStatus) }
        }
        do {
            try p.run()
            engine = p
            waitForEngine(attempt: 0)
        } catch {
            fail("Mac Cleaner couldn't start its engine: \(error.localizedDescription)")
        }
    }

    func waitForEngine(attempt: Int) {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/status") else { return }
        var req = URLRequest(url: url)
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { _, response, _ in
            DispatchQueue.main.async {
                if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                    self.load()
                } else if attempt < 150, self.engine?.isRunning == true {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.waitForEngine(attempt: attempt + 1) }
                } else if self.engine?.isRunning == true {
                    self.fail("Mac Cleaner's engine didn't start in time.")
                }
            }
        }.resume()
    }

    func load() {
        if let url = URL(string: "http://127.0.0.1:\(port)/") {
            webView.load(URLRequest(url: url))
        }
    }

    func engineExited(_ status: Int32) {
        if quitting { return }
        if status == updateExitCode || status == 0 {
            // 75: the updater takes over and reopens the app. 0: Quit from the dashboard.
            quitting = true
            NSApp.terminate(nil)
            return
        }
        fail("Mac Cleaner's engine stopped unexpectedly (code \(status)).")
    }

    func fail(_ message: String) {
        showMessage("Something went wrong", detail: message + " Details are in ~/Library/Logs/Mac Cleaner.log")
        let alert = NSAlert()
        alert.messageText = "Mac Cleaner ran into a problem"
        alert.informativeText = message
        alert.addButton(withTitle: "Restart")
        alert.addButton(withTitle: "Show Log")
        alert.addButton(withTitle: "Quit")
        switch alert.runModal() {
        case .alertFirstButtonReturn:
            startEngine()
        case .alertSecondButtonReturn:
            NSWorkspace.shared.activateFileViewerSelecting([logPath()])
        default:
            quitting = true
            NSApp.terminate(nil)
        }
    }

    func freePort() -> Int {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return 8765 }
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = 0
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        let bound = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, len) }
        }
        guard bound == 0 else { return 8765 }
        _ = withUnsafeMutablePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &len) }
        }
        return Int(UInt16(bigEndian: addr.sin_port))
    }

    // MARK: links

    // Anything that isn't the dashboard itself (GitHub links etc.) opens in the browser.
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = navigationAction.request.url, let scheme = url.scheme,
           scheme == "http" || scheme == "https", url.host != "127.0.0.1" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url { NSWorkspace.shared.open(url) }
        return nil
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
