#!/usr/bin/env node
// ロックファイルにある全パッケージの「公開されてからの日数」と「インストール時に動くスクリプト」を調べる。
//
//   node lockfile-check.mjs [プロジェクトのフォルダ] [--days 7] [--concurrency 8] [--max 5000]
//
// 読むのはロックファイルだけ。問い合わせ先は https://registry.npmjs.org（公開情報の取得のみ）。
// パッケージのインストール・スクリプトの実行はしない。結果は JSON で標準出力に出す。
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? Number(args[i + 1]) : fallback;
};
const dir = resolve(args.find((a, i) => !a.startsWith("--") && !args[i - 1]?.startsWith("--")) ?? ".");
const DAYS = opt("days", 7);
const CONCURRENCY = opt("concurrency", 8);
const MAX = opt("max", 5000);
const REGISTRY = "https://registry.npmjs.org";

/** "@scope/name@1.2.3" → ["@scope/name", "1.2.3"] */
function splitSpec(spec) {
  const at = spec.lastIndexOf("@");
  return at > 0 ? [spec.slice(0, at), spec.slice(at + 1)] : [spec, ""];
}

function fromPackageLock(text) {
  const lock = JSON.parse(text);
  const out = [];
  for (const [path, info] of Object.entries(lock.packages ?? {})) {
    if (!path || info.link || !info.version) continue;
    if (info.resolved && !info.resolved.startsWith(REGISTRY)) continue; // git・ファイル・別レジストリは対象外
    const name = info.name ?? path.slice(path.lastIndexOf("node_modules/") + "node_modules/".length);
    out.push({ name, version: info.version, lockInstallScript: Boolean(info.hasInstallScript) });
  }
  return out;
}

function fromPnpmLock(text) {
  const out = [];
  let inPackages = false;
  for (const line of text.split("\n")) {
    if (/^\S/.test(line)) inPackages = /^packages:/.test(line);
    if (!inPackages) continue;
    const m = /^ {2}'?\/?([^\s':]+?)'?:\s*$/.exec(line);
    if (!m) continue;
    const spec = m[1].replace(/\(.*$/, ""); // ピア依存の接尾辞 (react@18.3.1) を外す
    const [name, version] = splitSpec(spec.replace(/^\//, ""));
    if (name && /^\d/.test(version)) out.push({ name, version });
  }
  return out;
}

function fromYarnLock(text) {
  const out = [];
  let name = null;
  for (const line of text.split("\n")) {
    if (/^\S.*:\s*$/.test(line) && !line.startsWith("#") && !line.startsWith("__metadata")) {
      const first = line.replace(/:\s*$/, "").split(",")[0].trim().replace(/^"|"$/g, "");
      name = splitSpec(first)[0];
      continue;
    }
    const v = /^ {2}version:? "?([^"\s]+)"?/.exec(line);
    if (v && name) {
      out.push({ name, version: v[1] });
      name = null;
    }
  }
  return out;
}

function readLock() {
  const candidates = [
    ["package-lock.json", fromPackageLock],
    ["npm-shrinkwrap.json", fromPackageLock],
    ["pnpm-lock.yaml", fromPnpmLock],
    ["yarn.lock", fromYarnLock],
  ];
  for (const [file, parse] of candidates) {
    const p = join(dir, file);
    if (existsSync(p)) return { lockfile: file, packages: parse(readFileSync(p, "utf8")) };
  }
  return { lockfile: null, packages: [] };
}

const INSTALL_HOOKS = ["preinstall", "install", "postinstall"];

async function inspect(pkg) {
  const url = `${REGISTRY}/${pkg.name.replace("/", "%2f")}`;
  try {
    const res = await fetch(url, { headers: { accept: "application/json" }, signal: AbortSignal.timeout(20_000) });
    if (!res.ok) return { ...pkg, error: `HTTP ${res.status}` };
    const doc = await res.json();
    const published = doc.time?.[pkg.version] ?? null;
    const meta = doc.versions?.[pkg.version];
    const scripts = Object.fromEntries(Object.entries(meta?.scripts ?? {}).filter(([k]) => INSTALL_HOOKS.includes(k)));
    const ageDays = published ? (Date.now() - Date.parse(published)) / 86_400_000 : null;
    return {
      ...pkg,
      published,
      ageDays: ageDays == null ? null : Math.round(ageDays * 10) / 10,
      installScripts: Object.keys(scripts).length ? scripts : null,
      deprecated: meta?.deprecated ?? null,
      missing: !meta, // レジストリに無い（取り下げ済みなど）
      provenance: Boolean(meta?.dist?.attestations),
    };
  } catch (e) {
    return { ...pkg, error: String(e?.message ?? e) };
  }
}

async function main() {
  const { lockfile, packages } = readLock();
  if (!lockfile) {
    console.log(JSON.stringify({ dir, lockfile: null, note: "ロックファイルがありません。依存のバージョンが固定されていない状態です。" }, null, 2));
    return;
  }
  const seen = new Set();
  const unique = packages.filter((p) => {
    const k = `${p.name}@${p.version}`;
    return seen.has(k) ? false : (seen.add(k), true);
  });
  const targets = unique.slice(0, MAX);
  const results = [];
  let next = 0;
  await Promise.all(
    Array.from({ length: CONCURRENCY }, async () => {
      while (next < targets.length) results.push(await inspect(targets[next++]));
    }),
  );
  results.sort((a, b) => (a.ageDays ?? 1e9) - (b.ageDays ?? 1e9));
  const recent = results.filter((r) => r.ageDays != null && r.ageDays < DAYS);
  const withScripts = results.filter((r) => r.installScripts || r.lockInstallScript);
  console.log(
    JSON.stringify(
      {
        dir,
        lockfile,
        checked: results.length,
        truncated: unique.length > MAX ? unique.length - MAX : 0,
        thresholdDays: DAYS,
        recent,
        installScripts: withScripts.map(({ name, version, installScripts, lockInstallScript }) => ({ name, version, installScripts, lockInstallScript })),
        deprecated: results.filter((r) => r.deprecated).map(({ name, version, deprecated }) => ({ name, version, deprecated })),
        missing: results.filter((r) => r.missing && !r.error).map(({ name, version }) => ({ name, version })),
        errors: results.filter((r) => r.error).map(({ name, version, error }) => ({ name, version, error })),
        newest: results.slice(0, 10).map(({ name, version, published, ageDays }) => ({ name, version, published, ageDays })),
      },
      null,
      2,
    ),
  );
}

main();
