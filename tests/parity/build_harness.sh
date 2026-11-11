#!/usr/bin/env bash
# Builds the importer report tool from the ReRime App repository's own importer sources
# (macOS, swiftc). Nothing of the App repository is copied into this one.
#
#   bash tests/parity/build_harness.sh /path/to/re_rime /path/to/output/importer-report
set -euo pipefail
app="${1:?usage: build_harness.sh APP_REPO OUTPUT}"
output="${2:?usage: build_harness.sh APP_REPO OUTPUT}"
here="$(cd "$(dirname "$0")" && pwd)"
core="$app/ios/ReRime/ReRime/UserTable"
# The importer core: pure Swift and Foundation, no UI. UserTableDoors.swift is not compiled
# whole (its last type needs the App's install state); only its first part, the door rules
# up to the keyboard specimen, is taken, into a temporary file outside both repositories.
work="$(mktemp -d "${TMPDIR:-/tmp}/rerime-importer-report.XXXXXX")"
trap 'rm -rf "$work"' EXIT
awk '/^\/\/\/ Product requirement 14/ { exit } { print }' "$core/UserTableDoors.swift" > "$work/UserTableDoorsRules.swift"
swiftc -O -o "$output" \
  "$here/main.swift" \
  "$core/UserTableImportTypes.swift" \
  "$core/UserTableImporter.swift" \
  "$core/UserTableSourceRecognizer.swift" \
  "$core/UserTableRowReaders.swift" \
  "$core/UserTableRowCollector.swift" \
  "$core/UserTableTextDecoder.swift" \
  "$core/UserTableZipReader.swift" \
  "$core/UserTableAnalysis.swift" \
  "$core/UserTableCanonicalWriter.swift" \
  "$app/ios/ReRime/Shared/UserTableScheme.swift" \
  "$work/UserTableDoorsRules.swift"
echo "built $output"
