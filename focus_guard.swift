import AppKit
import ApplicationServices
import Foundation

func focused(_ attr: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard let pid = NSWorkspace.shared.frontmostApplication?.processIdentifier else { return nil }
    let err = AXUIElementCopyAttributeValue(AXUIElementCreateApplication(pid), attr as CFString, &value)
    return err == .success ? value : nil
}
let args = Array(CommandLine.arguments.dropFirst())
guard args.count >= 2 else { fputs("usage: focus_guard REPORT COMMAND [ARGS...]\n", stderr); exit(2) }
guard let pid = NSWorkspace.shared.frontmostApplication?.processIdentifier,
      let element = focused(kAXFocusedUIElementAttribute) else {
    fputs("Cannot observe keyboard focus; no command executed\n", stderr); exit(2)
}
if NSWorkspace.shared.frontmostApplication?.bundleIdentifier == "com.apple.Stickies" {
    fputs("Stickies is foreground; no command executed\n", stderr); exit(2)
}
func description(_ item: CFTypeRef) -> [String: String] {
    let ax = item as! AXUIElement
    var output: [String: String] = [:]
    for key in [kAXRoleAttribute, kAXSubroleAttribute, kAXIdentifierAttribute] {
        var value: CFTypeRef?
        if AXUIElementCopyAttributeValue(ax, key as CFString, &value) == .success, let value = value as? String { output[key] = value }
    }
    return output
}
let baselineDescription = description(element)
var changedDescriptions: [[String: String]] = []
let clipboard = NSPasteboard.general.changeCount
var samples = 0, appChanges = 0, focusChanges = 0, readFailures = 0, clipboardChanges = 0
func sample() {
    samples += 1
    if NSWorkspace.shared.frontmostApplication?.processIdentifier != pid { appChanges += 1 }
    if let current = focused(kAXFocusedUIElementAttribute) {
        if !CFEqual(current, element) { focusChanges += 1; if changedDescriptions.count < 20 { changedDescriptions.append(description(current)) } }
    } else { readFailures += 1 }
    if NSPasteboard.general.changeCount != clipboard { clipboardChanges += 1 }
}
let process = Process()
process.executableURL = URL(fileURLWithPath: args[1])
process.arguments = Array(args.dropFirst(2))
do { try process.run() } catch { fputs("Command failed to start\n", stderr); exit(2) }
repeat {
    sample()
    RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.02))
} while process.isRunning
process.waitUntilExit()
sample()
let ok = appChanges == 0 && focusChanges == 0 && readFailures == 0 && clipboardChanges == 0 && process.terminationStatus == 0
let result: [String: Any] = ["passed": ok, "samples": samples, "interval_ms": 20,
    "foreground_changes": appChanges, "focused_element_changes": focusChanges,
    "focus_read_failures": readFailures, "clipboard_change_count_changes": clipboardChanges,
    "command_exit": process.terminationStatus, "baseline_focus": baselineDescription, "changed_focus": changedDescriptions]
let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
try data.write(to: URL(fileURLWithPath: args[0]), options: .atomic)
print(String(data: data, encoding: .utf8)!)
exit(ok ? 0 : 1)
