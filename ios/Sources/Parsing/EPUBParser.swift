import Foundation

/// EPUB（ZIP + OPF + XHTML）から本文を読み出す。
enum EPUBParser {
    static func blocks(from url: URL) throws -> [RawBlock] {
        let archive: ZIPArchive
        do {
            archive = try ZIPArchive(url: url)
        } catch {
            throw ParseError.brokenEPUB(error.localizedDescription)
        }

        let opfPath = try rootFilePath(in: archive)
        let opfDirectory = (opfPath as NSString).deletingLastPathComponent

        let package: PackageDocument
        do {
            package = try PackageDocument(xml: try archive.string(for: opfPath))
        } catch {
            throw ParseError.brokenEPUB("OPF を読めません: \(error.localizedDescription)")
        }

        let documentPaths = readingOrder(package: package, opfDirectory: opfDirectory, archive: archive)
        guard !documentPaths.isEmpty else { throw ParseError.brokenEPUB("本文ファイルが見つかりません") }

        var blocks: [RawBlock] = []
        var lastHeading: String?

        for (index, path) in documentPaths.enumerated() {
            guard let html = try? archive.string(for: path) else { continue }

            let chapterTitle = HTMLTextExtractor.title(from: html)
            let locator = chapterTitle ?? "セクション \(index + 1)"
            var chapterBlocks = HTMLTextExtractor.blocks(from: html, locator: locator)
            guard !chapterBlocks.isEmpty else { continue }

            // 章内に見出しが無い場合だけ、<title> を見出しとして補う。
            if !chapterBlocks.contains(where: { $0.isHeading }),
               let chapterTitle, chapterTitle != lastHeading {
                chapterBlocks.insert(
                    RawBlock(text: chapterTitle, isHeading: true, locator: locator),
                    at: 0
                )
            }
            lastHeading = chapterBlocks.first(where: { $0.isHeading })?.text ?? lastHeading
            blocks.append(contentsOf: chapterBlocks)
        }

        guard !blocks.isEmpty else { throw ParseError.noExtractableText }
        return blocks
    }

    /// EPUB のタイトル（メタデータ）。取り込み時の本のタイトルに使う。
    static func metadataTitle(from url: URL) -> String? {
        guard let archive = try? ZIPArchive(url: url),
              let opfPath = try? rootFilePath(in: archive),
              let package = try? PackageDocument(xml: try archive.string(for: opfPath))
        else { return nil }
        return package.title
    }

    // MARK: - Private

    private static func rootFilePath(in archive: ZIPArchive) throws -> String {
        guard let containerXML = try? archive.string(for: "META-INF/container.xml") else {
            throw ParseError.brokenEPUB("META-INF/container.xml がありません")
        }
        guard let path = ContainerDocument(xml: containerXML).rootFilePath else {
            throw ParseError.brokenEPUB("container.xml に rootfile がありません")
        }
        let normalized = ZIPArchive.normalize(path.removingPercentEncoding ?? path)
        guard archive.contains(normalized) else {
            throw ParseError.brokenEPUB("\(normalized) がアーカイブ内にありません")
        }
        return normalized
    }

    /// spine の順に本文ファイルを並べる。spine が壊れている場合は拡張子で拾う。
    private static func readingOrder(
        package: PackageDocument,
        opfDirectory: String,
        archive: ZIPArchive
    ) -> [String] {
        var paths: [String] = []

        for idref in package.spine {
            guard let item = package.manifest[idref] else { continue }
            if !item.mediaType.isEmpty, !item.mediaType.contains("html") { continue }
            let href = item.href.components(separatedBy: "#")[0]
            let decoded = href.removingPercentEncoding ?? href
            let path = ZIPArchive.resolve(decoded, relativeTo: opfDirectory)
            if archive.contains(path) { paths.append(path) }
        }

        if paths.isEmpty {
            paths = archive.entries.keys
                .filter { path in
                    let ext = (path as NSString).pathExtension.lowercased()
                    return ext == "xhtml" || ext == "html" || ext == "htm"
                }
                .sorted()
        }
        return paths
    }
}

// MARK: - XML

/// META-INF/container.xml から OPF の場所を取り出す。
private final class ContainerDocument: NSObject, XMLParserDelegate {
    private(set) var rootFilePath: String?

    init(xml: String) {
        super.init()
        guard let data = xml.data(using: .utf8) else { return }
        let parser = XMLParser(data: data)
        parser.delegate = self
        parser.parse()
    }

    func parser(
        _ parser: XMLParser,
        didStartElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?,
        attributes attributeDict: [String: String]
    ) {
        guard rootFilePath == nil, localName(of: elementName) == "rootfile" else { return }
        rootFilePath = attributeDict["full-path"]
    }

    private func localName(of name: String) -> String {
        (name.components(separatedBy: ":").last ?? name).lowercased()
    }
}

/// OPF（パッケージ文書）のマニフェストと spine。
private final class PackageDocument: NSObject, XMLParserDelegate {
    struct Item {
        let href: String
        let mediaType: String
    }

    private(set) var title: String?
    private(set) var manifest: [String: Item] = [:]
    private(set) var spine: [String] = []

    private var isReadingTitle = false
    private var titleBuffer = ""

    init(xml: String) throws {
        super.init()
        guard let data = xml.data(using: .utf8) else {
            throw ParseError.brokenEPUB("OPF の文字コードを判別できません")
        }
        let parser = XMLParser(data: data)
        parser.delegate = self
        guard parser.parse() else {
            throw ParseError.brokenEPUB(parser.parserError?.localizedDescription ?? "XML 解析に失敗しました")
        }
    }

    func parser(
        _ parser: XMLParser,
        didStartElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?,
        attributes attributeDict: [String: String]
    ) {
        switch localName(of: elementName) {
        case "item":
            if let id = attributeDict["id"], let href = attributeDict["href"] {
                manifest[id] = Item(href: href, mediaType: attributeDict["media-type"] ?? "")
            }
        case "itemref":
            if let idref = attributeDict["idref"] {
                // linear="no" は本文の流れから外れる補助ページ。
                if attributeDict["linear"]?.lowercased() != "no" { spine.append(idref) }
            }
        case "title":
            if title == nil {
                isReadingTitle = true
                titleBuffer = ""
            }
        default:
            break
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        guard isReadingTitle else { return }
        titleBuffer += string
    }

    func parser(
        _ parser: XMLParser,
        didEndElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?
    ) {
        guard localName(of: elementName) == "title", isReadingTitle else { return }
        isReadingTitle = false
        let trimmed = titleBuffer.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { title = trimmed }
    }

    private func localName(of name: String) -> String {
        (name.components(separatedBy: ":").last ?? name).lowercased()
    }
}
