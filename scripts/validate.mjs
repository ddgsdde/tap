import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const LATEST = join(ROOT, "data", "latest");
const manifestPath = join(LATEST, "manifest.json");
if (!existsSync(manifestPath)) throw new Error("data/latest/manifest.json is missing; run npm run scan first");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

for (const file of manifest.files) {
  const path = join(LATEST, file.path);
  if (!existsSync(path)) throw new Error(`manifest file missing: ${file.path}`);
  const actual = sha256(path);
  if (actual !== file.sha256) throw new Error(`hash mismatch: ${file.path}`);
}

const tasks = JSON.parse(readFileSync(join(LATEST, "protocol", "tasks.json"), "utf8"));
if (tasks.taskCount !== tasks.tasks.length) throw new Error("task count mismatch");
const taskIds = new Set(tasks.tasks.map((task) => Number(task.taskId)));
if (taskIds.size !== tasks.tasks.length) throw new Error("duplicate task IDs");

const official = JSON.parse(readFileSync(join(LATEST, "protocol", "processors-official.json"), "utf8"));
let slots = 0;
let occupied = 0;
let netlists = 0;
for (const processor of official.processors) {
  const slug = processor.configName.replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
  const board = JSON.parse(readFileSync(join(LATEST, "leaderboards", `${slug}.json`), "utf8"));
  if (board.rows.length !== tasks.taskCount) throw new Error(`${slug}: incomplete leaderboard`);
  if (new Set(board.rows.map((row) => Number(row.taskId))).size !== tasks.taskCount) throw new Error(`${slug}: duplicate leaderboard tasks`);
  for (const row of board.rows) {
    slots++;
    if (!taskIds.has(Number(row.taskId))) throw new Error(`${slug}: unknown task ${row.taskId}`);
    if (row.empty) continue;
    occupied++;
    const expected = BigInt(row.area) * BigInt(Math.max(Number(row.depth), 1)) ** 3n;
    if (expected !== BigInt(row.cost)) throw new Error(`${slug} task ${row.taskId}: invalid cost`);
    if (!row.netlist) throw new Error(`${slug} task ${row.taskId}: missing netlist pointer`);
    const netlistPath = join(LATEST, row.netlist);
    if (!existsSync(netlistPath)) throw new Error(`${slug} task ${row.taskId}: missing netlist file`);
    const netlist = JSON.parse(readFileSync(netlistPath, "utf8"));
    if (String(netlist.circuit.circuitId) !== String(row.circuitId)) throw new Error(`${slug} task ${row.taskId}: circuit ID mismatch`);
    if (Number(netlist.task.taskId) !== Number(row.taskId)) throw new Error(`${slug} task ${row.taskId}: netlist task mismatch`);
    if (netlist.decoded.byteLength * 2 !== netlist.rawNetlist.length - 2) throw new Error(`${slug} task ${row.taskId}: netlist byte length mismatch`);
    netlists++;
  }
}

if (slots !== manifest.coverage.leaderboardSlotsRead) throw new Error("manifest leaderboard coverage mismatch");
if (occupied !== manifest.coverage.occupiedLeaderboardSlots) throw new Error("manifest occupied coverage mismatch");
if (netlists !== manifest.coverage.netlistsExported) throw new Error("manifest netlist coverage mismatch");

const transistorMarket = JSON.parse(readFileSync(join(LATEST, "markets", "transistors-raw.json"), "utf8"));
const circuitMarket = JSON.parse(readFileSync(join(LATEST, "markets", "circuits-raw.json"), "utf8"));
if (!Array.isArray(transistorMarket.tokens) || !Array.isArray(transistorMarket.openBids)) throw new Error("bad transistor market snapshot");
if (!Array.isArray(circuitMarket.listings) || !Array.isArray(circuitMarket.trades)) throw new Error("bad circuit market snapshot");

console.log(JSON.stringify({
  ok: true,
  block: manifest.block.number,
  tasks: tasks.taskCount,
  officialProcessors: official.processors.length,
  leaderboardSlots: slots,
  occupiedSlots: occupied,
  netlists,
  filesVerified: manifest.files.length,
}, null, 2));
