// Native hands/eyes only. One JSON line in, one JSON line out. No model or browser logic.
import AppKit
import ApplicationServices
import ScreenCaptureKit
import ImageIO
import UniformTypeIdentifiers

struct Failure: Error {
    let message: String
    var paused = false
}

func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
}

func axFrame(_ element: AXUIElement) -> CGRect? {
    guard let p = attribute(element, kAXPositionAttribute), let s = attribute(element, kAXSizeAttribute),
          CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero, size = CGSize.zero
    guard AXValueGetValue(p as! AXValue, .cgPoint, &point), AXValueGetValue(s as! AXValue, .cgSize, &size) else { return nil }
    return CGRect(origin: point, size: size)
}

func sameFrame(_ a: CGRect, _ b: CGRect) -> Bool {
    abs(a.minX - b.minX) < 2 && abs(a.minY - b.minY) < 2 && abs(a.width - b.width) < 2 && abs(a.height - b.height) < 2
}

func secure(_ element: AXUIElement?) -> Bool {
    guard let element else { return false }
    return (attribute(element, kAXSubroleAttribute) as? String) == kAXSecureTextFieldSubrole
}

@MainActor
final class WindowController {
    var selected: CGWindowID?
    var pid: pid_t?
    var axWindow: AXUIElement?
    var captureToken: String?
    var capturedFrame: CGRect?

    func windows() async throws -> [SCWindow] {
        guard CGPreflightScreenCaptureAccess() else {
            throw Failure(message: "Allow Screen Recording for the terminal/app running this helper in System Settings, then restart it.")
        }
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        return content.windows.filter {
            $0.windowLayer == 0 && $0.frame.width >= 100 && $0.frame.height >= 100 && $0.owningApplication != nil
        }.sorted {
            let a = ($0.owningApplication?.applicationName ?? "") + ($0.title ?? "")
            let b = ($1.owningApplication?.applicationName ?? "") + ($1.title ?? "")
            return a.localizedCaseInsensitiveCompare(b) == .orderedAscending
        }
    }

    func current() async throws -> SCWindow {
        guard let selected, let pid else { throw Failure(message: "Select a window first.") }
        guard let window = try await windows().first(where: { $0.windowID == selected && $0.owningApplication?.processID == pid }) else {
            throw Failure(message: "Selected window closed, minimized, or is no longer available. Select it again.")
        }
        return window
    }

    func access() throws {
        guard AXIsProcessTrusted() else {
            throw Failure(message: "Allow Accessibility for the terminal/app running this helper in System Settings, then restart it.")
        }
    }

    func checkFocus(_ window: SCWindow) throws {
        try access()
        guard let pid, let axWindow,
              NSWorkspace.shared.frontmostApplication?.processIdentifier == pid else {
            captureToken = nil
            throw Failure(message: "Return to the selected window to resume.", paused: true)
        }
        let app = AXUIElementCreateApplication(pid)
        guard let focused = attribute(app, kAXFocusedWindowAttribute),
              CFGetTypeID(focused) == AXUIElementGetTypeID(), CFEqual(focused, axWindow),
              let frame = axFrame(axWindow), sameFrame(frame, window.frame) else {
            captureToken = nil
            throw Failure(message: "A different window or dialog is focused. Return to the selected window.", paused: true)
        }
    }

    func select(_ id: CGWindowID, _ processID: pid_t) async throws -> [String: Any] {
        try access()
        guard let window = try await windows().first(where: { $0.windowID == id && $0.owningApplication?.processID == processID }) else {
            throw Failure(message: "Window list changed; choose the window again.")
        }
        let app = AXUIElementCreateApplication(processID)
        guard let candidates = attribute(app, kAXWindowsAttribute) as? [AXUIElement] else {
            throw Failure(message: "This app does not expose its windows to Accessibility.")
        }
        let matches = candidates.filter { element in
            guard let frame = axFrame(element) else { return false }
            return sameFrame(frame, window.frame)
        }
        let titled = matches.filter { (attribute($0, kAXTitleAttribute) as? String) == window.title }
        guard let target = (titled.count == 1 ? titled.first : matches.count == 1 ? matches.first : nil) else {
            throw Failure(message: "Cannot identify this window uniquely. Move it away from other windows and select again.")
        }
        selected = id; pid = processID; axWindow = target
        capturedFrame = nil; captureToken = nil
        guard AXUIElementPerformAction(target, kAXRaiseAction as CFString) == .success,
              let running = NSRunningApplication(processIdentifier: processID), running.activate(options: []) else {
            throw Failure(message: "Could not bring the selected window forward.")
        }
        return ["ok": true]
    }

    func shot() async throws -> [String: Any] {
        let window = try await current()
        try checkFocus(window)
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let rect = filter.contentRect
        let scale = min(1400 / rect.width, 1400 / rect.height)
        let width = Int((rect.width * scale).rounded()), height = Int((rect.height * scale).rounded())
        guard width >= 280, height >= 280 else {
            throw Failure(message: "Window is too narrow for Jev's image limits. Resize it and restart.")
        }
        let config = SCStreamConfiguration()
        config.width = width; config.height = height
        config.showsCursor = false
        config.ignoreShadowsSingleWindow = true
        config.captureResolution = .nominal
        let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
        let after = try await current()
        try checkFocus(after)
        guard sameFrame(window.frame, after.frame) else {
            throw Failure(message: "Window moved while taking its picture. Taking a new one.", paused: true)
        }
        // No shadows: normalized image coordinates correspond to the actual window frame.
        guard abs(rect.width - window.frame.width) < 2, abs(rect.height - window.frame.height) < 2 else {
            throw Failure(message: "Capture content and window bounds differ; this window is not supported safely.")
        }
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else {
            throw Failure(message: "Could not encode screenshot.")
        }
        CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.78] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw Failure(message: "Could not encode screenshot.") }
        let token = UUID().uuidString
        captureToken = token; capturedFrame = window.frame
        return ["ok": true, "width": image.width, "height": image.height,
                "data": (data as Data).base64EncodedString(), "token": token]
    }

    func hit(_ point: CGPoint) throws -> AXUIElement {
        var element: AXUIElement?
        guard AXUIElementCopyElementAtPosition(AXUIElementCreateSystemWide(), Float(point.x), Float(point.y), &element) == .success,
              let element else { throw Failure(message: "Cannot inspect the target control; no input sent.") }
        var owner: pid_t = 0
        AXUIElementGetPid(element, &owner)
        guard owner == pid else { throw Failure(message: "Another app covers the target point.", paused: true) }
        // A popover or another window from the same app must not receive the selected window's click.
        if let ownerWindow = attribute(element, kAXWindowAttribute), let axWindow, !CFEqual(ownerWindow, axWindow) {
            throw Failure(message: "Another window covers the target point.", paused: true)
        }
        return element
    }

    func guardTarget(_ element: AXUIElement) throws {
        var item: AXUIElement? = element
        let blocked = #"(?i)\b(pay|payment|purchase|buy now|place order|checkout|subscribe|delete|remove|send|transfer|allow|authorize|grant|sign in|log in)\b"#
        for _ in 0..<5 {
            guard let current = item else { break }
            if secure(current) { throw Failure(message: "Password control: finish this step yourself.") }
            let role = attribute(current, kAXRoleAttribute) as? String ?? ""
            if [kAXButtonRole, "AXLink", kAXCheckBoxRole].contains(role) {
                let label = [kAXTitleAttribute, kAXDescriptionAttribute, kAXHelpAttribute]
                    .compactMap { attribute(current, $0) as? String }.joined(separator: " ")
                if label.range(of: blocked, options: .regularExpression) != nil {
                    throw Failure(message: "This control needs you to act: \(label.prefix(100))")
                }
            }
            guard let parent = attribute(current, kAXParentAttribute), CFGetTypeID(parent) == AXUIElementGetTypeID() else { break }
            item = (parent as! AXUIElement)
        }
    }

    func act(_ plan: [String: Any], token: String) async throws -> [String: Any] {
        guard let expected = captureToken, token == expected, let frame = capturedFrame else {
            throw Failure(message: "Picture is stale; taking a new one.", paused: true)
        }
        captureToken = nil  // each screenshot authorizes at most one action
        let window = try await current()
        try checkFocus(window)
        guard sameFrame(frame, window.frame) else {
            throw Failure(message: "Window moved or resized; taking a new picture.", paused: true)
        }
        guard let pid, let action = plan["action"] as? String else { throw Failure(message: "Invalid action.") }
        let pointed = action == "click" || action == "type" || action.hasPrefix("scroll_")
        var point = CGPoint.zero
        if pointed {
            guard let x = plan["x"] as? Double, let y = plan["y"] as? Double,
                  x.isFinite, y.isFinite, x > 0, x < 1, y > 0, y < 1 else { throw Failure(message: "Invalid target coordinates.") }
            point = CGPoint(x: frame.minX + x * frame.width, y: frame.minY + y * frame.height)
            try guardTarget(hit(point))
        }
        if action == "click" || action == "type" {
            guard let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
                  let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
                throw Failure(message: "Could not create click.")
            }
            down.postToPid(pid); up.postToPid(pid)
        }
        if action == "type" {
            try await Task.sleep(for: .milliseconds(150))
            try checkFocus(try await current())
            let app = AXUIElementCreateApplication(pid)
            guard let raw = attribute(app, kAXFocusedUIElementAttribute), CFGetTypeID(raw) == AXUIElementGetTypeID() else {
                throw Failure(message: "No focused text field; no text sent.")
            }
            let field = raw as! AXUIElement
            try guardTarget(field)
            let role = attribute(field, kAXRoleAttribute) as? String ?? ""
            guard [kAXTextFieldRole, kAXTextAreaRole, kAXComboBoxRole].contains(role),
                  let text = plan["text"] as? String, !text.isEmpty, text.utf16.count <= 2000 else {
                throw Failure(message: "Target is not a supported text field, or text is invalid.")
            }
            // Insert exact supplied text; do not overwrite unrelated existing content.
            let characters = Array(text.utf16)
            for down in [true, false] {
                guard let event = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: down) else { throw Failure(message: "Could not create text input.") }
                characters.withUnsafeBufferPointer { event.keyboardSetUnicodeString(stringLength: characters.count, unicodeString: $0.baseAddress) }
                event.postToPid(pid)
            }
        } else if action.hasPrefix("scroll_") {
            let vertical: Int32 = action == "scroll_down" ? -500 : action == "scroll_up" ? 500 : 0
            let horizontal: Int32 = action == "scroll_right" ? -500 : action == "scroll_left" ? 500 : 0
            guard vertical != 0 || horizontal != 0,
                  let event = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 2, wheel1: vertical, wheel2: horizontal, wheel3: 0) else {
                throw Failure(message: "Invalid scroll action.")
            }
            event.location = point
            event.postToPid(pid)
        } else if action == "enter" || action == "escape" {
            let app = AXUIElementCreateApplication(pid)
            if let raw = attribute(app, kAXFocusedUIElementAttribute), CFGetTypeID(raw) == AXUIElementGetTypeID() {
                try guardTarget(raw as! AXUIElement)
            }
            for down in [true, false] {
                guard let event = CGEvent(keyboardEventSource: nil, virtualKey: action == "enter" ? 36 : 53, keyDown: down) else {
                    throw Failure(message: "Could not create key input.")
                }
                event.postToPid(pid)
            }
        } else if action != "click" && action != "type" {
            throw Failure(message: "Unsupported action.")
        }
        return ["ok": true, "result": "input delivered; inspect next screenshot to verify"]
    }

    func handle(_ request: [String: Any]) async throws -> [String: Any] {
        switch request["cmd"] as? String {
        case "list":
            return ["ok": true, "windows": try await windows().map {
                ["id": $0.windowID, "pid": $0.owningApplication!.processID,
                 "app": $0.owningApplication!.applicationName, "title": $0.title ?? ""] as [String: Any]
            }]
        case "select":
            guard let id = request["window"] as? UInt32, let pid = request["pid"] as? Int32 else { throw Failure(message: "Invalid window selection.") }
            return try await select(id, pid)
        case "shot": return try await shot()
        case "act":
            guard let plan = request["plan"] as? [String: Any], let token = request["token"] as? String else { throw Failure(message: "Invalid action request.") }
            return try await act(plan, token: token)
        default: throw Failure(message: "Unknown command.")
        }
    }
}

@main
struct Main {
    @MainActor static func main() async {
        let controller = WindowController()
        while let line = readLine() {
            let reply: [String: Any]
            do {
                guard let data = line.data(using: .utf8), let request = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    throw Failure(message: "Invalid JSON request.")
                }
                reply = try await controller.handle(request)
            } catch let failure as Failure {
                reply = ["ok": false, "error": failure.message, "paused": failure.paused]
            } catch {
                reply = ["ok": false, "error": error.localizedDescription]
            }
            if let data = try? JSONSerialization.data(withJSONObject: reply, options: [.sortedKeys]),
               let json = String(data: data, encoding: .utf8) { print(json); fflush(stdout) }
        }
    }
}
