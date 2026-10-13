import Foundation

private var failed = false

private func check(_ condition: @autoclosure () -> Bool, _ name: String) {
    if condition() {
        print("PASS: \(name)")
    } else {
        print("FAIL: \(name)")
        failed = true
    }
}

private func read(_ directory: URL, _ name: String) -> DocumentContent? {
    do {
        return try DocumentText.read(url: directory.appendingPathComponent(name))
    } catch {
        print("FAIL: \(name) の読み込み（\(error.localizedDescription)）")
        failed = true
        return nil
    }
}

guard CommandLine.arguments.count == 2 else {
    print("FAIL: 見本フォルダを1つ指定してください")
    exit(1)
}

let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)

if let meeting = read(directory, "doc-meeting.docx") {
    check(meeting.kind == "docx", "Word の種類")
    check(meeting.lines.contains("場所 架空市役所 第1会議室"), "Word の本文")
}

if let table = read(directory, "doc-table.docx") {
    check(table.tables.first?.count == 4, "Word の表の行数")
    check(table.tables.first?[1] == ["10月22日", "木", "架空の定例会", "10:00〜12:00", "議場"], "Word の表の内容")
}

if let table = read(directory, "doc-table.xlsx") {
    check(table.kind == "xlsx", "Excel の種類")
    check(table.tables.first?.count == 4, "Excel の表の行数")
    check(table.tables.first?[1] == ["2026-10-22", "木", "架空の定例会", "10:00〜12:00", "議場"], "Excel の表の内容と日付")
}

if let textPDF = read(directory, "doc-text.pdf") {
    check(textPDF.needsOCR == false, "文字入り PDF の OCR 判定")
    check(textPDF.lines.joined().contains("架空検討委員会"), "文字入り PDF の本文")
}

if let scanPDF = read(directory, "doc-scan.pdf") {
    check(scanPDF.needsOCR == true, "画像 PDF の OCR 判定")
    check(scanPDF.lines.isEmpty, "画像 PDF の行は空")
}

do {
    _ = try DocumentText.read(url: directory.appendingPathComponent("doc-bomb.docx"))
    check(false, "展開すると巨大な Word は読まない")
} catch DocumentTextError.tooLarge {
    check(true, "展開すると巨大な Word は読まない")
} catch {
    print("FAIL: 展開すると巨大な Word は読まない（\(error.localizedDescription)）")
    failed = true
}

if let wide = read(directory, "doc-wide.xlsx") {
    check(wide.tables.first?.first == ["架空の行事"], "極端に右の列は読まず、落ちない")
}

let unsupportedURL = FileManager.default.temporaryDirectory
    .appendingPathComponent("document-text-check-\(UUID().uuidString).doc")
do {
    try Data().write(to: unsupportedURL)
    _ = try DocumentText.read(url: unsupportedURL)
    check(false, "未対応形式")
} catch DocumentTextError.unsupported {
    check(true, "未対応形式")
} catch {
    print("FAIL: 未対応形式（\(error.localizedDescription)）")
    failed = true
}

exit(failed ? 1 : 0)
