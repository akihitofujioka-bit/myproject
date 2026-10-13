import Foundation
import PDFKit

struct DocumentContent {
    let kind: String
    let lines: [String]
    let tables: [[[String]]]
    var needsOCR: Bool
}

enum DocumentTextError: LocalizedError {
    case unsupported
    case broken
    case locked
    case empty

    var errorDescription: String? {
        switch self {
        case .unsupported:
            return "この形式は読めません（.docx・.xlsx・.pdf だけ読めます）"
        case .broken:
            return "ファイルが壊れているため読めませんでした"
        case .locked:
            return "パスワードが付いているため読めませんでした"
        case .empty:
            return "文字が見つかりませんでした"
        }
    }
}

enum DocumentText {
    static func read(url: URL) throws -> DocumentContent {
        switch url.pathExtension.lowercased() {
        case "docx":
            return try readDocx(url: url)
        case "xlsx":
            return try readXlsx(url: url)
        case "pdf":
            return try readPDF(url: url)
        default:
            throw DocumentTextError.unsupported
        }
    }

    private static func readDocx(url: URL) throws -> DocumentContent {
        let archive = try openOfficeArchive(url: url)
        guard let document = archive.entries["word/document.xml"] else {
            throw DocumentTextError.broken
        }
        let parser = WordParser()
        guard parser.parse(document) else { throw DocumentTextError.broken }
        guard hasText(lines: parser.lines, tables: parser.tables) else {
            throw DocumentTextError.empty
        }
        return DocumentContent(kind: "docx", lines: parser.lines, tables: parser.tables, needsOCR: false)
    }

    private static func readXlsx(url: URL) throws -> DocumentContent {
        let archive = try openOfficeArchive(url: url)

        var sharedStrings: [String] = []
        if let data = archive.entries["xl/sharedStrings.xml"] {
            let parser = SharedStringsParser()
            guard parser.parse(data) else { throw DocumentTextError.broken }
            sharedStrings = parser.strings
        }

        var dateStyles: Set<Int> = []
        if let data = archive.entries["xl/styles.xml"] {
            let parser = StylesParser()
            guard parser.parse(data) else { throw DocumentTextError.broken }
            dateStyles = parser.dateStyleIndexes
        }

        let sheetNames = archive.entries.keys
            .filter { $0.hasPrefix("xl/worksheets/sheet") && $0.hasSuffix(".xml") }
            .sorted { sheetNumber($0) < sheetNumber($1) }
        guard !sheetNames.isEmpty else { throw DocumentTextError.broken }

        var tables: [[[String]]] = []
        var lines: [String] = []
        for name in sheetNames {
            guard let data = archive.entries[name] else { continue }
            let parser = SheetParser(sharedStrings: sharedStrings, dateStyles: dateStyles)
            guard parser.parse(data) else { throw DocumentTextError.broken }
            guard !parser.rows.isEmpty else { continue }
            tables.append(parser.rows)
            lines.append(contentsOf: parser.rows.map { $0.joined(separator: " ") })
        }

        guard hasText(lines: lines, tables: tables) else { throw DocumentTextError.empty }
        return DocumentContent(kind: "xlsx", lines: lines, tables: tables, needsOCR: false)
    }

    private static func readPDF(url: URL) throws -> DocumentContent {
        guard let document = PDFDocument(url: url) else { throw DocumentTextError.broken }
        guard !document.isLocked else { throw DocumentTextError.locked }

        var lines: [String] = []
        for pageIndex in 0..<document.pageCount {
            guard let pageText = document.page(at: pageIndex)?.string else { continue }
            lines.append(contentsOf: pageText.components(separatedBy: .newlines).compactMap {
                let line = $0.trimmingCharacters(in: .whitespacesAndNewlines)
                return line.isEmpty ? nil : line
            })
        }
        let needsOCR = lines.joined().trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return DocumentContent(kind: "pdf", lines: needsOCR ? [] : lines, tables: [], needsOCR: needsOCR)
    }

    private static func openOfficeArchive(url: URL) throws -> ZipReader {
        let data: Data
        do {
            data = try Data(contentsOf: url)
        } catch {
            throw DocumentTextError.broken
        }

        // 暗号化された Office 文書は ZIP ではなく複合ファイル形式になる。
        if data.starts(with: [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]) {
            throw DocumentTextError.locked
        }
        do {
            return try ZipReader(data: data)
        } catch {
            throw DocumentTextError.broken
        }
    }

    private static func hasText(lines: [String], tables: [[[String]]]) -> Bool {
        if lines.contains(where: { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) {
            return true
        }
        return tables.flatMap { $0 }.flatMap { $0 }.contains {
            !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    private static func sheetNumber(_ path: String) -> Int {
        let name = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
        return Int(name.dropFirst("sheet".count)) ?? Int.max
    }
}

private final class WordParser: NSObject, XMLParserDelegate {
    private(set) var lines: [String] = []
    private(set) var tables: [[[String]]] = []
    private var paragraph: String?
    private var text = ""
    private var inText = false
    private var table: [[String]]?
    private var row: [String]?
    private var cellParagraphs: [String]?

    func parse(_ data: Data) -> Bool {
        let parser = XMLParser(data: data)
        parser.delegate = self
        return parser.parse()
    }

    func parser(
        _ parser: XMLParser,
        didStartElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?,
        attributes attributeDict: [String: String] = [:]
    ) {
        switch localName(elementName) {
        case "tbl": table = []
        case "tr": row = []
        case "tc": cellParagraphs = []
        case "p": paragraph = ""
        case "t":
            inText = true
            text = ""
        case "tab": paragraph?.append("\t")
        case "br", "cr": paragraph?.append("\n")
        default: break
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if inText { text += string }
    }

    func parser(
        _ parser: XMLParser,
        didEndElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?
    ) {
        switch localName(elementName) {
        case "t":
            paragraph?.append(text)
            inText = false
        case "p":
            let value = normalized(paragraph ?? "")
            if !value.isEmpty {
                lines.append(value)
                cellParagraphs?.append(value)
            }
            paragraph = nil
        case "tc":
            row?.append(cellParagraphs?.joined(separator: " ") ?? "")
            cellParagraphs = nil
        case "tr":
            if let row { table?.append(row) }
            row = nil
        case "tbl":
            if let table { tables.append(table) }
            table = nil
        default: break
        }
    }
}

private final class SharedStringsParser: NSObject, XMLParserDelegate {
    private(set) var strings: [String] = []
    private var current: String?
    private var inText = false

    func parse(_ data: Data) -> Bool {
        let parser = XMLParser(data: data)
        parser.delegate = self
        return parser.parse()
    }

    func parser(
        _ parser: XMLParser,
        didStartElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?,
        attributes attributeDict: [String: String] = [:]
    ) {
        switch localName(elementName) {
        case "si": current = ""
        case "t": inText = current != nil
        default: break
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if inText { current?.append(string) }
    }

    func parser(
        _ parser: XMLParser,
        didEndElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?
    ) {
        switch localName(elementName) {
        case "t": inText = false
        case "si":
            strings.append(current ?? "")
            current = nil
        default: break
        }
    }
}

private final class StylesParser: NSObject, XMLParserDelegate {
    private(set) var dateStyleIndexes: Set<Int> = []
    private var customFormats: [Int: String] = [:]
    private var inCellFormats = false
    private var styleIndex = 0

    func parse(_ data: Data) -> Bool {
        let parser = XMLParser(data: data)
        parser.delegate = self
        return parser.parse()
    }

    func parser(
        _ parser: XMLParser,
        didStartElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?,
        attributes attributeDict: [String: String] = [:]
    ) {
        switch localName(elementName) {
        case "numFmt":
            if let identifier = attributeDict["numFmtId"].flatMap(Int.init),
               let code = attributeDict["formatCode"] {
                customFormats[identifier] = code
            }
        case "cellXfs":
            inCellFormats = true
            styleIndex = 0
        case "xf" where inCellFormats:
            if let identifier = attributeDict["numFmtId"].flatMap(Int.init), isDateFormat(identifier) {
                dateStyleIndexes.insert(styleIndex)
            }
            styleIndex += 1
        default: break
        }
    }

    func parser(
        _ parser: XMLParser,
        didEndElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?
    ) {
        if localName(elementName) == "cellXfs" { inCellFormats = false }
    }

    private func isDateFormat(_ identifier: Int) -> Bool {
        if (14...22).contains(identifier) { return true }
        guard let code = customFormats[identifier]?.lowercased() else { return false }
        let visible = code.replacingOccurrences(of: "\"[^\"]*\"", with: "", options: .regularExpression)
        return visible.contains("y") && visible.contains("m") && visible.contains("d")
    }
}

private final class SheetParser: NSObject, XMLParserDelegate {
    private(set) var rows: [[String]] = []
    private let sharedStrings: [String]
    private let dateStyles: Set<Int>
    private var cells: [(column: Int, value: String)]?
    private var cellColumn = 0
    private var cellType = ""
    private var cellStyle: Int?
    private var cellValue = ""
    private var inlineText = ""
    private var collectingValue = false
    private var collectingInlineText = false

    init(sharedStrings: [String], dateStyles: Set<Int>) {
        self.sharedStrings = sharedStrings
        self.dateStyles = dateStyles
    }

    func parse(_ data: Data) -> Bool {
        let parser = XMLParser(data: data)
        parser.delegate = self
        return parser.parse()
    }

    func parser(
        _ parser: XMLParser,
        didStartElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?,
        attributes attributeDict: [String: String] = [:]
    ) {
        switch localName(elementName) {
        case "row":
            cells = []
        case "c":
            cellColumn = Self.columnIndex(from: attributeDict["r"] ?? "")
            cellType = attributeDict["t"] ?? ""
            cellStyle = attributeDict["s"].flatMap(Int.init)
            cellValue = ""
            inlineText = ""
        case "v": collectingValue = true
        case "t" where cellType == "inlineStr": collectingInlineText = true
        default: break
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if collectingValue { cellValue += string }
        if collectingInlineText { inlineText += string }
    }

    func parser(
        _ parser: XMLParser,
        didEndElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?
    ) {
        switch localName(elementName) {
        case "v": collectingValue = false
        case "t": collectingInlineText = false
        case "c":
            cells?.append((cellColumn, resolvedCellValue()))
        case "row":
            if let cells, let maximum = cells.map(\.column).max() {
                var row = Array(repeating: "", count: maximum + 1)
                for cell in cells { row[cell.column] = cell.value }
                if row.contains(where: { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) {
                    rows.append(row)
                }
            }
            cells = nil
        default: break
        }
    }

    private func resolvedCellValue() -> String {
        if cellType == "inlineStr" { return normalized(inlineText) }
        let value = normalized(cellValue)
        if cellType == "s", let index = Int(value), sharedStrings.indices.contains(index) {
            return sharedStrings[index]
        }
        if let style = cellStyle, dateStyles.contains(style), let serial = Double(value) {
            return Self.dateString(excelSerial: serial)
        }
        return value
    }

    private static func columnIndex(from reference: String) -> Int {
        var value = 0
        var foundLetter = false
        for scalar in reference.uppercased().unicodeScalars {
            guard scalar.value >= 65, scalar.value <= 90 else { break }
            foundLetter = true
            value = value * 26 + Int(scalar.value - 64)
        }
        return foundLetter ? value - 1 : 0
    }

    private static func dateString(excelSerial: Double) -> String {
        let seconds = (excelSerial - 25_569) * 86_400
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: Date(timeIntervalSince1970: seconds))
    }
}

private func localName(_ name: String) -> String {
    name.split(separator: ":").last.map(String.init) ?? name
}

private func normalized(_ text: String) -> String {
    text.trimmingCharacters(in: .whitespacesAndNewlines)
}
