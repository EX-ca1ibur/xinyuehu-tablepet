/**
 * Minimal asar reader: locate files by name and grep them, without Electron's
 * asar support (this Node cannot follow the virtual paths).
 *
 * asar layout: [8-byte pickle header][4-byte size][4-byte json length][json][blobs]
 */
import { openSync, readSync, closeSync, statSync } from 'node:fs'

const ARCHIVE = process.argv[2] ?? 'D:/dsh/resources/app.asar'
const PATTERN = new RegExp(process.argv[3] ?? 'usage-ledger|accruedCny|spendWatch', 'i')
const MAX_FILE = 4_000_000

function readHeader(fd) {
  const head = Buffer.alloc(16)
  readSync(fd, head, 0, 16, 0)
  const jsonLen = head.readUInt32LE(12)
  const json = Buffer.alloc(jsonLen)
  readSync(fd, json, 0, jsonLen, 16)
  return { header: JSON.parse(json.toString('utf8')), base: 16 + jsonLen }
}

function walk(node, prefix, out) {
  for (const [name, entry] of Object.entries(node.files ?? {})) {
    const path = `${prefix}/${name}`
    if (entry.files) walk(entry, path, out)
    // entries flagged `unpacked` live in the .unpacked directory next to the
    // archive and carry no offset inside it, so they cannot be read here.
    else if (entry.size !== undefined && entry.offset !== undefined && !entry.unpacked) {
      out.push({ path, offset: Number(entry.offset), size: entry.size })
    }
  }
}

const fd = openSync(ARCHIVE, 'r')
try {
  const { header, base } = readHeader(fd)
  const files = []
  walk(header, '', files)
  console.log(`archive ${ARCHIVE}: ${files.length} files, data base ${base}`)
  const broken = files.filter(f => !Number.isFinite(Number(f.offset)))
  console.log(`entries without a usable offset: ${broken.length}`)
  if (broken.length) {
    console.log('sample entries:', JSON.stringify(files.slice(0, 3)))
    console.log('sample broken :', JSON.stringify(broken.slice(0, 3)))
  }

  const hits = []
  let bytesRead = 0
  for (const f of files) {
    if (f.size > MAX_FILE || f.size === 0) continue
    if (!/\.(js|mjs|cjs|json|ts)$/.test(f.path) || f.path.endsWith('.map')) continue
    const buf = Buffer.alloc(f.size)
    readSync(fd, buf, 0, f.size, base + Number(f.offset))
    bytesRead += f.size
    const text = buf.toString('utf8')
    const m = text.match(PATTERN)
    if (m) {
      const at = m.index ?? 0
      hits.push({ path: f.path, snippet: text.slice(Math.max(0, at - 200), at + 400).replace(/\s+/g, ' ') })
    }
  }
  console.log(`scanned ${(bytesRead / 1e6).toFixed(1)} MB, ${hits.length} files match ${PATTERN}`)
  for (const h of hits.slice(0, 12)) {
    console.log(`\n--- ${h.path}\n    ${h.snippet.slice(0, 520)}`)
  }
} finally {
  closeSync(fd)
}
