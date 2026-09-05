import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(here, '../..')
const composeFile = path.join(repoRoot, 'performance', 'docker-compose.performance.yml')

export function sqlLiteral(value: string) {
  return `'${value.replaceAll("'", "''")}'`
}

export function query(sql: string) {
  const result = spawnSync(
    'docker',
    [
      'compose', '-p', 'ticketing-phase10a', '-f', composeFile,
      'exec', '-T', 'postgres', 'psql', '-X', '-U', 'ticketing', '-d', 'ticketing',
      '-v', 'ON_ERROR_STOP=1', '-At', '-F', '\t', '-c', sql,
    ],
    { cwd: repoRoot, encoding: 'utf8' },
  )
  if (result.status !== 0) {
    throw new Error(`psql failed (${result.status}): ${result.stderr}\nSQL: ${sql}`)
  }
  return result.stdout.trim()
}

export function row(sql: string) {
  const output = query(sql)
  if (!output) throw new Error(`query returned no rows: ${sql}`)
  return output.split('\t')
}
