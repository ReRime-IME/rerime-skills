import CryptoKit
import Foundation

// Host-side report of what ReRime's importer decides about a file, as JSON, for the
// comparison with validate_rerime_table.py (see tests/parity/README.md). This file holds no
// ReRime source: it is compiled together with the importer sources of the ReRime App
// repository, which this repository does not contain.
//
//   importer-report cases CASES.json OUTDIR   one JSON line per case, canonical tables in OUTDIR
//   importer-report scalars                   every Unicode scalar as a row's text
//   importer-report gb18030                   GB18030 byte sequences as a row's text
//   importer-report graphemes                 Character counts of the hex strings on stdin
//   importer-report tables                    the character data the checker carries

struct Case: Decodable {
    let name: String
    let path: String
    let fileName: String?
    let limits: [String: Int]?
    let table: Int?
}

// A few Pinyin syllables stand in for the App's syllable list. The scheme door's answer
// does not depend on it; cases with these codes show that.
let syllables: Set<String> = ["ni", "hao", "shi", "jie", "zhong", "guo", "tian", "di"]

func makeOptions(_ overrides: [String: Int]?) -> UserTableImportOptions {
    var options = UserTableImportOptions()
    options.isPinyinSyllable = { syllables.contains($0) }
    for (key, value) in overrides ?? [:] {
        switch key {
        case "maximumFileBytes": options.limits.maximumFileBytes = value
        case "maximumRows": options.limits.maximumRows = value
        case "maximumArchiveBytes": options.limits.maximumArchiveBytes = value
        case "maximumArchiveMembers": options.limits.maximumArchiveMembers = value
        case "maximumMemberBytes": options.limits.maximumMemberBytes = value
        case "maximumImportBytes": options.limits.maximumImportBytes = value
        case "maximumLineBytes": options.limits.maximumLineBytes = value
        case "maximumHeaderBytes": options.limits.maximumHeaderBytes = value
        case "maximumHeaderLines": options.limits.maximumHeaderLines = value
        case "personalEntryRows": options.limits.personalEntryRows = value
        case "personalEntryBytes": options.limits.personalEntryBytes = value
        default: fatalError("unknown limit \(key)")
        }
    }
    return options
}

func refusalReport(_ refusal: UserTableRefusal) -> [String: Any] {
    switch refusal {
    case .empty: return ["refusal": "empty"]
    case .fileTooLarge(let bytes, let limit): return ["refusal": "fileTooLarge", "bytes": bytes, "limit": limit]
    case .tooManyRows(let rows, let limit): return ["refusal": "tooManyRows", "rows": rows, "limit": limit]
    case .unknownEncoding: return ["refusal": "unknownEncoding"]
    case .schemeFile: return ["refusal": "schemeFile"]
    case .compiledDictionary: return ["refusal": "compiledDictionary"]
    case .unsupportedFile: return ["refusal": "unsupportedFile"]
    case .tooFewValidRows(let valid, let invalid): return ["refusal": "tooFewValidRows", "valid": valid, "invalid": invalid]
    case .tooFewRows(let rows, let minimum): return ["refusal": "tooFewRows", "rows": rows, "minimum": minimum]
    case .doesNotFitEngine: return ["refusal": "doesNotFitEngine"]
    case .archiveTooLarge(let bytes, let limit): return ["refusal": "archiveTooLarge", "bytes": bytes, "limit": limit]
    case .archiveTooManyMembers(let count, let limit):
        return ["refusal": "archiveTooManyMembers", "count": count, "limit": limit]
    case .archiveEncrypted: return ["refusal": "archiveEncrypted"]
    case .archiveUnsupported(let problem): return ["refusal": "archiveUnsupported", "problem": problem.rawValue]
    case .archiveNoTable: return ["refusal": "archiveNoTable"]
    case .archiveMemberTooLarge(let limit): return ["refusal": "archiveMemberTooLarge", "limit": limit]
    case .archiveImportTooLarge(let limit): return ["refusal": "archiveImportTooLarge", "limit": limit]
    case .selectionNotFound: return ["refusal": "selectionNotFound"]
    }
}

func label(_ kind: UserTableSourceKind) -> String {
    switch kind {
    case .rimeDictionary: return "rimeDictionary"
    case .phraseList(let grammar): return "phraseList:\(grammar.rawValue)"
    case .plainTable: return "plainTable"
    }
}

func hex(_ digest: SHA256.Digest) -> String { digest.map { String(format: "%02x", $0) }.joined() }

func tableReport(_ table: UserTableArchiveTable) -> [String: Any] {
    ["id": table.id, "memberName": table.memberName, "suggestedName": table.suggestedName, "kind": label(table.kind),
     "declaredBytes": table.declaredBytes, "importedFiles": table.importedFiles, "isSchemeMain": table.isSchemeMain]
}

func budgetReport(_ budget: UserTableBuildBudget?) -> Any {
    guard let budget else { return NSNull() }
    return ["entries": budget.entries, "syllables": budget.syllables, "indexBytes": budget.indexBytes,
            "textBytes": budget.textBytes, "estimateBytes": budget.estimateBytes, "boundBytes": budget.boundBytes,
            "state": budget.state.rawValue]
}

func analysisReport(_ analysis: UserTableAnalysis?, _ canonical: Data) -> Any {
    guard let analysis else { return NSNull() }
    let s = analysis.structure
    func engineDigest(_ scheme: UserTableScheme) -> String {
        hex(SHA256.hash(data: UserTableAnalyzer.engineRows(canonicalTable: canonical, scheme: scheme)))
    }
    return [
        "rows": s.rows, "charactersWithOwnRow": s.charactersWithOwnRow,
        "charactersWithSeveralCodes": s.charactersWithSeveralCodes, "multiCharacterRows": s.multiCharacterRows,
        "codedAsAllCharacters": s.codedAsAllCharacters, "codedAsLeadingCharacters": s.codedAsLeadingCharacters,
        "codedOtherwise": s.codedOtherwise, "bySyllable": s.bySyllable, "longestCode": s.longestCode,
        "distinctCodes": s.distinctCodes, "mostRowsOnOneCode": s.mostRowsOnOneCode,
        "longestSyllableCode": s.longestSyllableCode, "optionalFinalLetters": s.optionalFinalLetters,
        "spellings": s.spellings, "syllables": s.syllables,
        "bySyllableBudget": budgetReport(analysis.bySyllableBudget), "wholeWordBudget": budgetReport(analysis.wholeWordBudget),
        "wholeWordRowsSHA256": engineDigest(.wholeWord), "bySyllableRowsSHA256": engineDigest(.bySyllable),
    ] as [String: Any]
}

/// The answer of the 添加输入方案… door for what the importer said.
func schemeDoor(_ content: UserTableFileFacts.Content) -> Any {
    let facts = UserTableFileFacts(isEntriesFile: false, content: content)
    switch UserTableDoors.route(facts, door: .scheme) {
    case .schemePreview: return ["route": "schemePreview"]
    case .refuse(let refusal): return refusalReport(refusal).merging(["route": "refuse"]) { $1 }
    default: return ["route": "other"]
    }
}

func report(_ data: Data, fileName: String?, table: Int?, options: UserTableImportOptions,
            canonicalTo: URL? = nil) -> [String: Any] {
    do {
        switch try UserTableImporter.read(data, fileName: fileName, archiveTable: table, options: options) {
        case .chooseTable(let tables):
            return ["outcome": "choose", "tables": tables.map(tableReport), "door": schemeDoor(.severalTables)]
        case .table(let imported):
            let preview = imported.preview, reading = preview.reading
            let canonical = imported.canonicalTable()
            if let canonicalTo { try canonical.write(to: canonicalTo) }
            var skipped: [String: Int] = [:], skippedLines: [String: [Int]] = [:]
            for (reason, count) in preview.skipped { skipped[reason.rawValue] = count }
            for (reason, lines) in preview.skippedLines { skippedLines[reason.rawValue] = lines }
            let facts = UserTableFileFacts.Table(
                tooLargeForEntries: preview.destinationRule == .tooLargeForPersonalEntries,
                codesArePinyin: preview.codesArePinyin, canBeTable: preview.canBeTable,
                suggestsEntries: preview.suggestedDestination == .personalEntries, rowCount: preview.rowCount,
                entryLimit: options.limits.personalEntryRows, isInstalledTable: false)
            return [
                "outcome": "table",
                "reading": [
                    "kind": label(reading.kind), "encoding": reading.encoding.rawValue,
                    "hadByteOrderMark": reading.hadByteOrderMark, "columnOrder": reading.columnOrder.rawValue,
                    "columnOrderAssumed": reading.columnOrderAssumed, "separator": reading.separator.rawValue,
                    "usedDataMarker": reading.usedDataMarker, "keptFileOrder": reading.keptFileOrder,
                    "importedFiles": reading.importedFiles, "missingImports": reading.missingImports,
                ] as [String: Any],
                "rowCount": preview.rowCount, "skipped": skipped, "skippedLines": skippedLines,
                "canonicalSHA256": hex(SHA256.hash(data: canonical)), "canonicalBytes": canonical.count,
                "suggestedName": preview.suggestedName as Any? ?? NSNull(),
                "suggestsEntries": preview.suggestedDestination == .personalEntries,
                "tooLargeForEntries": preview.destinationRule == .tooLargeForPersonalEntries,
                "canBeTable": preview.canBeTable, "scheme": preview.scheme?.rawValue as Any? ?? NSNull(),
                "schemeNeedsExactCheck": preview.schemeNeedsExactCheck,
                "tables": preview.archiveTables.map(tableReport),
                "selectedTable": preview.selectedArchiveTable as Any? ?? NSNull(),
                "analysis": analysisReport(imported.analysis, canonical), "door": schemeDoor(.table(facts)),
            ]
        }
    } catch let refusal as UserTableRefusal {
        return refusalReport(refusal).merging(["outcome": "refused", "door": schemeDoor(.refused(refusal))]) { $1 }
    } catch {
        return ["outcome": "error", "error": String(describing: error)]
    }
}

func emit(_ object: Any) {
    let data = try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
    FileHandle.standardOutput.write(data + Data([0x0A]))
}

func runCases(_ casesPath: String, _ outDirectory: String) throws {
    let cases = try JSONDecoder().decode([Case].self, from: Data(contentsOf: URL(fileURLWithPath: casesPath)))
    let out = URL(fileURLWithPath: outDirectory)
    try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
    for item in cases {
        autoreleasepool {
            let data = try! Data(contentsOf: URL(fileURLWithPath: item.path))
            var result = report(data, fileName: item.fileName ?? URL(fileURLWithPath: item.path).lastPathComponent,
                                table: item.table, options: makeOptions(item.limits),
                                canonicalTo: out.appendingPathComponent(item.name + ".tsv"))
            result["name"] = item.name
            emit(result)
        }
    }
}

// MARK: Sweeps

/// What the importer does with one probe row (code `zz`) placed after two plain rows:
/// `=` kept unchanged, `K<hex>` kept as other bytes, a skip reason, or `R<refusal>`.
/// Anything else that happens to the file (rows split or merged) is spelled out.
func probe(_ file: [UInt8], probeText: [UInt8], options: UserTableImportOptions) -> String {
    do {
        guard case .table(let imported) = try UserTableImporter.read(Data(file), fileName: "probe.txt", options: options) else {
            return "?choose"
        }
        var kept: [String] = []
        for position in 0..<imported.rowCount {
            let row = imported.row(at: position)
            if row.code == "zz" { kept.append(Array(row.text.utf8) == probeText ? "=" : "K" + row.text.utf8.map { String(format: "%02x", $0) }.joined()) }
        }
        let skipped = imported.preview.skippedLines.map { "\($0.key.rawValue)@\($0.value.map(String.init).joined(separator: ","))" }.sorted()
        let rows = imported.rowCount - kept.count
        return (kept + skipped).joined(separator: " ") + (rows == 2 ? "" : " rows=\(rows)")
    } catch let refusal as UserTableRefusal {
        return "R" + (refusalReport(refusal)["refusal"] as! String)
    } catch { return "?error" }
}

func sweepScalars() {
    let options = makeOptions(nil)
    let head = Array("天\taa\n地\tab\n".utf8)
    var output = ""
    for value in UInt32(0)...0x10FFFF {
        guard let scalar = Unicode.Scalar(value) else { continue }
        let alone = Array(String(scalar).utf8)
        let inside = Array("中".utf8) + alone + Array("中".utf8)
        let first = probe(head + alone + Array("\tzz\n".utf8), probeText: alone, options: options)
        let second = probe(head + inside + Array("\tzz\n".utf8), probeText: inside, options: options)
        output += String(value, radix: 16) + "\t" + first + "\t" + second + "\n"
        if output.utf8.count > 1 << 20 { FileHandle.standardOutput.write(Data(output.utf8)); output = "" }
    }
    FileHandle.standardOutput.write(Data(output.utf8))
}

func sweepGB18030(step: Int) {
    let options = makeOptions(nil)
    // Bytes that are not valid UTF-8, so the file is tried as GB18030: 天 and 地 in GBK.
    let head: [UInt8] = [0xCC, 0xEC, 0x09, 0x61, 0x61, 0x0A, 0xB5, 0xD8, 0x09, 0x61, 0x62, 0x0A]
    var output = ""
    func run(_ sequence: [UInt8]) {
        let verdict = probe(head + sequence + Array("\tzz\n".utf8), probeText: [], options: options)
        output += sequence.map { String(format: "%02x", $0) }.joined() + "\t" + verdict + "\n"
        if output.utf8.count > 1 << 20 { FileHandle.standardOutput.write(Data(output.utf8)); output = "" }
    }
    for byte in UInt8(0x80)...0xFF { run([byte]) }
    for lead in UInt8(0x81)...0xFF { for trail in UInt8(0x30)...0xFF { run([lead, trail]) } }
    var index = 0
    for b1 in UInt8(0x81)...0xFE { for b2 in UInt8(0x30)...0x39 { for b3 in UInt8(0x81)...0xFE { for b4 in UInt8(0x30)...0x39 {
        // The BMP part in full, the rest sampled.
        if b1 <= 0x84 || index % step == 0 { run([b1, b2, b3, b4]) }
        index += 1
    } } } }
    FileHandle.standardOutput.write(Data(output.utf8))
}

func countGraphemes() {
    var output = ""
    while let line = readLine() {
        let scalars = line.split(separator: " ").compactMap { UInt32($0, radix: 16).flatMap(Unicode.Scalar.init) }
        output += "\(String(String.UnicodeScalarView(scalars)).count)\n"
    }
    FileHandle.standardOutput.write(Data(output.utf8))
}

/// The character data the checker carries, read from this host's Swift and Foundation: how
/// scalars group into Characters, and the property sets the importer asks for.
func dumpTables() {
    var sets: [(String, [UInt32])] = [("JOINS_PREVIOUS", []), ("CONJUNCT_EXTEND", []), ("JOINS_NEXT", []),
                                      ("CONJUNCT_CONSONANT", []), ("INVISIBLE", []), ("IDEOGRAPHS", []), ("WHITESPACE", [])]
    for value in UInt32(0)...0x10FFFF {
        guard let scalar = Unicode.Scalar(value) else { continue }
        let text = String(scalar)
        if value >= 0x80 {
            if ("a" + text).count == 1 {
                sets[0].1.append(value)
                if ("\u{0915}\u{094D}" + text + "\u{0915}").count == 1 { sets[1].1.append(value) }
            } else {
                if (text + "a").count == 1 { sets[2].1.append(value) }
                if ("\u{0915}\u{094D}" + text).count == 1 { sets[3].1.append(value) }
            }
        }
        if scalar.properties.isDefaultIgnorableCodePoint || scalar.properties.isVariationSelector { sets[4].1.append(value) }
        if scalar.properties.isUnifiedIdeograph || value == 0x3007 { sets[5].1.append(value) }
        if CharacterSet.whitespaces.contains(scalar) { sets[6].1.append(value) }
    }
    for (name, values) in sets {
        var ranges: [String] = []
        var index = 0
        while index < values.count {
            var last = index
            while last + 1 < values.count, values[last + 1] == values[last] + 1 { last += 1 }
            ranges.append(index == last ? String(values[index], radix: 16)
                          : String(values[index], radix: 16) + "-" + String(values[last], radix: 16))
            index = last + 1
        }
        print(name, ranges.joined(separator: " "))
    }
}

let arguments = CommandLine.arguments
switch arguments.count > 1 ? arguments[1] : "" {
case "cases" where arguments.count == 4: try runCases(arguments[2], arguments[3])
case "scalars": sweepScalars()
case "gb18030": sweepGB18030(step: arguments.count > 2 ? Int(arguments[2]) ?? 97 : 97)
case "graphemes": countGraphemes()
case "tables": dumpTables()
default:
    FileHandle.standardError.write(Data("usage: importer-report cases CASES.json OUTDIR | scalars | gb18030 [STEP] | graphemes | tables\n".utf8))
    exit(2)
}
