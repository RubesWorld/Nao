// Menu bar toggle for the Mini's two display modes.
//
// Wraps the same ~/bin/desk-mode.sh and ~/bin/remote-mode.sh that back the
// `deskmode` / `remotemode` shell commands — this is a second front door to
// them, not a reimplementation. Read those scripts for why the resolutions
// are what they are.

import Cocoa

let displayID = "143821D7-3209-4C2A-9E49-97A60D350718"
let displayplacer = "/opt/homebrew/bin/displayplacer"

struct Mode {
    let label: String       // shown in the menu bar
    let detail: String      // shown in the menu
    let resolution: String  // what displayplacer reports when this mode is live
    let command: String
}

let modes = [
    Mode(label: "Desk",
         detail: "Desk — 3440×1440 @ 50Hz",
         resolution: "3440x1440",
         command: "/opt/homebrew/bin/deskmode"),
    Mode(label: "Remote",
         detail: "Remote — 1440×900 @ 60Hz",
         resolution: "1440x900",
         command: "/opt/homebrew/bin/remotemode"),
]

@discardableResult
func run(_ path: String, _ args: [String] = []) -> String {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: path)
    task.arguments = args
    let out = Pipe()
    task.standardOutput = out
    task.standardError = Pipe()
    guard (try? task.run()) != nil else { return "" }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    task.waitUntilExit()
    return String(data: data, encoding: .utf8) ?? ""
}

/// The display's live resolution, e.g. "1440x900". nil if displayplacer can't
/// see the display at all (unplugged, or Homebrew moved).
func currentResolution() -> String? {
    let listing = run(displayplacer, ["list"])
    guard let idEnd = listing.range(of: displayID)?.upperBound else { return nil }
    // Per-screen block prints "Resolution:" before the "mode N: res:..." list,
    // so the first match after the id is the live one.
    for line in listing[idEnd...].split(separator: "\n") {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        if trimmed.hasPrefix("Resolution:") {
            return String(trimmed.dropFirst("Resolution:".count)).trimmingCharacters(in: .whitespaces)
        }
    }
    return nil
}

final class Delegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var statusItem: NSStatusItem!

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = NSImage(systemSymbolName: "display",
                                           accessibilityDescription: "Display mode")
        statusItem.button?.imagePosition = .imageLeading

        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu

        refresh()
    }

    // Rebuilt on every open so the checkmark reflects reality even when the
    // resolution was changed from the terminal or System Settings.
    func menuNeedsUpdate(_ menu: NSMenu) {
        let live = currentResolution()
        menu.removeAllItems()

        for (index, mode) in modes.enumerated() {
            let item = NSMenuItem(title: mode.detail,
                                  action: #selector(switchMode(_:)),
                                  keyEquivalent: String(index + 1))
            item.target = self
            item.tag = index
            item.state = (live == mode.resolution) ? .on : .off
            menu.addItem(item)
        }

        menu.addItem(.separator())
        menu.addItem(withTitle: live.map { "Current: \($0)" } ?? "Display not found",
                     action: nil, keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
    }

    @objc private func switchMode(_ sender: NSMenuItem) {
        let mode = modes[sender.tag]
        DispatchQueue.global(qos: .userInitiated).async {
            run(mode.command)
            // The mode switch blanks the display for a beat; let it settle
            // before reading back what actually took effect.
            Thread.sleep(forTimeInterval: 1.5)
            DispatchQueue.main.async { self.refresh() }
        }
    }

    private func refresh() {
        let live = currentResolution()
        let match = modes.first { $0.resolution == live }
        statusItem.button?.title = match.map { " \($0.label)" } ?? ""
        statusItem.button?.toolTip = live.map { "Display: \($0)" } ?? "Display not found"
    }
}

let app = NSApplication.shared
let delegate = Delegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
