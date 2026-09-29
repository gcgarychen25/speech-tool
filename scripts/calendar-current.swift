import EventKit
import Foundation

/// Print the Calendar event overlapping "now" as JSON on stdout.
/// Local-only; no network. Used by Speech Tool for lecture course autofill.
///
/// Build: swiftc -O -o scripts/calendar-current scripts/calendar-current.swift

struct EventOut: Codable {
    var title: String
    var start: String
    var end: String
    var all_day: Bool
    var calendar: String
}

struct SuggestOut: Codable {
    var ok: Bool
    var authorized: Bool
    var course: String?
    var title: String?
    var event_title: String?
    var events: [EventOut]
    var detail: String?
}

let iso: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f
}()

let isoBasic: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime]
    return f
}()

func format(_ date: Date) -> String {
    iso.string(from: date)
}

func emit(_ value: SuggestOut) {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    if let data = try? encoder.encode(value), let text = String(data: data, encoding: .utf8) {
        print(text)
    } else {
        print("{\"ok\":false,\"authorized\":false,\"events\":[],\"detail\":\"encode_failed\"}")
    }
}

func pickEvent(_ events: [EKEvent]) -> EKEvent? {
    let named = events.filter { event in
        !(event.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
    let timed = named.filter { !$0.isAllDay }
    let pool = timed.isEmpty ? named : timed
    return pool.max { a, b in
        let aLen = a.endDate.timeIntervalSince(a.startDate)
        let bLen = b.endDate.timeIntervalSince(b.startDate)
        if aLen != bLen { return aLen < bLen }
        return (a.title ?? "").count < (b.title ?? "").count
    }
}

let store = EKEventStore()
let group = DispatchGroup()
var accessGranted = false
var accessError: String?

group.enter()
if #available(macOS 14.0, *) {
    store.requestFullAccessToEvents { granted, error in
        accessGranted = granted
        accessError = error?.localizedDescription
        group.leave()
    }
} else {
    store.requestAccess(to: .event) { granted, error in
        accessGranted = granted
        accessError = error?.localizedDescription
        group.leave()
    }
}

_ = group.wait(timeout: .now() + 8)

if !accessGranted {
    emit(SuggestOut(
        ok: false,
        authorized: false,
        course: nil,
        title: nil,
        event_title: nil,
        events: [],
        detail: accessError ?? "calendar_access_denied"
    ))
    exit(0)
}

let now = Date()
let windowStart = now.addingTimeInterval(-36 * 3600)
let windowEnd = now.addingTimeInterval(36 * 3600)
let predicate = store.predicateForEvents(withStart: windowStart, end: windowEnd, calendars: nil)
let matched = store.events(matching: predicate).filter { event in
    event.startDate <= now && event.endDate >= now
}

var events: [EventOut] = matched.map { event in
    EventOut(
        title: event.title ?? "",
        start: format(event.startDate),
        end: format(event.endDate),
        all_day: event.isAllDay,
        calendar: event.calendar?.title ?? ""
    )
}
events.sort { $0.start < $1.start }

let chosen = pickEvent(matched)
let course = chosen?.title?.trimmingCharacters(in: .whitespacesAndNewlines)
let stamp: String = {
    let f = DateFormatter()
    f.locale = .current
    f.dateFormat = "MMM d, h:mm a"
    return f.string(from: now)
}()

emit(SuggestOut(
    ok: true,
    authorized: true,
    course: course,
    title: stamp,
    event_title: course,
    events: events,
    detail: course == nil ? "no_overlapping_event" : nil
))
