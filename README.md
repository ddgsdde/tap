# TapeOut Chain Data

TapeOut Protocol 的可复现链上数据镜像。仓库定时读取 BNB Smart Chain 主网和 TapeOut 官方公开数据，保存：

- 官方处理器的全部题目榜首、门数、深度、成本、持有人和矿机状态；
- 每个榜首电路的原始链上网表、解码结构，以及可导出的 NAND-only BLIF；
- 题库元数据和官方测试向量；
- 晶体管市场买单、成交历史、价格/深度汇总；
- 电路市场挂单、成交历史与成交量；
- 协议合约、处理器、晶体管供应及区块状态；
- 每次扫描相对上一版的榜首变化，以及按日保存的摘要。

> “榜首”表示扫描区块时合约 `bestSlot` 的持有者，不等于已经获得数学全局最优证明。行情和持有人会随新区块变化。

## 最新数据

- [`data/latest/manifest.json`](data/latest/manifest.json)：扫描时间、固定区块、数据完整性与文件索引
- [`data/latest/leaderboards/`](data/latest/leaderboards/)：各官方处理器完整榜单
- [`data/latest/netlists/`](data/latest/netlists/)：榜首链上网表及解码结果
- [`data/latest/blif/`](data/latest/blif/)：可直接用于逻辑工具的纯 NAND 组合电路
- [`data/latest/markets/`](data/latest/markets/)：晶体管、电路与外部价格行情
- [`data/latest/protocol/`](data/latest/protocol/)：配置、任务、向量、合约和处理器状态
- [`data/changes/latest.json`](data/changes/latest.json)：最近一次榜首变化
- [`data/history/`](data/history/)：每日快照摘要

所有 BNB 数额在原始 JSON 中保留 wei 字符串，汇总文件同时提供十进制 BNB 字符串，避免浮点数损失精度。

## 自动更新

[`update-data.yml`](.github/workflows/update-data.yml) 每小时运行一次，也支持手动触发。工作流会：

1. 固定一个 BSC 区块；
2. 在该区块读取全部官方处理器榜首和对应网表；
3. 校验题目、矿机记录、门数以及 `area × max(depth, 1)^3 = cost`；
4. 拉取市场快照并生成规范化行情；
5. 运行独立数据校验；
6. 仅在数据发生变化时提交到 `main`。

工作流只进行只读 RPC 调用，不需要钱包、私钥或链上交易。

## 离线 SAT 最优推理

仓库内置固定版本的 Kissat 4.0.4 与 drat-trim 源码，以及不依赖第三方
Python 包的精确 NAND 综合器。获得仓库后，即使沙盒完全断网，也可以从源码构建
求解器、搜索更低成本电路、解码 SAT 模型、全输入验证候选，并独立核验 UNSAT
证明证书。

```bash
npm run sat:build
npm run sat:selftest
```

完整用法和证明边界见
[`docs/OFFLINE_OPTIMALITY.md`](docs/OFFLINE_OPTIMALITY.md)。

## 本地运行

```bash
npm ci
npm run scan
npm run validate
```

可用环境变量：

```bash
# 逗号分隔的 BSC RPC，按顺序故障转移
TAPEOUT_RPC_URLS="https://tapeout.net/rpc,https://bsc-rpc.publicnode.com" npm run scan

# 只扫描指定官方处理器；名称来自 pod-mainnet.json
TAPEOUT_CPUS="TapeOut,Behemoth" npm run scan
```

## 数据来源

- BNB Smart Chain 主网 JSON-RPC
- [TapeOut PoD 配置与题库](https://tapeout.net/pod/pod-mainnet.json)
- [TapeOut 晶体管市场快照](https://tapeout.net/market.json)
- [TapeOut 电路市场快照](https://tapeout.net/circuit-market.json)
- [DexScreener BEM 行情](https://api.dexscreener.com/latest/dex/tokens/0x5ce033B2bFCa3Af30b3e8C8457DeaF776A8b695a)
- Binance BNB/USDT 公开行情

## 许可

代码使用 [MIT License](LICENSE)。链上数据和第三方接口数据分别受其原始来源条款约束。
