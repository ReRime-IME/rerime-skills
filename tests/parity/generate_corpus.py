#!/usr/bin/env python3
"""Writes the synthetic corpus the checker and ReRime's importer are compared on.

    python3 tests/parity/generate_corpus.py OUTPUT_DIRECTORY [--large]

Every file is invented here: made-up codes on common characters, no real input scheme and
no user data. The same call always writes the same bytes. OUTPUT_DIRECTORY/cases.json lists
the cases: name, path, the file name ReRime is told, limits that differ from ReRime's own
(so a cap can be crossed by a small file) and the table chosen from a ZIP.

--large adds the cases that cross ReRime's real caps (300,000 rows, 16 MiB, 64 MiB): they
take a few hundred megabytes of disk and some minutes.
"""
import json
import random
import struct
import sys
import zlib
from pathlib import Path

HAN = [chr(0x4E00 + n) for n in range(0, 4000)]
LETTERS = "abcdefghijklmnopqrstuvwxyz"


def code_of(index, letters=3):
    """A distinct invented code of `letters` letters for a number."""
    found = []
    for _ in range(letters):
        found.append(LETTERS[index % 26])
        index //= 26
    return "".join(found)


def table(rows, separator="\t", end="\n"):
    return "".join(separator.join(str(field) for field in row) + end for row in rows)


# --- Invented tables by structure -----------------------------------------------------------------


def syllabary(count, letters=3, finals=""):
    """`count` one-character rows with distinct codes; `finals` alternate on each stem."""
    if not finals:
        return [(HAN[n], code_of(n, letters)) for n in range(count)]
    return [(HAN[n], code_of(n // len(finals), letters) + finals[n % len(finals)]) for n in range(count)]


def words(singles, count, length=2, seed=1):
    """`count` distinct words of `length` characters, coded as the joined codes."""
    rng = random.Random(seed)
    found = {}
    while len(found) < count:
        picks = [rng.choice(singles) for _ in range(length)]
        found.setdefault("".join(text for text, _ in picks), "".join(code for _, code in picks))
    return list(found.items())


def other_words(singles, count, seed=2):
    """Words whose codes are not the joined codes of their characters."""
    rng = random.Random(seed)
    found = {}
    while len(found) < count:
        text = "".join(rng.choice(singles)[0] for _ in range(2))
        found.setdefault(text, "zzq" + code_of(len(found), 4))
    return list(found.items())


# --- A ZIP writer that can write every irregular archive ----------------------------------------


class Zip:
    def __init__(self):
        self.body = bytearray()
        self.entries = []

    def add(self, name, content, method=8, flags=0, crc=None, declared=None, packed=None, extra=b"",
            local_name=None, local_flags=None, local_method=None, local_sizes=None, offset=None, raw=None):
        """`content` is the member's real bytes; every other argument overrides one field."""
        name_bytes = name if isinstance(name, bytes) else name.encode("utf-8")
        if raw is None:
            if method == 8:
                deflater = zlib.compressobj(6, zlib.DEFLATED, -15)
                raw = deflater.compress(content) + deflater.flush()
            else:
                raw = content
        crc = zlib.crc32(content) if crc is None else crc
        declared = len(content) if declared is None else declared
        packed = len(raw) if packed is None else packed
        at = len(self.body) if offset is None else offset
        if offset is None:
            sizes = (crc, packed, declared) if local_sizes is None else local_sizes
            local = local_name if local_name is not None else name_bytes
            self.body += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags if local_flags is None else local_flags,
                                     method if local_method is None else local_method, 0, 0x21, *sizes,
                                     len(local), 0) + local + raw
        self.entries.append((name_bytes, flags, method, crc, packed, declared, extra, at))
        return self

    def bytes(self, comment=b"", gap=b"", total=None, disk=0, directory_size=None, directory_offset=None,
              locator=False, entry_disk=0):
        directory = bytearray()
        for name, flags, method, crc, packed, declared, extra, at in self.entries:
            directory += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, flags, method, 0, 0x21, crc, packed,
                                     declared, len(name), len(extra), 0, entry_disk, 0, 0, at) + name + extra
        start = len(self.body)
        count = len(self.entries) if total is None else total
        end = struct.pack("<IHHHHIIH", 0x06054B50, disk, 0, count, count,
                          len(directory) if directory_size is None else directory_size,
                          start if directory_offset is None else directory_offset, len(comment)) + comment
        middle = (b"PK\x06\x07" + bytes(16)) if locator else b""
        return bytes(self.body) + bytes(directory) + gap + middle + end


def unicode_path(raw, name):
    data = b"\x01" + struct.pack("<I", zlib.crc32(raw)) + name.encode("utf-8")
    return struct.pack("<HH", 0x7075, len(data)) + data


# --- The cases ----------------------------------------------------------------------------------


def build(large=False):
    """[(name, file name, bytes, limits or None, chosen table or None)]"""
    cases = []

    def add(name, data, file_name="table.txt", limits=None, choose=None):
        if isinstance(data, str):
            data = data.encode("utf-8")
        assert name not in {case[0] for case in cases}, name
        cases.append((name, file_name, data, limits, choose))

    base = "天\tba\n地\tbo\n玄\tda\n黄\tdo\n天地\tbabo\n玄黄\tdado\n"
    singles = syllabary(60, finals="ptx")
    # Valid rows appended where a case would otherwise be refused for its invalid rows, so
    # that every skipped row is compared, not only the refusal.
    pad = table([(HAN[3000 + n], "zzy" + code_of(n)) for n in range(40)])
    pad_space = pad.replace("\t", " ")

    def pad_phrases(form):
        return "".join(form.format(code="zzy" + code_of(n), text=HAN[3000 + n]) + "\n" for n in range(40))

    # Encodings.
    add("utf8", base)
    add("utf8-bom", b"\xef\xbb\xbf" + base.encode("utf-8"))
    add("utf8-bom-invalid", b"\xef\xbb\xbf" + "天\tba\n".encode("gb18030") + b"\xff\n")
    add("utf16le-bom", b"\xff\xfe" + base.encode("utf-16-le"))
    add("utf16be-bom", b"\xfe\xff" + base.encode("utf-16-be"))
    add("utf16le-unmarked", base.encode("utf-16-le"))
    add("utf16be-unmarked", base.encode("utf-16-be"))
    add("utf16le-bom-odd-length", b"\xff\xfe" + base.encode("utf-16-le") + b"\x0a")
    add("utf16le-bom-lone-surrogate", b"\xff\xfe" + "天\tba\n".encode("utf-16-le") + b"\x00\xd8" + "\tbo\n".encode("utf-16-le"))
    add("utf16le-unmarked-lone-surrogate", "天\tba\n".encode("utf-16-le") + b"\x00\xd8" + "\tbo\n".encode("utf-16-le"))
    add("utf16-supplementary", b"\xff\xfe" + "𠀀\tba\n𠀁\tbo\n𠀀𠀁\tbabo\n".encode("utf-16-le"))
    add("utf16le-no-separators", "天地玄黄".encode("utf-16-le"))
    add("utf16-equal-both-orders", b"\x09\x00\x00\x09" + "天".encode("utf-16-le"))
    add("utf32le-bom", b"\xff\xfe\x00\x00" + base.encode("utf-32-le"))
    add("utf32be-bom", b"\x00\x00\xfe\xff" + base.encode("utf-32-be"))
    add("gb18030", base.encode("gb18030"))
    add("gb18030-four-byte", "㐀\tba\n𠀀\tbo\n㐀𠀀\tbabo\n天\tda\n".encode("gb18030"))
    add("gb18030-invalid-byte", "天\tba\n".encode("gb18030") + b"\xff\tbo\n")
    add("gb18030-truncated", "天\tba\n地\tbo".encode("gb18030") + b"\xcc")
    add("gb18030-mostly-private-use", b"\xaa\xa1\tba\n\xaa\xa2\tbo\n\xaa\xa3\tda\n")
    add("gb18030-one-private-use-in-200", "".join(f"{HAN[n]}\t{code_of(n)}\n" for n in range(199)).encode("gb18030")
        + b"\xaa\xa1\tzz\n")
    add("gb18030-euro-sign", "天\tba\n".encode("gb18030") + b"\xa2\xe3\tbo\n\x80\tda\n")
    add("big5-text", "天\tba\n地\tbo\n玄\tda\n黃\tdo\n".encode("big5"))
    add("shift-jis-text", "天\tba\n地\tbo\nかな\tda\n".encode("shift_jis"))
    add("latin1-text", "café\tba\nnaïve\tbo\n".encode("latin-1"))
    add("euc-kr-text", "한\tba\n글\tbo\n".encode("euc_kr"))
    add("nul-in-text", b"\xe5\xa4\xa9\tba\n\x00\tbo\n")
    add("nul-in-text-dictionary-name", b"\xe5\xa4\xa9\tba\n\x00\tbo\n", file_name="table.DAT")
    add("nul-not-text-bin-name", b"\x00\x01\x02\xff\xfe\xfd" * 20, file_name="words.bin")
    add("nul-not-text-other-name", b"\x01\x00\x02\xff\xfe\xfd" * 20, file_name="words.pdf")
    for index, magic in enumerate([b"Rime::Table/4.0", b"mschxudp\x02\x00", b"\x40\x15\x00\x00\x44\x43\x53\x01\x01",
                                   b"Freeime Dictionary 1", b"\x55\xaa\x88\x81\x02"]):
        add(f"compiled-magic-{index}", magic + b"\x00" * 8 + b"\n")
    for index, magic in enumerate([b"%PDF-1.7\n", b"\x7fELF\x02", b"\x89PNG\r\n", b"\xff\xd8\xff\xe0", b"GIF89a",
                                   b"\x00\x01\x00\x00\x00", b"\xcf\xfa\xed\xfe\x07", b"\xca\xfe\xba\xbe\x00",
                                   b"7z\xbc\xaf\x27", b"SQLite format 3\x00"]):
        add(f"binary-magic-{index}", magic + b"abc\n")
    for index, magic in enumerate([b"MZ", b"PK", b"OTTO", b"ttcf", b"wOF", b"Rar!", b"\x1f\x8b"]):
        add(f"short-magic-with-nul-{index}", magic + b"\x90\x00\x03" + b"x" * 40)
        add(f"short-magic-nul-after-512-{index}", magic + b"a\tb\n" * 200 + b"\x00")
    add("short-magic-as-text", "PKU\tba\nMZT\tbo\nRar!\tda\n")
    # A text table whose first bytes are a binary file's signature is refused as that file.
    for index, start in enumerate(["GIF89", "%PDF-x", "Rime::a", "mschxudp", "Freeime Dictionary", "SQLite format 3"]):
        add(f"magic-prefix-text-table-{index}", f"{start}\tba\n天\tbo\n地\tda\n")
    add("empty", b"")
    add("blank-only", b" \t\r\n\n  \n")
    add("comments-only", "# one\n# two\n")
    add("zip-end-record-only", b"PK\x05\x06" + bytes(18))

    # Plain tables.
    add("plain-code-first", "ba\t天\nbo\t地\nbabo\t天地\n")
    add("plain-both-letters", "ab\tba\ncd\tbo\n")
    add("plain-code-first-majority", "ba\t天\nbo\t地\n玄\tda\n")
    add("plain-order-tie", "ba\t天\n地\tbo\n")
    add("plain-weights", "天\tba\t5\n地\tba\t9\n玄\tba\n黄\tba\t9\n宇\tbo\t0\n宙\tbo\n")
    add("plain-code-first-weights", "ba\t天\t5\nba\t地\t9\nbo\t玄\n")
    add("plain-weight-digits", "天\tba\t1234567890\n地\tba\t12345678901\n玄\tba\t007\n黄\tba\t 3 \n")
    add("plain-third-column-not-digits", "天\tba\thigh\n地\tbo\t1.5\n玄\tda\t-3\n黄\tdo\t12%\n宇\tga\n宙\tgo\n日\tka\n月\tko\n" + pad)
    add("plain-four-columns", "天\tba\t1\tx\n地\tbo\n玄\tda\n")
    add("plain-code-first-four-columns", "ba\t天\t地\t玄\nbo\t黄\nda\t宇\n")
    add("plain-one-column", "天\n地\tbo\n玄\tda\n")
    add("plain-empty-fields", "天\t\n\tbo\n玄\tda\n黄\tdo\n宇\t\t5\n" + pad)
    add("plain-trailing-tabs", "天\tba\t\n地\tbo\t\t\n玄\tda\n")
    add("plain-leading-blanks", "  天\tba\n\t地\tbo\n 玄 \t da \n")
    add("plain-crlf", base.replace("\n", "\r\n"))
    add("plain-cr-only", base.replace("\n", "\r"))
    add("plain-no-final-newline", "天\tba\n地\tbo")
    add("plain-blank-lines", "\n\n天\tba\n\n地\tbo\n\n")
    add("plain-comments", "# head\n天\tba\n #indented\n#\n地\tbo\n玄\tda # not a comment\n")
    add("plain-code-spaces", "你好\tni hao\n你\tni\n好\thao\n你好\tnihao\n世界\tshi  jie\n世\t shi \n")
    add("plain-code-capitals", "天\tBA\n地\tBo\n天地\tBaBo\n")
    add("plain-code-rules", "天\tb1\n地\tb-o\n玄\tda'\n黄\tdö\n宇\t9\n宙\tga\n日\tgo\n月\tka\n星\tko\n辰\tma\n" + pad)
    add("plain-code-length", f"天\t{'a' * 96}\n地\t{'a' * 97}\n玄\t{'ab ' * 32}\n黄\t{'ab ' * 32}c\n宇\t{'a' * 129}\n宙\tbo\n")
    add("plain-code-inner-return", "天\tb\ra\n地\tbo\n玄\tda\n")
    add("plain-special-values", "$ddcmd(x)\tba\n$[date]\tbo\n$X\tda\n$1\tdo\n$\tga\n价$x\tgo\n $key\tka\n" + pad)
    add("plain-duplicates", "天\tba\n天\tba\n天\tbo\n天\tBA\n地\tba\n 天 \tba\t9\n")
    add("plain-nfc-duplicate", "é\tba\né\tba\nÅ\tbo\nÅ\tbo\n")
    add("plain-line-length", "天\tba\n地\tbo\n" + "玄" * 1365 + "\tda\n" + "玄" * 1364 + "\tda\n# " + "x" * 5000 + "\n"
        + "x" * 4094 + "\tb\n" + "x" * 4093 + "\tb\n" + " " * 100 + "黄\tdo" + " " * 5000 + "\n" + pad)
    add("plain-fullwidth-space", "\u3000天\u3000\tba\n天\u3000地\tbo\n\u3000\tda\n\u3000 \u3000玄 \u3000\tdo\n")

    # Space-separated tables.
    add("space-text-first", "天 ba\n地 bo\n天地 babo\n")
    add("space-code-first", "ba 天\nbo 地\nbabo 天地\n")
    add("space-code-words", "ba 天 地 玄\nbo 黄\nda 宇 5\ndo 宙 洪 7\nga 荒 $x 日\n")
    add("space-text-first-extra-words", "天 ba bo\n地 bo 5\n玄 da\n黄 do\n宇 ga\n")
    add("space-single-word", "天\n地 bo\n玄 da\n")
    add("space-runs", "天   ba\n地  bo\n  玄 da  \n")
    add("space-gb18030", "天 ba\n地 bo\n天地 babo\n".encode("gb18030"))
    add("space-utf16be-unmarked", "ba 天 地\nbo 玄\n".encode("utf-16-be"))
    add("space-text-rules", "天 b1\n地 " + "a" * 97 + "\n" + "字" * 81 + " bo\n玄\x07 da\n$x do\n" + pad_space)
    add("space-weights", "天 ba 5\n地 ba 9\n玄 ba\n")
    add("space-both-letters", "ab ba\ncd bo\n")
    add("space-with-inner-return", "天 b\ra\n地 bo\n玄 da\n")
    add("space-vertical-tab", "天\x0bba\n地 bo\n玄 da\n")
    add("mixed-one-tab-line", "天 ba\n地\tbo\n玄 da\n黄 do\n")
    add("mixed-tab-in-comment-only", "#a\tb\n天 ba\n地 bo\n")
    add("mixed-leading-tab-only", "\t天 ba\n地 bo\n")
    add("tab-code-with-spaces-columns", "ni hao\t你好\nni\t你\nhao\t好\n")

    # The [DATA] marker.
    for index, marker in enumerate(["[DATA]", "[Data]", "[data]", "[数据]", "[dAtA]", " [DATA] \r"]):
        add(f"marker-{index}", f"name=x\nnote\tzz\n{marker}\n天\tba\n地\tbo\n")
    add("marker-not-one", "[DATE]\n天\tba\n地\tbo\n[data ]\n[数据 ]\n")
    add("marker-twice", "[DATA]\n天\tba\n[DATA]\n地\tbo\n")
    add("marker-last-line", "天\tba\n地\tbo\n[DATA]")
    add("marker-space-table", "junk line here\n[DATA]\n天 ba\n地 bo\n")

    # Text rules.
    add("text-length", f"{'字' * 80}\tba\n{'字' * 81}\tbo\n{'a' * 80}\tda\n{'a' * 81}\tdo\n天\tga\n")
    add("text-length-marks", "".join(f"{unit * 80}\t{code_of(n)}\n{unit * 81}\t{code_of(n + 50)}\n" for n, unit in enumerate(
        ["q\u0303", "क्ष", "🇨🇳", "한", "नि", "กำ", "g\u0308", "👍🏽", "각", "ൎക", "ꙑ\u20dd"])) + "天\tzz\n")
    add("text-length-conjuncts", "".join(f"{unit * 40}\t{code_of(n)}\n{unit * 41}\t{code_of(n + 50)}\n" for n, unit in enumerate(
        ["क्षत्र", "ক্ষক", "क़्कक", "क्\u200dष", "ક્ષક", "କ୍ଷକ", "క్షక", "ക്ഷക", "က္ကက", "ក្កក", "क्ःकक"])) + pad)
    add("text-length-flags", f"{'🇨🇳' * 80}\tba\n{'🇨' * 159}\tbo\n{'🇨' * 161}\tda\n天\tdo\n")
    add("text-controls", "天\x07\tba\n地\x7f\tbo\n玄\x1b\tda\n黄\x85\tdo\n宇\u2028\tga\n宙\u2029\tgo\n日\tka\n月\tko\n星\tma\n辰\tmo\n" + pad)
    add("text-bidi", "".join(f"a{chr(value)}b\t{code_of(n)}\n" for n, value in enumerate(
        [0x061C, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069]))
        + "".join(f"{HAN[n]}\t{code_of(n + 100)}\n" for n in range(12)))
    add("text-format-and-private", "".join(f"a{chr(value)}b\t{code_of(n)}\n" for n, value in enumerate(
        [0x00AD, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0xE000, 0xF8FF, 0xF0000, 0x10FFFD, 0x0378, 0xFFFE, 0xE0001]))
        + "".join(f"{HAN[n]}\t{code_of(n + 100)}\n" for n in range(13)))
    add("text-spaces", "".join(f"a{chr(value)}b\t{code_of(n)}\n" for n, value in enumerate(
        [0x00A0, 0x1680, 0x2000, 0x2003, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000, 0x0020]))
        + "".join(f"{HAN[n]}\t{code_of(n + 100)}\n" for n in range(10)))
    add("text-invisible", "".join(f"a{chr(value)}b\t{code_of(n)}\n" for n, value in enumerate(
        [0x034F, 0x115F, 0x1160, 0x17B4, 0x180B, 0x180E, 0x3164, 0xFE00, 0xFE0F, 0xFFA0, 0xE0100, 0xE01EF]))
        + "❤\ufe0f\tzy\n" + "".join(f"{HAN[n]}\t{code_of(n + 100)}\n" for n in range(13)))
    add("text-marks", "e\u0301\u0302\u0303\u0304\tba\ne\u0301\u0302\u0303\u0304\u0305\tbo\n"
        "e\u0301\u0302x\u0303\u0304\u0305\tda\nक\u093e\u093f\u0940\u0941\u0942\tdo\na\u20dd\u20dd\u20dd\u20dd\u20dd\tga\n"
        "\u0301\tgo\ne\ufe00\ufe01\ufe02\ufe03\ufe04\tka\ne\u0301\u0301\u0301\u0301\ufe0f\tko\n天\tma\n地\tmo\n玄\tna\n")
    add("text-compatibility-ideographs", "".join(f"{chr(value)}\t{code_of(n)}\n" for n, value in enumerate(
        [0xFA0E, 0xFA10, 0xFA11, 0xF900, 0x3007, 0x2F00, 0x3400, 0x9FEF, 0x2A6D6, 0x2CEB0])))
    add("text-other-scripts", "α\tba\nβ\tbo\nαβ\tbabo\nא\tda\nب\tdo\n한글\tga\nคำ\tgo\n")
    add("text-ascii", "a b\tba\na\"b\tbo\n#x\tda\n;x\tdo\n[x]\tga\na=b\tgo\na,b\tka\n")

    # File-level rules.
    add("rule-valid-equals-invalid", "天\tba\n地\tbo\n玄\tb1\n黄\tb2\n")
    add("rule-valid-below-invalid", "天\tba\n地\tbo\n玄\tb1\n黄\tb2\n宇\tb3\n")
    add("rule-nothing-valid", "天\tb1\n地\tb2\n")
    add("rule-duplicates-count-as-valid", "α\tba\nα\tba\nα\tba\nβ\tb1\nγ\tb2\nδ\tb3\n")
    add("rule-duplicates-only-one-row", "α\tba\nα\tba\nα\tba\n")
    add("rule-one-row-other-script", "α\tba\n")
    add("rule-one-row-chinese", "天\tba\n")
    add("rule-one-row-chinese-pinyin", "你好\tnihao\n")
    add("rule-two-rows", "α\tba\nβ\tbo\n")
    add("rule-rows-at-cap", table(syllabary(5)), limits={"maximumRows": 5})
    add("rule-rows-over-cap", table(syllabary(6)), limits={"maximumRows": 5})
    add("rule-rows-over-cap-duplicates", table(syllabary(5) + syllabary(5)), limits={"maximumRows": 5})
    add("rule-rows-over-cap-repeated-overflow", table(syllabary(7) + syllabary(7)[5:]), limits={"maximumRows": 5})
    add("rule-rows-over-cap-and-invalid", table(syllabary(6)) + "天\tb1\n" * 9, limits={"maximumRows": 5})
    add("rule-bytes-at-cap", base + "#" * (200 - len(base.encode()) - 1) + "\n", limits={"maximumFileBytes": 200})
    add("rule-bytes-over-cap", base + "#" * (201 - len(base.encode()) - 1) + "\n", limits={"maximumFileBytes": 200})
    chinese = table([(HAN[n] + HAN[n + 1], code_of(n, 4)) for n in range(30)])
    add("entries-chinese-half", table([(HAN[n], code_of(n)) for n in range(5)] + [("αβγδε"[n], code_of(n + 9)) for n in range(5)]))
    add("entries-chinese-under-half", table([(HAN[n], code_of(n)) for n in range(4)] + [("αβγδε"[n], code_of(n + 9)) for n in range(5)]))
    add("entries-compatibility-ideographs", "﨎\tba\n﨏\tbo\n﨑\tda\nα\tdo\nβ\tga\n")
    add("entries-counted-before-joining-codes", "你好\tni hao\n你好\tnihao\nα\tba\nβ\tbo\n")
    add("entries-pinyin-codes", "你好\tnihao\n世界\tshijie\n中国\tzhong guo\n天地\ttiandi\n你\tni\n好\thao\n")
    add("entries-rows-at-limit", chinese, limits={"personalEntryRows": 30})
    add("entries-rows-over-limit", chinese, limits={"personalEntryRows": 29})
    add("entries-bytes-at-limit", chinese, limits={"personalEntryBytes": len(chinese.encode())})
    add("entries-bytes-over-limit", chinese, limits={"personalEntryBytes": len(chinese.encode()) - 1})
    add("entries-one-row-over-entry-bytes", "天\tba\n", limits={"personalEntryBytes": 3})

    # Rime dictionaries.
    head = "# Rime dictionary\n---\nname: sample\nversion: \"1\"\nsort: by_weight\n...\n"
    add("rime-basic", head + "天\tba\t5\n地\tba\t9\n天地\tbabo\n", file_name="sample.dict.yaml")
    add("rime-columns-block", "---\nname: sample\ncolumns:\n  - code\n  - text\n  - weight\n...\nba\t天\t5\nbo\t地\n", file_name="sample.dict.yaml")
    add("rime-columns-flow", "---\nname: sample\ncolumns: [ weight , text, \"code\" ]\n...\n5\t天\tba\n9\t地\tba\nx\t玄\tbo\n")
    add("rime-columns-with-stem", "---\nname: sample\ncolumns: [text, code, weight, stem]\n...\n天\tba\t5\tb\n地\tbo\t\tb\n玄\tda\n")
    add("rime-columns-no-code", "---\nname: sample\ncolumns: [text, weight]\n...\n天\t5\n地\t9\n")
    add("rime-columns-no-text", "---\nname: sample\ncolumns: [code, weight]\n...\nba\t5\nbo\t9\n")
    add("rime-columns-reset", "---\nname: sample\ncolumns: [code, text]\ncolumns:\n...\nba\t天\nbo\t地\n")
    add("rime-columns-empty-then-items", "---\nname: sample\ncolumns:\n- code\n- text\nother: 1\n- weight\n...\nba\t天\nbo\t地\n")
    add("rime-sort-original", "---\nname: sample\nsort: original\n...\n天\tba\t5\n地\tba\t9\n玄\tba\n黄\taa\t1\n")
    add("rime-sort-quoted", "---\nname: 'sample'\nsort: \"original\" # keep\n...\n天\tba\t5\n地\tba\t9\n")
    add("rime-name-quoted-comment", "---\nname: \"My Table\"   # the name\n...\nα\tba\nβ\tbo\n")
    add("rime-name-empty", "---\nname:\nversion: 1\n...\nα\tba\nβ\tbo\n")
    add("rime-name-missing", "---\nversion: \"1\"\nsort: original\n...\nα\tba\nβ\tbo\n")
    add("rime-name-after-marker", "---\nversion: 1\n...\nname: late\nα\tba\nβ\tbo\n")
    add("rime-name-indented", "---\n  name: inner\n...\nα\tba\nβ\tbo\n")
    add("rime-name-hidden-character", "---\nname: bad\u200bname\n...\nα\tba\nβ\tbo\n")
    add("rime-name-too-long", f"---\nname: {'名' * 41}\n...\nα\tba\nβ\tbo\n")
    add("rime-name-forty", f"---\nname: \u3000{'क्ष' * 40} \n...\nα\tba\nβ\tbo\n")
    add("rime-imports-single-file", "---\nname: sample\nimport_tables:\n  - sample.extra\n  - sample\n  - other\n...\nα\tba\nβ\tbo\n")
    add("rime-imports-flow", "---\nname: sample\nimport_tables: [one, 'two', sample, ]\n...\nα\tba\nβ\tbo\n")
    add("rime-comments", head + "# comment\nα\tba\n#x\tbo\n# no comment\n#y\tda\n# z\tdo\n")
    add("rime-no-comment-variants", head + "α\tba\n# no comment \n#y\tda\n" + "---\n")
    add("rime-rows", head + "α\n\tba\nβ\t\nγ\t \t5\nδ\tda\tx\nε\tdo\t5\textra\n ζ \t ga \t 7 \nη\tgo\t12345678901\n")
    add("rime-body-special-value", head + "$ddcmd(x)\tba\nα\tbo\n")
    add("rime-line-length", head + "α\tba\nβ\tbo\n" + "x" * 4094 + "\tb\n" + "x" * 4093 + "\tb" + " " * 9 + "\n")
    add("rime-marker-at-line-200", "---\nname: sample\n" + "# pad\n" * 197 + "...\nα\tba\nβ\tbo\n")
    add("rime-marker-at-line-201", "---\nname: sample\n" + "# pad\n" * 198 + "...\nα\tba\nβ\tbo\n")
    # The "..." line must start within the first 64 KiB.
    add("rime-header-64k", "---\nname: sample\n# " + "x" * 65515 + "\n...\nα\tba\nβ\tbo\n")
    add("rime-header-over-64k", "---\nname: sample\n# " + "x" * 65516 + "\n...\nα\tba\nβ\tbo\n")
    add("rime-marker-with-blanks", "---\nname: sample\n... \t\r\nα\tba\nβ\tbo\n")
    add("rime-marker-indented", "---\nname: sample\n ...\nα\tba\nβ\tbo\n")
    add("rime-no-body", "---\nname: sample\n...\n")
    add("rime-utf16", b"\xff\xfe" + (head + "天\tba\n地\tbo\n").encode("utf-16-le"))
    add("rime-gb18030", ("# 码表\n" + head + "天\tba\n地\tbo\n").encode("gb18030"))
    add("rime-crlf", (head + "天\tba\n地\tbo\n").replace("\n", "\r\n"))
    add("rime-spaced-codes", head + "你好\tni hao\n你\tni\n好\thao\n你好\tnihao\n")

    # Scheme and configuration files.
    schema = ("schema:\n  schema_id: sample\n  name: Sample\nswitches:\n  - name: ascii_mode\n    reset: 0\n"
              "engine:\n  processors:\n    - ascii_composer\n    - speller\ntranslator:\n  dictionary: sample\n  prism: sample\n")
    add("config-schema", schema, file_name="sample.schema.yaml")
    add("config-sixty-percent", "a: 1\nb: 2\nc: 3\nd: 4\ne: 5\nf: 6\nplain words\nmore words\nand more\nthe end\n")
    add("config-under-sixty-percent", "a: 1\nb: 2\nc: 3\nd: 4\ne: 5\nplain words\nmore words\nand more\nthe end\nlast one\n")
    add("config-with-tabs-half", "a: 1\nb: 2\nc:\t3\nd:\t4\n")
    add("config-with-tabs-under-half", "a: 1\nb: 2\nc: 3\nd:\t4\ne: 5\n")
    add("config-yaml-shapes", "---\n- item\n-item\nkey:\nkey:value\n\"k\": v\nk y: v\n: v\na/b@c.d-e_f: 1\n- \n")
    add("config-after-2000-lines", "天 ba\n" * 1 + "".join(f"{HAN[n]} {code_of(n)}\n" for n in range(1, 2000)) + "a: 1\n" * 4000)
    add("config-rime-like-without-marker", "name: sample\nversion: 1\nsort: original\n")

    # Phrase lists.
    add("phrase-code-position", "; Baidu mobile\nba=1,天\nba=2,地\nbo=1,玄黄\n[group]\nda=10,宇\nda=9,宙\n")
    add("phrase-code-comma-position", "ba,1=天\nba,2=地\nbo,1=玄黄\nda,10=宇\nda,9=宙\n")
    add("phrase-position-code", "1,ba=天\n2,ba=地\n1,bo=玄黄\n10,da=宇\n9,da=宙\n")
    add("phrase-utf16", b"\xff\xfe" + "ba=1,天\r\nba=2,地\r\nbo=1,玄黄\r\n".encode("utf-16-le"))
    add("phrase-utf16-unmarked", "ba=1,天\r\nba=2,地\r\nbo=1,玄黄\r\n".encode("utf-16-le"))
    add("phrase-gb18030", "ba=1,天\r\nba=2,地\r\nbo=1,玄黄\r\n".encode("gb18030"))
    add("phrase-positions", "ba=2,天\nba=1,地\nba=1,玄\nba=1234567890,黄\nba=999999999,宇\nba=0,宙\nba=00,洪\n")
    add("phrase-multi-line-empty-value", "ba,1=天\nbo,1=\nline one\nline two\nda,1=玄\ndo,1=\n[group]\nlost line\nga,1=黄\n")
    add("phrase-multi-line-backslash", "1,ba=天\n2,ba=地\n\\more of it\n\\and more\n1,bo=玄\n\\tail\n" + pad_phrases("1,{code}={text}"))
    add("phrase-backslash-first", "\\orphan\n1,ba=天\n2,ba=地\n")
    add("phrase-dynamic-values", "ba=1,#date\nbo=1,天\nda=1,地\nga=1, #x\n")
    add("phrase-malformed-lines", "ba=1,天\nplain line\nbo=1,地\nx=y\nda,1=玄\n=1,黄\nga=,宇\ngo=1,宙\n" + pad_phrases("{code}=1,{text}"))
    add("phrase-code-rules", "b1=1,天\nba bo=1,地\nBA=1,玄\n=1,黄\nda=1,宇\ndo=1,宙\n")
    add("phrase-text-rules", "ba=1, 天 \nbo=1,a=b,c\nda=1,\u200b\nga=1,\u3000地\u3000\ngo=1,$x\n")
    add("phrase-comments-and-groups", ";c\n#c\n[g]\nba=1,天\n [g] \n ;c\nbo=1,地\n#da=1,玄\n")
    add("phrase-line-length", "ba=1,天\nbo=1," + "x" * 4091 + "\nda=1," + "x" * 4090 + "\nga=1,地\n")
    add("phrase-held-row-before-long-line", "ba=1,天\nbo=1," + "x" * 5000 + "\n\\tail\nda=1,地\n")
    add("phrase-half", "ba=1,天\nbo=1,地\n玄\tda\n黄\tdo\n")
    add("phrase-under-half", "ba=1,天\nbo=1,地\n玄\tda\n黄\tdo\n宇\tga\n")
    add("phrase-mixed-grammars", "ba=1,天\nbo=1,地\nda=1,玄\ndo,1=黄\n1,ga=宇\n")
    add("phrase-grammar-edge", "a,b,1=天\n1,2=地\n1,=玄\n,1=黄\na,1x=宇\nba,1=宙\nbo,2=洪\nda,3=荒\ndo,4=日\n" + pad_phrases("{code},1={text}"))
    add("phrase-text-and-code-rules-padded", "b1=1,天\nba=1,地\x07\nbo=1,$x\nda=1," + "字" * 81 + "\n" + "a" * 97 + "=1,玄\n" + pad_phrases("{code}=1,{text}"))
    add("phrase-spaces", " ba = 1 , 天 \nbo=1,地\nda=1,玄\n")
    add("phrase-after-2000-plain-lines", "".join(f"{HAN[n]}\t{code_of(n)}\n" for n in range(2000)) + "ba=1,天\n" * 3000)
    add("phrase-one-row", "ba=1,α\n")
    add("phrase-lines-in-tab-table", "a=1,b\tba\nc=2,d\tbo\n天\tda\n")

    # How the table runs.
    add("run-by-syllable", table(singles + words(singles, 40)))
    add("run-whole-word", table(syllabary(40) + other_words(syllabary(40), 30)))
    add("run-no-words", table(syllabary(40)))
    plain_singles = syllabary(200)
    add("run-share-99-percent", table(plain_singles + words(plain_singles, 99) + other_words(plain_singles, 1)))
    add("run-share-under-99-percent", table(plain_singles + words(plain_singles, 197) + other_words(plain_singles, 3)))
    add("run-share-198-of-200", table(plain_singles + words(plain_singles, 198) + other_words(plain_singles, 2)))
    add("run-syllables-at-bound", table(syllabary(3500) + words(syllabary(3500), 5)))
    add("run-syllables-over-bound", table(syllabary(3501) + words(syllabary(3501), 5)))
    eight = syllabary(2500, letters=8)
    add("run-spellings-at-bound", table(eight + words(eight, 5)))
    add("run-spellings-over-bound", table(eight + [(HAN[3000], "q")] + words(eight, 5)))
    add("run-whole-row-unit-over-bound", table(syllabary(3499) + words(syllabary(3499), 300) + [(HAN[1] + HAN[2], "zzzzq"),
                                                                                              (HAN[2] + HAN[1], "zzzzr")]))
    add("run-optional-finals", table(syllabary(120, finals="ptxq") + words(syllabary(120, finals="ptxq"), 30)))
    add("run-finals-extended", table(singles + [(HAN[900 + n], code_of(n) + "pa") for n in range(20)] + words(singles, 20)))
    add("run-finals-too-few", table(syllabary(18, finals="pt") + words(syllabary(18, finals="pt"), 5)))
    add("run-finals-with-longer-unit", table(singles + words(singles, 30) + [(HAN[1] + HAN[2], "luckyt"), (HAN[3] + HAN[4], "luckyq")]))
    add("run-leading-characters", table(syllabary(30) + [(HAN[0] + HAN[1] + HAN[2] + HAN[3], code_of(0) + code_of(1)),
                                                         (HAN[4] + "，" + HAN[5], code_of(4) + code_of(5)),
                                                         ("，" + HAN[6] + "。", code_of(6))]))
    add("run-several-codes", table(syllabary(30) + [(HAN[n], code_of(n)[::-1] + "q") for n in range(10)]
                                   + [(HAN[0] + HAN[1], code_of(0)[::-1] + "q" + code_of(1)),
                                      (HAN[2] + HAN[3], code_of(2) + code_of(3)[::-1] + "q"),
                                      (HAN[2] + HAN[3], code_of(2)[::-1] + "q" + code_of(3)[::-1] + "q")]))
    add("run-nested-codes", table([("甲", "a" * n) for n in range(1, 25)] + [("乙", "b")]
                                  + [("甲" * 30 + "乙", "a" * 60 + "b"), ("甲" * 30, "a" * 61 + "c")]))
    add("run-merged-after-split", table(syllabary(10) + [(HAN[0] + HAN[1] + HAN[2], code_of(0) + code_of(1)),
                                                         (HAN[0] + HAN[1] + HAN[2], code_of(0) + code_of(1) + code_of(2)),
                                                         (HAN[0] + HAN[1] + HAN[2], code_of(0))]))
    add("run-spaced-and-joined", "你好\tni hao\n你好\tnihao\n你\tni\n好\thao\n世界\tshi jie\n世\tshi\n界\tjie\n")
    add("run-supplementary-plane", table([(chr(0x20000 + n), code_of(n)) for n in range(20)]
                                         + [(chr(0x20000 + n) + chr(0x20001 + n), code_of(n) + code_of(n + 1)) for n in range(10)]))
    add("run-decomposed-text-is-one-row", "é\tba\nè\tbo\néè\tbabo\n")
    # The engine's size budget. By syllable: long entries that share no leading codes do not
    # fit, and the table runs whole word. Whole word with long texts needs the exact check.
    big = syllabary(200)
    add("budget-syllable-does-not-fit", table(big + words(big, 3000, length=9, seed=5)))
    add("budget-syllable-needs-exact-check", table(big + words(big, 3000, length=5, seed=6)))
    add("budget-whole-needs-exact-check", table(big + [(text * 6, "zzq" + code_of(n, 4)) for n, (text, _) in
                                                       enumerate(words(big, 300, length=8, seed=7))]))
    add("budget-both-over-conservative-bound", table(big + [(text, code[:15]) for text, code in words(big, 800, length=60, seed=8)]))
    add("budget-short-pairs-fit", table(big + words(big, 3000, length=2, seed=9)))

    # ZIP archives.
    dictionary = (head + "天\tba\n地\tbo\n天地\tbabo\n").encode()
    other = ("---\nname: other\n...\nα\tga\nβ\tgo\n").encode()
    add("zip-one-table", Zip().add("sample.dict.yaml", dictionary).bytes(), "pack.zip")
    add("zip-stored", Zip().add("sample.dict.yaml", dictionary, method=0).bytes(), "pack.zip")
    add("zip-plain-table", Zip().add("words.txt", base.encode()).add("font.ttf", b"\x00\x01\x00\x00junk").bytes(), "pack.zip")
    add("zip-scheme-package", Zip().add("pkg/sample.schema.yaml", schema.encode()).add("pkg/sample.dict.yaml", dictionary)
        .add("pkg/setup.exe", b"MZ\x90\x00" + bytes(64)).add("pkg/rime.lua", b"os.execute('x')").add("pkg/readme.txt", b"Read me first.\nThanks.\n")
        .bytes(), "pack.zip")
    several = Zip().add("a/other.dict.yaml", other).add("b/sample.dict.yaml", dictionary).add("c/words.txt", base.encode())
    add("zip-several-tables", several.bytes(), "pack.zip")
    add("zip-several-tables-choose-0", several.bytes(), "pack.zip", choose=0)
    add("zip-several-tables-choose-2", several.bytes(), "pack.zip", choose=2)
    add("zip-several-tables-choose-missing", several.bytes(), "pack.zip", choose=7)
    add("zip-choice-for-one-table-wrong", Zip().add("sample.dict.yaml", dictionary).bytes(), "pack.zip", choose=3)
    add("zip-scheme-names-main", Zip().add("a/other.dict.yaml", other).add("b/sample.dict.yaml", dictionary)
        .add("sample.schema.yaml", schema.encode()).bytes(), "pack.zip")
    main = ("---\nname: main\nimport_tables:\n  - main.extra\n  - main.gone\n  - shared\n...\n天\tba\n地\tbo\n").encode()
    extra = ("---\nname: main.extra\n...\n玄\tda\n天\tba\n黄\tb1\n").encode()
    shared = ("---\nname: shared\ncolumns: [code, text]\n...\nga\t宇\n").encode()
    imports = Zip().add("dicts/main.dict.yaml", main).add("dicts/main.extra.dict.yaml", extra).add("shared.dict.yaml", shared)
    add("zip-import-tables", imports.bytes(), "pack.zip")
    add("zip-import-is-not-a-dictionary", Zip().add("main.dict.yaml", main).add("main.extra.dict.yaml", base.encode()).bytes(), "pack.zip")
    add("zip-import-becomes-plain-when-whole", Zip().add("main.dict.yaml", main).add(
        "main.extra.dict.yaml", ("---\nname: main.extra\n" + "# " + "x" * 70000 + "\n...\n玄\tda\n").encode()).bytes(), "pack.zip")
    add("zip-two-tables-importing-each-other", Zip().add("one.dict.yaml", b"---\nname: one\nimport_tables: [two]\n...\n\xce\xb1\tba\n")
        .add("two.dict.yaml", b"---\nname: two\nimport_tables: [one]\n...\n\xce\xb2\tbo\n").bytes(), "pack.zip")
    add("zip-no-table-names", Zip().add("setup.exe", b"MZ" + bytes(40)).add("font.ttf", b"x").add("notes.md", b"a\tb\n").bytes(), "pack.zip")
    add("zip-only-readme", Zip().add("readme.txt", b"Read me first.\nThen install.\nThanks a lot.\n").bytes(), "pack.zip")
    add("zip-only-scheme-file", Zip().add("sample.schema.yaml", schema.encode()).bytes(), "pack.zip")
    add("zip-only-binary-txt", Zip().add("data.txt", b"\x00\x01\x02\x03" * 30).bytes(), "pack.zip")
    add("zip-only-empty-txt", Zip().add("data.txt", b"").bytes(), "pack.zip")
    add("zip-two-not-tables", Zip().add("readme.txt", b"Read me first.\nThanks a lot.\n").add("sample.schema.yaml", schema.encode()).bytes(), "pack.zip")
    add("zip-nested-archive", Zip().add("inner.zip", Zip().add("sample.dict.yaml", dictionary).bytes()).bytes(), "pack.zip")
    add("zip-nested-archive-named-txt", Zip().add("inner.txt", Zip().add("sample.dict.yaml", dictionary).bytes()).bytes(), "pack.zip")
    add("zip-housekeeping", Zip().add("__MACOSX/._words.txt", base.encode()).add("._words.txt", base.encode())
        .add(".DS_Store", b"x").add("x/.ds_store.txt", base.encode()).add("x/__macosx/y.txt", base.encode())
        .add("words.TXT", base.encode()).add(".txt", base.encode()).add("folder.txt/", b"").bytes(), "pack.zip")
    add("zip-backslash-housekeeping", Zip().add("__MACOSX\\words.txt", base.encode()).add("real\\words.tsv", base.encode()).bytes(), "pack.zip")
    add("zip-suffixes", Zip().add("a.ini", b"ba=1,\xce\xb1\nbo=1,\xce\xb2\n").add("b.tsv", base.encode()).add("c.yaml", other)
        .add("d.csv", base.encode()).add("e.dict.yml", other).bytes(), "pack.zip")
    add("zip-encrypted", Zip().add("sample.dict.yaml", dictionary, flags=1).bytes(), "pack.zip")
    add("zip-strong-encryption-flag", Zip().add("sample.dict.yaml", dictionary, flags=0x40).bytes(), "pack.zip")
    add("zip-masked-directory-flag", Zip().add("sample.dict.yaml", dictionary, flags=0x2000).bytes(), "pack.zip")
    add("zip-encrypted-beside-table", Zip().add("secret.txt", base.encode(), flags=1).add("words.txt", base.encode()).bytes(), "pack.zip")
    add("zip-encrypted-not-a-candidate", Zip().add("secret.bin", b"xx", flags=1).add("words.txt", base.encode()).bytes(), "pack.zip")
    add("zip-method-bzip2", Zip().add("words.txt", base.encode(), method=12, raw=b"BZh9junk").bytes(), "pack.zip")
    add("zip-method-unknown-beside-table", Zip().add("a.txt", base.encode(), method=14, raw=b"junk").add("words.txt", base.encode()).bytes(), "pack.zip")
    add("zip-encrypted-and-unknown-method", Zip().add("a.txt", base.encode(), method=14, raw=b"junk").add("b.txt", base.encode(), flags=1).bytes(), "pack.zip")
    add("zip-data-descriptor", Zip().add("words.txt", base.encode(), flags=8, local_sizes=(0, 0, 0)).bytes(), "pack.zip")
    add("zip-utf8-flag-name", Zip().add("词库/码表.txt", base.encode(), flags=0x800).bytes(), "pack.zip")
    add("zip-gbk-name", Zip().add("词库/示例.dict.yaml".encode("gbk"), dictionary).add("另一个.txt".encode("gbk"), base.encode()).bytes(), "pack.zip")
    gbk = "示例.txt".encode("gbk")
    add("zip-unicode-path", Zip().add(gbk, base.encode(), extra=unicode_path(gbk, "表格.txt")).add(b"b.txt", base.encode(),
        extra=unicode_path(b"other", "wrong-checksum.txt")).add("c.txt", base.encode(), flags=0x800, extra=unicode_path(b"c.txt", "ignored.txt")).bytes(), "pack.zip")
    add("zip-name-undecodable", Zip().add(b"\xff\xfe\x80.txt", base.encode()).add(b"z.txt", base.encode()).bytes(), "pack.zip")
    add("zip-name-hidden-characters", Zip().add("a\u200bb\u202ec\x07.txt", base.encode()).add("z.txt", base.encode()).bytes(), "pack.zip")
    add("zip-comment", Zip().add("words.txt", base.encode()).bytes(comment=b"made by hand PK\x05\x06 not an end record"), "pack.zip")
    add("zip-comment-length-wrong", Zip().add("words.txt", base.encode()).bytes(comment=b"abc") + b"x", "pack.zip")
    add("zip-utf16-member", Zip().add("words.txt", b"\xff\xfe" + base.encode("utf-16-le")).bytes(), "pack.zip")
    add("zip-gb18030-member", Zip().add("words.txt", base.encode("gb18030")).bytes(), "pack.zip")
    long_head = "".join(f"{HAN[n % 4000]}\t{code_of(n, 4)}\n" for n in range(12000))
    add("zip-member-longer-than-head", Zip().add("words.txt", long_head.encode()).bytes(), "pack.zip")
    add("zip-utf16-member-longer-than-head", Zip().add("words.txt", b"\xff\xfe" + long_head.encode("utf-16-le")).bytes(), "pack.zip")
    add("zip-utf16-unmarked-member-longer-than-head", Zip().add("words.txt", ("𠀀\tba\n" + "𠀁" * 40000 + "\tbo\n").encode("utf-16-le")).bytes(), "pack.zip")
    add("zip-gb18030-member-longer-than-head", Zip().add("words.txt", long_head.encode("gb18030")).bytes(), "pack.zip")
    add("zip-head-one-long-line", Zip().add("words.txt", ("天" * 30000 + "\tba\n地\tbo\n").encode()).bytes(), "pack.zip")
    add("zip-head-table-rest-not", Zip().add("words.txt", (base + "not a row at all\n" * 9000).encode()).bytes(), "pack.zip")
    add("zip-head-readme-rest-table", Zip().add("words.txt", ("Read me first.\n" * 6000 + long_head).encode()).bytes(), "pack.zip")
    add("zip-header-beyond-head", Zip().add("sample.dict.yaml", ("---\nname: sample\n" + "# " + "x" * 400 + "\n") .encode() * 1
        + ("# " + "y" * 500 + "\n").encode() * 150 + b"...\n\xce\xb1\tba\n\xce\xb2\tbo\n").bytes(), "pack.zip")
    # Irregular archives.
    good = Zip().add("words.txt", base.encode())
    add("zip-zip64-count", good.bytes(total=0xFFFF), "pack.zip")
    add("zip-zip64-locator", good.bytes(locator=True), "pack.zip")
    add("zip-zip64-extra", Zip().add("words.txt", base.encode(), extra=struct.pack("<HHQ", 1, 8, 5)).bytes(), "pack.zip")
    add("zip-zip64-size", Zip().add("words.txt", base.encode(), declared=0xFFFFFFFF).bytes(), "pack.zip")
    add("zip-multi-disk", good.bytes(disk=1), "pack.zip")
    add("zip-multi-disk-entry", good.bytes(entry_disk=1), "pack.zip")
    add("zip-count-mismatch", good.bytes(total=2), "pack.zip")
    add("zip-count-too-small", Zip().add("a.txt", base.encode()).add("b.txt", base.encode()).bytes(total=1), "pack.zip")
    add("zip-gap-before-end", good.bytes(gap=b"hidden"), "pack.zip")
    add("zip-directory-size-wrong", good.bytes(directory_size=10), "pack.zip")
    add("zip-directory-offset-wrong", good.bytes(directory_offset=3), "pack.zip")
    add("zip-truncated", good.bytes()[:-30], "pack.zip")
    add("zip-only-local-header", good.bytes()[:40], "pack.zip")
    add("zip-extra-field-overrun", Zip().add("words.txt", base.encode(), extra=struct.pack("<HH", 0x9999, 50) + b"ab").bytes(), "pack.zip")
    # One member's bytes lie inside another's: the stored member holds a whole local entry.
    inner = Zip().add("words.txt", base.encode())
    outer = Zip().add("holder.bin", bytes(inner.body), method=0)
    outer.entries.append(inner.entries[0][:7] + (30 + len(b"holder.bin"),))
    add("zip-overlapping-members", outer.bytes(), "pack.zip")
    overlap = Zip().add("a.txt", base.encode())
    overlap.entries.append((b"a.txt", 0, 8, overlap.entries[0][3], overlap.entries[0][4], overlap.entries[0][5], b"", 0))
    add("zip-duplicate-names", overlap.bytes(), "pack.zip")
    add("zip-empty-name", Zip().add("", base.encode()).bytes(), "pack.zip")
    add("zip-local-name-differs", Zip().add("words.txt", base.encode(), local_name=b"other.txt").bytes(), "pack.zip")
    add("zip-local-flags-differ", Zip().add("words.txt", base.encode(), local_flags=0x800).bytes(), "pack.zip")
    add("zip-local-method-differs", Zip().add("words.txt", base.encode(), local_method=0).bytes(), "pack.zip")
    add("zip-local-sizes-differ", Zip().add("words.txt", base.encode(), local_sizes=(0, 1, 2)).bytes(), "pack.zip")
    add("zip-local-offset-wrong", Zip().add("pad.bin", b"x" * 50, method=0).add("words.txt", base.encode(), offset=7, local_name=b"pad.bin").bytes(), "pack.zip")
    add("zip-data-runs-into-directory", Zip().add("words.txt", base.encode(), packed=5000).bytes(), "pack.zip")
    for index, path in enumerate(["../words.txt", "/words.txt", "C:/words.txt", "a/../../words.txt", "a\\..\\words.txt",
                                  "..", "c:\\words.txt", "a/..b/words.txt", "cc:/words.txt"]):
        add(f"zip-path-{index}", Zip().add(path, base.encode()).bytes(), "pack.zip")
    add("zip-unsafe-path-not-a-table", Zip().add("../setup.exe", b"MZ").add("words.txt", base.encode()).bytes(), "pack.zip")
    add("zip-crc-mismatch", Zip().add("words.txt", base.encode(), crc=1).bytes(), "pack.zip")
    add("zip-crc-mismatch-not-chosen", Zip().add("a.txt", base.encode(), crc=1).add("b.dict.yaml", dictionary).bytes(), "pack.zip", choose=1)
    add("zip-size-declared-larger", Zip().add("words.txt", base.encode(), declared=len(base.encode()) + 1).bytes(), "pack.zip")
    add("zip-size-declared-smaller", Zip().add("words.txt", base.encode(), declared=3).bytes(), "pack.zip")
    deflated = zlib.compressobj(6, zlib.DEFLATED, -15)
    stream = deflated.compress(base.encode()) + deflated.flush()
    add("zip-deflate-truncated", Zip().add("words.txt", base.encode(), raw=stream[:-3]).bytes(), "pack.zip")
    add("zip-deflate-trailing-bytes", Zip().add("words.txt", base.encode(), raw=stream + b"extra").bytes(), "pack.zip")
    add("zip-deflate-garbage", Zip().add("words.txt", base.encode(), raw=b"\xff\xff\xff\xff").bytes(), "pack.zip")
    add("zip-deflate-empty", Zip().add("words.txt", base.encode(), raw=b"").bytes(), "pack.zip")
    add("zip-deflate-garbage-not-a-candidate", Zip().add("a.bin", b"x", raw=b"\xff\xff").add("words.txt", base.encode()).bytes(), "pack.zip")
    add("zip-deflate-garbage-beside-table", Zip().add("a.txt", b"x", raw=b"\xff\xff").add("words.txt", base.encode()).bytes(), "pack.zip")
    add("zip-stored-size-differs", Zip().add("words.txt", base.encode(), method=0, raw=base.encode() + b"x\ty\n").bytes(), "pack.zip")
    # Caps, crossed by small files under lowered limits.
    add("zip-archive-at-cap", good.bytes(), "pack.zip", limits={"maximumArchiveBytes": len(good.bytes())})
    add("zip-archive-over-cap", good.bytes(), "pack.zip", limits={"maximumArchiveBytes": len(good.bytes()) - 1})
    three = Zip().add("a.bin", b"x").add("b.bin", b"y").add("words.txt", base.encode())
    add("zip-members-at-cap", three.bytes(), "pack.zip", limits={"maximumArchiveMembers": 3})
    add("zip-members-over-cap", three.bytes(), "pack.zip", limits={"maximumArchiveMembers": 2})
    add("zip-member-at-cap", good.bytes(), "pack.zip", limits={"maximumMemberBytes": len(base.encode())})
    add("zip-member-over-cap", good.bytes(), "pack.zip", limits={"maximumMemberBytes": len(base.encode()) - 1})
    add("zip-stored-member-over-cap", Zip().add("words.txt", base.encode(), method=0).bytes(), "pack.zip",
        limits={"maximumMemberBytes": len(base.encode()) - 1})
    add("zip-member-over-cap-declared-small", Zip().add("words.txt", base.encode(), declared=2).bytes(), "pack.zip",
        limits={"maximumMemberBytes": 10})
    total = len(main) + len(extra) + len(shared)
    add("zip-import-at-cap", imports.bytes(), "pack.zip", limits={"maximumImportBytes": total})
    add("zip-import-over-cap", imports.bytes(), "pack.zip", limits={"maximumImportBytes": total - 1})
    add("zip-import-cap-below-first-table", imports.bytes(), "pack.zip", limits={"maximumImportBytes": len(main) - 1})
    add("zip-import-cap-exactly-first-table", imports.bytes(), "pack.zip", limits={"maximumImportBytes": len(main)})
    add("zip-rows-over-cap", Zip().add("words.txt", table(syllabary(6)).encode()).bytes(), "pack.zip", limits={"maximumRows": 5})
    add("zip-table-over-file-cap-is-read", good.bytes(), "pack.zip", limits={"maximumFileBytes": 10})
    add("zip-entries-by-declared-size", Zip().add("words.txt", chinese.encode()).bytes(), "pack.zip",
        limits={"personalEntryBytes": len(chinese.encode()) - 1})

    if large:
        many = [(HAN[n % 4000] + HAN[(n // 4000) % 4000], code_of(n, 5)) for n in range(300_001)]
        add("large-rows-at-cap", table(many[:300_000]))
        add("large-rows-over-cap", table(many))
        padding = "# " + "x" * 1021 + "\n"
        add("large-bytes-at-cap", base + padding * (16 * 1024 - 1) + "#" * (1023 - len(base.encode())) + "\n")
        add("large-bytes-over-cap", base + padding * (16 * 1024 - 1) + "#" * (1024 - len(base.encode())) + "\n")
        add("large-over-entry-bytes", chinese + padding * 2048)
        add("large-zip-member-at-cap", Zip().add("words.txt", (base + padding * (16 * 1024 - 1) + "#" * (1023 - len(base.encode())) + "\n").encode()).bytes(), "pack.zip")
        add("large-zip-member-over-cap", Zip().add("words.txt", (base + padding * (16 * 1024)).encode()).bytes(), "pack.zip")
        part = ("---\nname: {}\n...\n" + "α\tba\n" + padding * (15 * 1024)).encode()
        add("large-zip-import-over-cap", Zip().add("main.dict.yaml", b"---\nname: main\nimport_tables: [one, two]\n...\n\xce\xb2\tbo\n" + padding.encode() * (15 * 1024))
            .add("one.dict.yaml", part.replace(b"{}", b"one")).add("two.dict.yaml", part.replace(b"{}", b"two")).bytes(), "pack.zip")
        pad = Zip().add("pad.bin", bytes(64 * 1024 * 1024), method=0).add("words.txt", base.encode())
        add("large-zip-archive-over-cap", pad.bytes(), "pack.zip")
        add("large-zip-members-at-cap", _with_table(511, base), "pack.zip")
        add("large-zip-members-over-cap", _with_table(512, base), "pack.zip")
    return cases


def _with_table(count, base):
    archive = Zip()
    for n in range(count):
        archive.add(f"f{n}.bin", b"x", method=0)
    return archive.add("words.txt", base.encode()).bytes()


def write(directory, large=False):
    """Writes the corpus and returns the cases as cases.json lists them."""
    directory = Path(directory)
    listed = []
    for name, file_name, data, limits, choose in build(large):
        folder = directory / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / file_name).write_bytes(data)
        case = {"name": name, "path": str(folder / file_name), "fileName": file_name}
        if limits:
            case["limits"] = limits
        if choose is not None:
            case["table"] = choose
        listed.append(case)
    (directory / "cases.json").write_text(json.dumps(listed, ensure_ascii=False, indent=1), encoding="utf-8")
    return listed


if __name__ == "__main__":
    arguments = [argument for argument in sys.argv[1:] if argument != "--large"]
    if len(arguments) != 1:
        sys.exit("usage: generate_corpus.py OUTPUT_DIRECTORY [--large]")
    print(f"{len(write(arguments[0], '--large' in sys.argv))} cases written to {arguments[0]}")
