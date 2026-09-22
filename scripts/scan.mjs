import {
  Contract,
  Interface,
  JsonRpcProvider,
  formatEther,
  getBytes,
  getAddress,
  keccak256,
  solidityPackedKeccak256,
} from "ethers";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DATA = join(ROOT, "data");
const STAGING = join(DATA, ".staging", "latest");
const LATEST = join(DATA, "latest");
const CHANGES = join(DATA, "changes");
const HISTORY = join(DATA, "history");
const REFERENCE = join(DATA, "reference");

const URLS = {
  config: "https://tapeout.net/pod/pod-mainnet.json",
  vectors: "https://tapeout.net/pod/pod-vectors-all.json",
  transistorMarket: "https://tapeout.net/market.json",
  circuitMarket: "https://tapeout.net/circuit-market.json",
  dexBem: "https://api.dexscreener.com/latest/dex/tokens/0x5ce033B2bFCa3Af30b3e8C8457DeaF776A8b695a",
  bnbUsd: "https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT",
};

const RPC_URLS = (process.env.TAPEOUT_RPC_URLS || [
  "https://bsc-rpc.publicnode.com",
  "https://bsc-dataseed.binance.org",
  "https://rpc-bsc.48.club",
].join(",")).split(",").map((x) => x.trim()).filter(Boolean);

const MULTICALL_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11";
const MULTICALL_ABI = [
  "function aggregate3(tuple(address target,bool allowFailure,bytes callData)[] calls) view returns(tuple(bool success,bytes returnData)[] returnData)",
];

const MINING_ABI = [
  "function bestSlot(uint32,address) view returns(uint64 holderPlus1,uint256 cost)",
  "function getMiner(bytes32) view returns(tuple(address circuits,uint64 circuitId,uint32 taskId,uint32 gateCount,uint32 stateCount,uint32 depth,uint64 area,uint32 mult,uint64 since,uint8 status,address registrant,uint32 nandBurn,uint32 latchBurn,uint64 bstar,uint64 bonus,bool optimal,uint128 verifWeight,uint128 unverWeight,uint256 debt))",
];
const CIRCUITS_ABI = [
  "function circuitInfo(uint256) view returns(uint32 nIn,uint32 nOut,uint32 nState,uint32 gateCount)",
  "function netlist(uint256) view returns(bytes)",
  "function ownerOf(uint256) view returns(address)",
  "function name() view returns(string)",
  "function symbol() view returns(string)",
  "function transistors() view returns(address)",
  "function nextId() view returns(uint256)",
  "function factory() view returns(address)",
];
const TRANSISTORS_ABI = [
  "function cpuName() view returns(string)",
  "function cpuSymbol() view returns(string)",
  "function story() view returns(string)",
  "function creator() view returns(address)",
  "function circuits() view returns(address)",
  "function mintPrice() view returns(uint256)",
  "function minted() view returns(uint256)",
  "function supplyCap() view returns(uint256)",
  "function protocolFee() view returns(uint256)",
  "function protocolWallet() view returns(address)",
  "function NAND() view returns(uint256)",
  "function LATCH() view returns(uint256)",
];
const FACTORY_ABI = [
  "function cpuCount() view returns(uint256)",
  "function cpuAt(uint256) view returns(address)",
  "function deployFee() view returns(uint256)",
];

function jsonValue(_key, value) {
  return typeof value === "bigint" ? value.toString() : value;
}

function writeJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, jsonValue, 2)}\n`);
}

function writeText(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, value);
}

function sha256Buffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function sha256File(path) {
  return sha256Buffer(readFileSync(path));
}

function slug(value) {
  return String(value).replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
}

function wei(value) {
  return BigInt(value ?? 0);
}

function amount(weiValue) {
  return { wei: BigInt(weiValue).toString(), bnb: formatEther(BigInt(weiValue)) };
}

async function fetchJson(url, { optional = false } = {}) {
  let lastError;
  for (let attempt = 0; attempt < 4; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30_000);
    try {
      const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`, {
        headers: { "user-agent": "ddgsdde/tap chain-data scanner" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return await response.json();
    } catch (error) {
      lastError = error;
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 800 * (attempt + 1)));
    } finally {
      clearTimeout(timer);
    }
  }
  if (optional) return { unavailable: true, error: String(lastError?.message || lastError), source: url };
  throw new Error(`failed to fetch ${url}: ${lastError?.message || lastError}`);
}

async function mapLimit(items, concurrency, callback) {
  const output = new Array(items.length);
  let cursor = 0;
  async function worker() {
    while (true) {
      const index = cursor++;
      if (index >= items.length) return;
      output[index] = await callback(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, worker));
  return output;
}

async function readContractPool(contracts, method, args, blockTag) {
  let lastError;
  for (let round = 0; round < 6; round++) {
    for (const contract of contracts) {
      try {
        return await contract[method](...args, { blockTag });
      } catch (error) {
        lastError = error;
      }
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 750 * 2 ** round + Math.floor(Math.random() * 300)));
  }
  throw lastError;
}

class ChainReader {
  constructor(urls) {
    this.providers = urls.map((url) => new JsonRpcProvider(url, 56, {
      staticNetwork: true,
      batchMaxCount: 1,
      batchStallTime: 10,
    }));
    this.contracts = new Map();
  }

  contract(providerIndex, address, abi, label) {
    const key = `${providerIndex}:${address.toLowerCase()}:${label}`;
    if (!this.contracts.has(key)) this.contracts.set(key, new Contract(address, abi, this.providers[providerIndex]));
    return this.contracts.get(key);
  }

  async providerCall(callback) {
    let lastError;
    for (let i = 0; i < this.providers.length; i++) {
      try {
        return await callback(this.providers[i], i);
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError;
  }

  async read(address, abi, label, method, args, blockTag) {
    const contracts = this.providers.map((_provider, index) => this.contract(index, address, abi, label));
    return readContractPool(contracts, method, args, blockTag);
  }

  async multicall(address, abi, label, calls, blockTag, chunkSize = 80) {
    const iface = new Interface(abi);
    const output = [];
    const execute = async (chunk, offset) => {
      const encoded = chunk.map(({ method, args = [] }) => ({
        target: address,
        allowFailure: true,
        callData: iface.encodeFunctionData(method, args),
      }));
      let results;
      try {
        results = await this.read(MULTICALL_ADDRESS, MULTICALL_ABI, "multicall3", "aggregate3", [encoded], blockTag);
      } catch (error) {
        if (chunk.length === 1) throw error;
        const middle = Math.ceil(chunk.length / 2);
        await execute(chunk.slice(0, middle), offset);
        await execute(chunk.slice(middle), offset + middle);
        return;
      }
      results.forEach((result, index) => {
        if (!result.success) throw new Error(`${label} multicall ${offset + index} (${chunk[index].method}) reverted`);
        output.push(iface.decodeFunctionResult(chunk[index].method, result.returnData));
      });
    };
    for (let offset = 0; offset < calls.length; offset += chunkSize) {
      await execute(calls.slice(offset, offset + chunkSize), offset);
    }
    return output;
  }
}

function readU24(bytes, offset) {
  if (offset + 3 > bytes.length) throw new Error(`truncated u24 at byte ${offset}`);
  return bytes[offset] * 65536 + bytes[offset + 1] * 256 + bytes[offset + 2];
}

function readU64(bytes, offset) {
  if (offset + 8 > bytes.length) throw new Error(`truncated u64 at byte ${offset}`);
  let value = 0n;
  for (let i = 0; i < 8; i++) value = (value << 8n) | BigInt(bytes[offset + i]);
  return value;
}

export function decodeNetlist(rawHex, nIn) {
  const bytes = getBytes(rawHex);
  const elements = [];
  let offset = 0;
  let nextSignal = 2 + Number(nIn);
  let nand = 0;
  let latch = 0;
  let ref = 0;
  while (offset < bytes.length) {
    const byteOffset = offset;
    const opcode = bytes[offset++];
    if (opcode === 0) {
      const a = readU24(bytes, offset);
      const b = readU24(bytes, offset + 3);
      offset += 6;
      if (a >= nextSignal || b >= nextSignal) throw new Error(`NAND at ${byteOffset} has a future reference`);
      elements.push({ op: "NAND", opcode, a, b, out: nextSignal++, byteOffset });
      nand++;
    } else if (opcode === 1) {
      const d = readU24(bytes, offset);
      offset += 3;
      elements.push({ op: "LATCH", opcode, d, out: nextSignal++, byteOffset });
      latch++;
    } else if (opcode === 2) {
      if (offset + 30 > bytes.length) throw new Error(`truncated REF at byte ${byteOffset}`);
      const cpu = getAddress(`0x${Buffer.from(bytes.slice(offset, offset + 20)).toString("hex")}`);
      offset += 20;
      const circuitId = readU64(bytes, offset);
      offset += 8;
      const nRefIn = bytes[offset++];
      const nRefOut = bytes[offset++];
      const inputs = [];
      for (let i = 0; i < nRefIn; i++) {
        const input = readU24(bytes, offset);
        offset += 3;
        if (input >= nextSignal) throw new Error(`REF at ${byteOffset} has a future reference`);
        inputs.push(input);
      }
      const outputs = Array.from({ length: nRefOut }, () => nextSignal++);
      elements.push({ op: "REF", opcode, cpu, circuitId: circuitId.toString(), inputs, outputs, byteOffset });
      ref++;
    } else {
      throw new Error(`unknown opcode ${opcode} at byte ${byteOffset}`);
    }
  }
  return {
    byteLength: bytes.length,
    sha256: sha256Buffer(bytes),
    keccak256: keccak256(bytes),
    signalCount: nextSignal,
    counts: { nand, latch, ref, topLevelElements: elements.length },
    elements,
  };
}

function pureNandDepth(decoded, nIn, nOut) {
  if (decoded.counts.latch || decoded.counts.ref) return null;
  const depths = Array(2 + Number(nIn)).fill(0);
  for (const element of decoded.elements) depths[element.out] = 1 + Math.max(depths[element.a], depths[element.b]);
  return {
    outputs: depths.slice(-Number(nOut)),
    max: Math.max(0, ...depths.slice(-Number(nOut))),
  };
}

function netlistToBlif(decoded, task, circuitId, cpuName) {
  if (task.kind !== "comb" || decoded.counts.latch || decoded.counts.ref) return null;
  const nIn = Number(task.nIn);
  const nOut = Number(task.nOut);
  if (decoded.elements.length < nOut) return null;
  const names = ["zero", "one", ...Array.from({ length: nIn }, (_, i) => `i${i}`)];
  const outputStart = decoded.elements.length - nOut;
  const outputs = Array.from({ length: nOut }, (_, i) => `o${i}`);
  const lines = [
    `# TapeOut ${cpuName} task ${task.taskId}, circuit ${circuitId}`,
    `.model task${task.taskId}_circuit${circuitId}`,
    `.inputs ${Array.from({ length: nIn }, (_, i) => `i${i}`).join(" ")}`,
    `.outputs ${outputs.join(" ")}`,
    ".names zero",
    ".names one",
    "1",
  ];
  for (let i = 0; i < decoded.elements.length; i++) {
    const element = decoded.elements[i];
    const out = i >= outputStart ? outputs[i - outputStart] : `g${i}`;
    const left = names[element.a];
    const right = names[element.b];
    if (left === undefined || right === undefined) throw new Error(`cannot name signal in task ${task.taskId}`);
    if (left === right) lines.push(`.names ${left} ${out}`, "0 1");
    else lines.push(`.names ${left} ${right} ${out}`, "0- 1", "-0 1");
    names[element.out] = out;
  }
  lines.push(".end", "");
  return lines.join("\n");
}

function summarizeTransistorMarket(snapshot) {
  const generatedAt = Date.parse(snapshot.generatedAt || 0) / 1000;
  const cutoff = generatedAt - 86_400;
  const bidsByKey = new Map();
  for (const bid of snapshot.openBids || []) {
    const key = `${bid.transistors.toLowerCase()}-${bid.tokenId}`;
    if (!bidsByKey.has(key)) bidsByKey.set(key, []);
    bidsByKey.get(key).push(bid);
  }
  return (snapshot.tokens || []).map((token) => {
    const key = `${token.transistors.toLowerCase()}-${token.tokenId}`;
    const bids = (bidsByKey.get(key) || []).sort((a, b) => wei(b.price) > wei(a.price) ? 1 : -1);
    const trades = [...(snapshot.tradesByKey?.[key] || [])].sort((a, b) => Number(a.ts) - Number(b.ts));
    const recent = trades.filter((trade) => Number(trade.ts) >= cutoff);
    const volume24h = recent.reduce((sum, trade) => sum + wei(trade.qty), 0n);
    const notional24h = recent.reduce((sum, trade) => sum + wei(trade.price) * wei(trade.qty), 0n);
    const openQuantity = bids.reduce((sum, bid) => sum + wei(bid.remaining), 0n);
    const openNotional = bids.reduce((sum, bid) => sum + wei(bid.price) * wei(bid.remaining), 0n);
    const latest = trades.at(-1);
    return {
      key,
      processor: token.processor,
      processorName: token.name,
      transistors: token.transistors,
      tokenId: Number(token.tokenId),
      type: Number(token.tokenId) === 0 ? "NAND" : Number(token.tokenId) === 1 ? "LATCH" : `TOKEN_${token.tokenId}`,
      topBid: bids[0] ? { id: bids[0].id, price: amount(bids[0].price), remaining: bids[0].remaining } : null,
      openBook: { bids: bids.length, quantity: openQuantity.toString(), notional: amount(openNotional) },
      latestTrade: latest ? { timestamp: Number(latest.ts), price: amount(latest.price), quantity: latest.qty } : null,
      trailing24h: {
        trades: recent.length,
        quantity: volume24h.toString(),
        notional: amount(notional24h),
        vwap: volume24h ? amount(notional24h / volume24h) : null,
      },
      allTradesInSnapshot: trades.length,
    };
  });
}

function summarizeCircuitMarket(snapshot) {
  const listingsByCpu = {};
  for (const listing of snapshot.listings || []) {
    const key = listing.circuits.toLowerCase();
    listingsByCpu[key] = (listingsByCpu[key] || 0) + 1;
  }
  const tradesByCpu = {};
  for (const trade of snapshot.trades || []) {
    const key = trade.circuits.toLowerCase();
    tradesByCpu[key] = (tradesByCpu[key] || 0) + 1;
  }
  const listings = [...(snapshot.listings || [])].sort((a, b) => wei(a.price) > wei(b.price) ? 1 : -1);
  const trades = [...(snapshot.trades || [])].sort((a, b) => Number(b.ts) - Number(a.ts));
  return {
    generatedAt: snapshot.generatedAt,
    block: snapshot.block,
    market: snapshot.marketAddr,
    listingCount: listings.length,
    tradeCountInSnapshot: trades.length,
    volume24h: amount(snapshot.vol24h || 0),
    volumeTotal: amount(snapshot.volTotal || 0),
    listingsByProcessor: listingsByCpu,
    tradesByProcessor: tradesByCpu,
    cheapestListings: listings.slice(0, 100).map((x) => ({ ...x, price: amount(x.price) })),
    latestTrades: trades.slice(0, 100).map((x) => ({ ...x, price: amount(x.price) })),
  };
}

function loadPreviousLeaderboards() {
  const dir = join(LATEST, "leaderboards");
  if (!existsSync(dir)) return new Map();
  const map = new Map();
  for (const file of readdirSync(dir).filter((name) => name.endsWith(".json"))) {
    const data = JSON.parse(readFileSync(join(dir, file), "utf8"));
    for (const row of data.rows || []) map.set(`${data.processor.address.toLowerCase()}:${row.taskId}`, row);
  }
  return map;
}

function compareLeaderboards(previous, leaderboards) {
  const changes = [];
  for (const board of leaderboards) {
    for (const row of board.rows) {
      const key = `${board.processor.address.toLowerCase()}:${row.taskId}`;
      const before = previous.get(key);
      if (!before) {
        if (!row.empty) changes.push({ processor: board.processor.name, taskId: row.taskId, name: row.name, category: "initial_or_new", before: null, after: row });
        continue;
      }
      const holderChanged = String(before.circuitId ?? "") !== String(row.circuitId ?? "");
      const costChanged = String(before.cost ?? "") !== String(row.cost ?? "");
      const metricsChanged = Number(before.nand ?? -1) !== Number(row.nand ?? -1)
        || Number(before.latch ?? -1) !== Number(row.latch ?? -1)
        || Number(before.depth ?? -1) !== Number(row.depth ?? -1);
      if (!holderChanged && !costChanged && !metricsChanged && Boolean(before.empty) === Boolean(row.empty)) continue;
      let category = "holder_refresh_same_metrics";
      if (before.empty && !row.empty) category = "filled_empty_slot";
      else if (!before.empty && row.empty) category = "became_empty";
      else if (!before.empty && !row.empty && BigInt(row.cost) < BigInt(before.cost)) category = "cost_improved";
      else if (!before.empty && !row.empty && BigInt(row.cost) > BigInt(before.cost)) category = "cost_increased";
      else if (metricsChanged) category = "metrics_changed_same_cost";
      changes.push({ processor: board.processor.name, taskId: row.taskId, name: row.name, category, before, after: row });
    }
  }
  return changes;
}

function listFiles(root) {
  const output = [];
  function walk(path) {
    for (const entry of readdirSync(path, { withFileTypes: true })) {
      const full = join(path, entry.name);
      if (entry.isDirectory()) walk(full);
      else output.push(full);
    }
  }
  walk(root);
  return output.sort();
}

async function main() {
  const previousLeaderboards = loadPreviousLeaderboards();
  rmSync(STAGING, { recursive: true, force: true });
  mkdirSync(STAGING, { recursive: true });

  console.log("Fetching TapeOut configuration, vectors and markets…");
  const [config, vectors, transistorMarket, circuitMarket, dexBem, bnbUsd] = await Promise.all([
    fetchJson(URLS.config),
    fetchJson(URLS.vectors),
    fetchJson(URLS.transistorMarket),
    fetchJson(URLS.circuitMarket),
    fetchJson(URLS.dexBem, { optional: true }),
    fetchJson(URLS.bnbUsd, { optional: true }),
  ]);
  if (Number(config.chainId) !== 56) throw new Error(`unexpected chain ${config.chainId}`);
  if (!Array.isArray(config.tasks) || !config.tasks.length) throw new Error("empty task catalog");

  const selectedNames = process.env.TAPEOUT_CPUS
    ? new Set(process.env.TAPEOUT_CPUS.split(",").map((x) => x.trim()).filter(Boolean))
    : null;
  const cpus = Object.entries(config.cpus)
    .filter(([name]) => !selectedNames || selectedNames.has(name))
    .map(([name, value]) => ({ name, ...value }));
  if (!cpus.length) throw new Error("no processors selected");

  const reader = new ChainReader(RPC_URLS);
  const blockNumber = await reader.providerCall((provider) => provider.getBlockNumber());
  const [block, gasPrice] = await Promise.all([
    reader.providerCall((provider) => provider.getBlock(blockNumber)),
    reader.providerCall((provider) => provider.getFeeData()),
  ]);
  if (!block) throw new Error(`block ${blockNumber} not found`);
  const blockTag = blockNumber;
  console.log(`Fixed BSC block ${blockNumber} (${new Date(block.timestamp * 1000).toISOString()})`);

  const contractStatus = {};
  for (const [name, address] of Object.entries(config.contracts)) {
    const code = await reader.providerCall((provider) => provider.getCode(address, blockTag));
    contractStatus[name] = { address, codeBytes: (code.length - 2) / 2, codeHash: keccak256(code) };
  }

  const factoryContracts = reader.providers.map((provider) => new Contract(config.contracts.factory, FACTORY_ABI, provider));
  const readFactory = (method, args = []) => readContractPool(factoryContracts, method, args, blockTag);
  const [cpuCountRaw, deployFeeRaw] = await Promise.all([readFactory("cpuCount"), readFactory("deployFee")]);
  const cpuCount = Number(cpuCountRaw);
  const tokenProcessorMap = new Map();
  for (const token of transistorMarket.tokens || []) {
    const key = token.processor.toLowerCase();
    if (!tokenProcessorMap.has(key)) tokenProcessorMap.set(key, { address: getAddress(token.processor), name: token.name, transistors: getAddress(token.transistors), tokenIds: [] });
    tokenProcessorMap.get(key).tokenIds.push(Number(token.tokenId));
  }
  const registeredProcessors = [...tokenProcessorMap.values()]
    .sort((a, b) => a.address.toLowerCase().localeCompare(b.address.toLowerCase()));
  const sampleIndexes = [...new Set([0, Math.floor(cpuCount / 2), Math.max(0, cpuCount - 1)])];
  const factorySamples = await mapLimit(sampleIndexes, 1, async (index) => ({
    index,
    address: getAddress(await readFactory("cpuAt", [index])),
  }));
  console.log(`Factory reports ${cpuCount} processors; market index covers ${registeredProcessors.length}.`);

  const leaderboards = [];
  const processorStates = [];
  for (const cpu of cpus) {
    console.log(`Scanning ${cpu.name} leaderboard (${config.tasks.length} tasks)…`);
    const circuitsAddress = getAddress(cpu.address);
    const circuitContracts = reader.providers.map((provider) => new Contract(circuitsAddress, CIRCUITS_ABI, provider));
    const readCircuit = (method, args = []) => readContractPool(circuitContracts, method, args, blockTag);
    const [chainName, chainSymbol, transistorsAddress, nextIdRaw, factoryAddress] = await Promise.all([
      readCircuit("name"), readCircuit("symbol"), readCircuit("transistors"), readCircuit("nextId"), readCircuit("factory"),
    ]);
    const transistors = getAddress(transistorsAddress);
    const transistorContracts = reader.providers.map((provider) => new Contract(transistors, TRANSISTORS_ABI, provider));
    const readTransistor = (method, args = []) => readContractPool(transistorContracts, method, args, blockTag);
    const [cpuName, cpuSymbol, story, creator, mintPrice, minted, supplyCap, protocolFee, protocolWallet, nandId, latchId] = await Promise.all([
      readTransistor("cpuName"), readTransistor("cpuSymbol"), readTransistor("story"), readTransistor("creator"),
      readTransistor("mintPrice"), readTransistor("minted"), readTransistor("supplyCap"), readTransistor("protocolFee"),
      readTransistor("protocolWallet"), readTransistor("NAND"), readTransistor("LATCH"),
    ]);
    const processorState = {
      configName: cpu.name,
      address: circuitsAddress,
      name: chainName,
      symbol: chainSymbol,
      multiplier: cpu.multiplier,
      fromBlock: cpu.fromBlock,
      factory: getAddress(factoryAddress),
      nextCircuitId: nextIdRaw.toString(),
      transistors: {
        address: transistors,
        cpuName,
        cpuSymbol,
        story,
        creator: getAddress(creator),
        mintPrice: amount(mintPrice),
        minted: minted.toString(),
        supplyCap: supplyCap.toString(),
        remaining: (supplyCap - minted).toString(),
        protocolFee: protocolFee.toString(),
        protocolWallet: getAddress(protocolWallet),
        tokenIds: { NAND: nandId.toString(), LATCH: latchId.toString() },
      },
    };
    processorStates.push(processorState);

    const slots = await reader.multicall(
      config.contracts.mining,
      MINING_ABI,
      `${cpu.name} bestSlot`,
      config.tasks.map((task) => ({ method: "bestSlot", args: [task.taskId, circuitsAddress] })),
      blockTag,
    );
    const occupiedSlots = slots
      .map((slot, index) => ({ slot, task: config.tasks[index] }))
      .filter(({ slot }) => slot.holderPlus1 !== 0n);
    const miners = await reader.multicall(
      config.contracts.mining,
      MINING_ABI,
      `${cpu.name} getMiner`,
      occupiedSlots.map(({ slot }) => {
        const circuitId = slot.holderPlus1 - 1n;
        return { method: "getMiner", args: [solidityPackedKeccak256(["address", "uint256"], [circuitsAddress, circuitId])] };
      }),
      blockTag,
    );
    const minerByTask = new Map(occupiedSlots.map(({ task }, index) => [Number(task.taskId), miners[index][0]]));
    const rows = config.tasks.map((task, index) => {
      const slot = slots[index];
      if (slot.holderPlus1 === 0n) return { taskId: task.taskId, srcId: task.srcId, name: task.name, kind: task.kind, empty: true };
      const circuitId = slot.holderPlus1 - 1n;
      const miner = minerByTask.get(Number(task.taskId));
      if (Number(miner.taskId) !== Number(task.taskId)) throw new Error(`${cpu.name} task ${task.taskId}: miner task mismatch`);
      const expectedCost = miner.area * BigInt(Math.max(Number(miner.depth), 1)) ** 3n;
      if (expectedCost !== slot.cost) throw new Error(`${cpu.name} task ${task.taskId}: cost mismatch`);
      return {
        taskId: task.taskId,
        srcId: task.srcId,
        name: task.name,
        kind: task.kind,
        nIn: task.nIn,
        nOut: task.nOut,
        cycles: task.cycles,
        circuitId: circuitId.toString(),
        cost: slot.cost.toString(),
        depth: Number(miner.depth),
        gateCount: Number(miner.gateCount),
        stateCount: Number(miner.stateCount),
        nand: Number(miner.nandBurn),
        latch: Number(miner.latchBurn),
        area: miner.area.toString(),
        multiplier: Number(miner.mult),
        since: miner.since.toString(),
        status: Number(miner.status),
        registrant: getAddress(miner.registrant),
        bstar: miner.bstar.toString(),
        bonus: miner.bonus.toString(),
        optimal: Boolean(miner.optimal),
        verifiedWeight: miner.verifWeight.toString(),
        unverifiedWeight: miner.unverWeight.toString(),
        debt: miner.debt.toString(),
      };
    });

    const occupied = rows.filter((row) => !row.empty);
    console.log(`Fetching ${occupied.length} ${cpu.name} best netlists…`);
    const circuitResults = await reader.multicall(
      circuitsAddress,
      CIRCUITS_ABI,
      `${cpu.name} circuit data`,
      occupied.flatMap((row) => [
        { method: "circuitInfo", args: [row.circuitId] },
        { method: "netlist", args: [row.circuitId] },
        { method: "ownerOf", args: [row.circuitId] },
      ]),
      blockTag,
      45,
    );
    occupied.forEach((row, index) => {
      const task = config.tasks.find((candidate) => Number(candidate.taskId) === Number(row.taskId));
      const info = circuitResults[index * 3];
      const raw = circuitResults[index * 3 + 1][0];
      const owner = circuitResults[index * 3 + 2][0];
      const decoded = decodeNetlist(raw, Number(info.nIn));
      const pureDepth = pureNandDepth(decoded, Number(info.nIn), Number(info.nOut));
      if (Number(info.nIn) !== Number(task.nIn) || Number(info.nOut) !== Number(task.nOut)) {
        throw new Error(`${cpu.name} task ${task.taskId}: circuit interface mismatch`);
      }
      if (task.kind === "comb" && pureDepth && pureDepth.max !== Number(row.depth)) {
        throw new Error(`${cpu.name} task ${task.taskId}: decoded depth ${pureDepth.max} != ${row.depth}`);
      }
      const fileStem = `task-${String(task.taskId).padStart(3, "0")}-circuit-${row.circuitId}`;
      const cpuSlug = slug(cpu.name);
      const blif = netlistToBlif(decoded, task, row.circuitId, cpu.name);
      const netlistRecord = {
        snapshotBlock: blockNumber,
        processor: { name: cpu.name, address: circuitsAddress },
        task: { taskId: task.taskId, srcId: task.srcId, name: task.name, kind: task.kind, nIn: task.nIn, nOut: task.nOut, cycles: task.cycles },
        circuit: {
          circuitId: row.circuitId,
          owner: getAddress(owner),
          info: { nIn: Number(info.nIn), nOut: Number(info.nOut), nState: Number(info.nState), gateCount: Number(info.gateCount) },
          mining: row,
        },
        rawNetlist: raw,
        decoded,
        pureNandDepth: pureDepth,
        blifAvailable: Boolean(blif),
      };
      writeJson(join(STAGING, "netlists", cpuSlug, `${fileStem}.json`), netlistRecord);
      if (blif) writeText(join(STAGING, "blif", cpuSlug, `${fileStem}.blif`), blif);
      row.owner = getAddress(owner);
      row.netlist = `netlists/${cpuSlug}/${fileStem}.json`;
      row.blif = blif ? `blif/${cpuSlug}/${fileStem}.blif` : null;
      row.rawNetlistBytes = decoded.byteLength;
      row.rawNetlistSha256 = decoded.sha256;
      row.topLevel = decoded.counts;
    });

    const board = {
      snapshotBlock: blockNumber,
      blockTimeUTC: new Date(block.timestamp * 1000).toISOString(),
      processor: processorState,
      taskCount: rows.length,
      occupiedCount: occupied.length,
      emptyCount: rows.length - occupied.length,
      rows,
    };
    leaderboards.push(board);
    writeJson(join(STAGING, "leaderboards", `${slug(cpu.name)}.json`), board);
  }

  const transistorSummary = summarizeTransistorMarket(transistorMarket);
  const circuitSummary = summarizeCircuitMarket(circuitMarket);
  writeJson(join(STAGING, "markets", "transistors-raw.json"), transistorMarket);
  writeJson(join(STAGING, "markets", "transistors-summary.json"), {
    generatedAt: transistorMarket.generatedAt,
    block: transistorMarket.lastBlock,
    tokenCount: transistorSummary.length,
    activeTokenCount: transistorSummary.filter((row) => row.topBid || row.latestTrade).length,
    rows: transistorSummary,
  });
  writeJson(join(STAGING, "markets", "circuits-raw.json"), circuitMarket);
  writeJson(join(STAGING, "markets", "circuits-summary.json"), circuitSummary);
  writeJson(join(STAGING, "markets", "dexscreener-bem.json"), dexBem);
  writeJson(join(STAGING, "markets", "bnb-usdt.json"), bnbUsd);

  writeJson(join(STAGING, "protocol", "config.json"), config);
  writeJson(join(STAGING, "protocol", "tasks.json"), { generatedAt: new Date().toISOString(), taskCount: config.tasks.length, tasks: config.tasks });
  writeJson(join(STAGING, "protocol", "contracts.json"), {
    snapshotBlock: blockNumber,
    chainId: 56,
    factory: { address: config.contracts.factory, cpuCount, deployFee: amount(deployFeeRaw) },
    contracts: contractStatus,
  });
  writeJson(join(STAGING, "protocol", "processors-official.json"), { snapshotBlock: blockNumber, processors: processorStates });
  writeJson(join(STAGING, "protocol", "processors-registered.json"), {
    snapshotBlock: blockNumber,
    source: "TapeOut market token index, cross-checked against factory cpuCount and sampled cpuAt entries",
    factoryCount: cpuCount,
    count: registeredProcessors.length,
    fullCountMatch: registeredProcessors.length === cpuCount,
    factorySamples,
    processors: registeredProcessors,
  });

  mkdirSync(REFERENCE, { recursive: true });
  writeJson(join(REFERENCE, "pod-vectors-all.json"), vectors);
  writeJson(join(REFERENCE, "manifest.json"), {
    source: URLS.vectors,
    generatedAt: new Date().toISOString(),
    taskCount: Object.keys(vectors).length,
    sha256: sha256File(join(REFERENCE, "pod-vectors-all.json")),
  });

  const changes = compareLeaderboards(previousLeaderboards, leaderboards);
  const changeDocument = {
    generatedAt: new Date().toISOString(),
    block: blockNumber,
    blockTimeUTC: new Date(block.timestamp * 1000).toISOString(),
    total: changes.length,
    costImproved: changes.filter((row) => row.category === "cost_improved").length,
    holderRefreshSameMetrics: changes.filter((row) => row.category === "holder_refresh_same_metrics").length,
    changes,
  };
  mkdirSync(CHANGES, { recursive: true });
  writeJson(join(CHANGES, "latest.json"), changeDocument);

  const scanTime = new Date();
  const date = scanTime.toISOString().slice(0, 10);
  const historyDir = join(HISTORY, date);
  writeJson(join(historyDir, "summary.json"), {
    generatedAt: scanTime.toISOString(),
    block: blockNumber,
    blockTimeUTC: new Date(block.timestamp * 1000).toISOString(),
    processors: leaderboards.map((board) => ({
      name: board.processor.configName,
      address: board.processor.address,
      occupied: board.occupiedCount,
      rows: board.rows.map((row) => row.empty ? { taskId: row.taskId, empty: true } : {
        taskId: row.taskId, circuitId: row.circuitId, cost: row.cost, depth: row.depth, nand: row.nand, latch: row.latch,
      }),
    })),
  });
  writeJson(join(historyDir, "changes.json"), changeDocument);
  writeJson(join(historyDir, "markets-summary.json"), {
    generatedAt: scanTime.toISOString(),
    transistorMarket: {
      generatedAt: transistorMarket.generatedAt,
      block: transistorMarket.lastBlock,
      openBids: transistorMarket.openBids?.length || 0,
      tokens: transistorMarket.tokens?.length || 0,
    },
    circuitMarket: circuitSummary,
    bnbUsd,
  });

  const filesBeforeManifest = listFiles(STAGING);
  const manifest = {
    schemaVersion: 1,
    generatedAt: scanTime.toISOString(),
    sources: URLS,
    chainId: 56,
    rpcEndpointsConfigured: RPC_URLS.length,
    block: {
      number: blockNumber,
      hash: block.hash,
      parentHash: block.parentHash,
      timestamp: Number(block.timestamp),
      timeUTC: new Date(block.timestamp * 1000).toISOString(),
      gasLimit: block.gasLimit.toString(),
      gasUsed: block.gasUsed.toString(),
      baseFeePerGas: block.baseFeePerGas?.toString() ?? null,
      gasPrice: gasPrice.gasPrice?.toString() ?? null,
    },
    coverage: {
      taskCount: config.tasks.length,
      officialProcessorsConfigured: Object.keys(config.cpus).length,
      officialProcessorsScanned: leaderboards.length,
      registeredProcessors: registeredProcessors.length,
      leaderboardSlotsRead: leaderboards.reduce((sum, board) => sum + board.rows.length, 0),
      occupiedLeaderboardSlots: leaderboards.reduce((sum, board) => sum + board.occupiedCount, 0),
      netlistsExported: leaderboards.reduce((sum, board) => sum + board.occupiedCount, 0),
      blifExported: filesBeforeManifest.filter((path) => path.endsWith(".blif")).length,
      transistorTokens: transistorMarket.tokens?.length || 0,
      transistorOpenBids: transistorMarket.openBids?.length || 0,
      circuitListings: circuitMarket.listings?.length || 0,
      circuitTradesInSnapshot: circuitMarket.trades?.length || 0,
    },
    changes: {
      total: changeDocument.total,
      costImproved: changeDocument.costImproved,
      holderRefreshSameMetrics: changeDocument.holderRefreshSameMetrics,
    },
    files: filesBeforeManifest.map((path) => ({
      path: relative(STAGING, path),
      bytes: statSync(path).size,
      sha256: sha256File(path),
    })),
  };
  writeJson(join(STAGING, "manifest.json"), manifest);

  rmSync(LATEST, { recursive: true, force: true });
  mkdirSync(dirname(LATEST), { recursive: true });
  renameSync(STAGING, LATEST);
  console.log(JSON.stringify({
    block: blockNumber,
    blockTimeUTC: manifest.block.timeUTC,
    tasks: config.tasks.length,
    processors: leaderboards.map((board) => ({ name: board.processor.configName, occupied: board.occupiedCount })),
    registeredProcessors: registeredProcessors.length,
    netlists: manifest.coverage.netlistsExported,
    blif: manifest.coverage.blifExported,
    changes: manifest.changes,
    files: manifest.files.length + 1,
  }, null, 2));
}

await main();
