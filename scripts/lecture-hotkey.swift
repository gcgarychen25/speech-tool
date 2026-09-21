import Carbon
import Cocoa

/// Global Control-Option-L listener. Does not need Accessibility permission.
/// LaunchAgent: com.speechtool.lecture-hotkey

private func scriptPath() -> String {
    if CommandLine.arguments.count > 1 {
        return CommandLine.arguments[1]
    }
    return (CommandLine.arguments[0] as NSString)
        .deletingLastPathComponent + "/start-lecture.sh"
}

private func notify(_ title: String, _ body: String) {
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
    proc.arguments = ["-e", "display notification \"\(body)\" with title \"\(title)\""]
    try? proc.run()
}

private func runStartLecture() {
    let path = scriptPath()
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/bin/zsh")
    proc.arguments = [path]
    proc.standardOutput = FileHandle.nullDevice
    proc.standardError = FileHandle.nullDevice
    do {
        try proc.run()
    } catch {
        notify("Speech Tool", "Could not run start-lecture.sh")
    }
}

private func hotKeyHandler(
    _ nextHandler: EventHandlerCallRef?,
    _ event: EventRef?,
    _ userData: UnsafeMutableRawPointer?
) -> OSStatus {
    runStartLecture()
    return noErr
}

private func fourCharCode(_ text: String) -> OSType {
    var value: OSType = 0
    for byte in text.utf8 {
        value = (value << 8) + OSType(byte)
    }
    return value
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

var eventType = EventTypeSpec(
    eventClass: OSType(kEventClassKeyboard),
    eventKind: UInt32(kEventHotKeyPressed)
)
InstallEventHandler(
    GetApplicationEventTarget(),
    hotKeyHandler,
    1,
    &eventType,
    nil,
    nil
)

var hotKeyRef: EventHotKeyRef?
let hotKeyID = EventHotKeyID(signature: fourCharCode("SPLT"), id: 1)
let status = RegisterEventHotKey(
    UInt32(kVK_ANSI_L),
    UInt32(controlKey | optionKey),
    hotKeyID,
    GetApplicationEventTarget(),
    0,
    &hotKeyRef
)
if status != noErr {
    notify("Speech Tool hotkey failed", "Control-Option-L is already used by another app.")
}

app.run()
