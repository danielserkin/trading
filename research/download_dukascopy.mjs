#!/usr/bin/env node
import {mkdir, writeFile} from "node:fs/promises";
import {createRequire} from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const {getHistoricalRates} = require("./.cache/duka/node_modules/dukascopy-node");

const from = process.argv[2] || "2025-12-01";
const to = process.argv[3] || "2026-06-01";
const symbols = process.argv.slice(4).length
  ? process.argv.slice(4)
  : ["eurusd", "gbpusd", "usdjpy", "usdcad", "audjpy", "euraud", "gbpchf", "gbpcad"];
const outputDir = path.resolve("research/.cache/dukascopy-bars");
await mkdir(outputDir, {recursive: true});

for (const instrument of symbols) {
  const data = await getHistoricalRates({
    instrument,
    dates: {from: new Date(`${from}T00:00:00Z`), to: new Date(`${to}T00:00:00Z`)},
    timeframe: "m15",
    format: "json",
    priceType: "bid",
    volumes: false,
    ignoreFlats: true,
    batchSize: 5,
    pauseBetweenBatchesMs: 1500,
    retryCount: 6,
    pauseBetweenRetriesMs: 3000,
    useCache: true,
    cacheFolderPath: path.resolve("research/.cache/dukascopy-http"),
  });
  const destination = path.join(outputDir, `${instrument.toUpperCase()}-${from}-${to}-m15-bid.json`);
  await writeFile(destination, `${JSON.stringify(data)}\n`);
  process.stdout.write(`${instrument.toUpperCase()} ${data.length} ${destination}\n`);
}
