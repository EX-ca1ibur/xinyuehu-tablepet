/**
 * Validate the installed 心月狐 pet with the DSH pet plugin's own resolver,
 * so we know the GUI will accept it (and not warn it away).
 */
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const DSH_HOME = process.env.DSH_HOME || join(homedir(), '.dsh')
const PLUGIN = join(DSH_HOME, 'profiles', 'web', 'node_modules',
                    '@linxin666', 'dsh-pet', 'lib', 'index.js')
const PET_DIR = join(homedir(), '.codex', 'pets', 'hsin-moon-fox')

const mod = await import(pathToFileURL(PLUGIN).href)
console.log('plugin exports:', Object.keys(mod).filter(k => /pet|registr|manifest|scan/i.test(k)).join(', '))

const raw = JSON.parse(readFileSync(join(PET_DIR, 'pet.json'), 'utf8'))

if (mod.PET_ROW_ORDER) {
  console.log('row order :', mod.PET_ROW_ORDER.join(', '))
  console.log('cell      :', mod.DEFAULT_PET_CELL, 'cols', mod.DEFAULT_PET_COLUMNS,
    'frames', JSON.stringify(mod.DEFAULT_FRAME_COUNTS))
}

if (mod.resolvePetManifest) {
  const entry = mod.resolvePetManifest(raw, PET_DIR, { warnings: [], diagnostics: [] })
  console.log('resolved  :', entry === undefined ? 'REJECTED' : 'ok')
  if (entry) {
    console.log('  id      :', entry.id, '|', entry.displayName)
    console.log('  cell    :', entry.cell?.width + 'x' + entry.cell?.height)
    console.log('  columns :', entry.columns, '| atlasRows', entry.atlasRows)
    console.log('  frames  :', JSON.stringify(entry.frames))
    console.log('  tracks  :', Object.keys(entry.tracks ?? {}).join(', '))
    console.log('  sheet   :', entry.spritesheetPath ?? entry.spritesheet)
  }
}

if (mod.loadPetRegistry) {
  try {
    const base = mod.petCodexPetsDir ? mod.petCodexPetsDir() : undefined
  } catch { /* ignore */ }
  const reg = mod.loadPetRegistry({
    petsDir: join(homedir(), '.codex', 'pets'),
    assetsDir: 'C:/nonexistent-assets',
    diagnostics: [],
    warnings: [],
  })
  const entries = Array.isArray(reg) ? reg : (reg?.pets ?? reg?.entries ?? [])
  console.log('registry entries:', entries.length)
  for (const e of entries) {
    console.log('  -', e.id, '|', e.displayName, '| frames', JSON.stringify(e.frames))
  }
  if (reg?.diagnostics?.length) {
    for (const d of reg.diagnostics) console.log(`  [${d.level}] ${d.message}`)
  }
  if (reg?.warnings?.length) for (const w of reg.warnings) console.log('  warn:', w)
}
