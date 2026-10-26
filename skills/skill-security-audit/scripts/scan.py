#!/usr/bin/env python3
"""Agent Skills とエージェント設定ファイルを、読むだけで検査する。

  python3 -I scan.py <フォルダかファイル> [...]   結果を JSON で標準出力に出す

対象のファイルを実行・import・ネットワーク送信はしない。標準ライブラリだけで動く。
"""
import json
import os
import re
import sys

# エージェントが読む設定・指示のファイル
CONTEXT_NAMES = {"SKILL.md", "CLAUDE.md", "AGENTS.md", "GEMINI.md", ".cursorrules", ".windsurfrules", "copilot-instructions.md"}
CONFIG_NAMES = {"settings.json", "settings.local.json", ".mcp.json", "mcp.json", "hooks.json", "plugin.json", "marketplace.json"}
SCRIPT_EXT = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".ps1", ".bat", ".cmd"}
TEXT_EXT = SCRIPT_EXT | {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".html", ".xml", ""}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
MAX_BYTES = 2_000_000

# (id, 重さ, 説明, 正規表現)。重さ: high = 単独で危険、medium = 文脈次第、info = 把握しておく
RULES = [
    ("unicode-tag", "high", "見えない Unicode Tag 文字（U+E0000〜E007F）。人には見えず、モデルには読める命令を隠せる", re.compile("[\U000E0000-\U000E007F]")),
    ("bidi-control", "high", "文字の表示順を入れ替える制御文字（Trojan Source）", re.compile("[‪-‮⁦-⁩]")),
    ("zero-width", "medium", "ゼロ幅文字。単語の中に命令や識別子を隠せる", re.compile("[​-‏⁠﻿]")),
    ("html-comment", "medium", "HTML コメント。Markdown の表示では見えないが、モデルは読む", re.compile(r"<!--[\s\S]*?-->")),
    ("pipe-to-shell", "high", "ダウンロードしたものをそのままシェルで実行する", re.compile(r"(curl|wget|iwr|Invoke-WebRequest)[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh\b|\b(bash|sh)\s+<\(\s*(curl|wget)", re.I)),
    ("reverse-shell", "high", "リバースシェルの典型", re.compile(r"/dev/tcp/|\bnc\b[^\n]*\s-e\s|\bmkfifo\b[^\n]*\bnc\b|socket\.socket\([^\n]*\)[^\n]*connect", re.I)),
    ("decode-exec", "high", "復号した文字列を実行する（難読化）", re.compile(r"(base64\s+(-d|--decode)[^\n]*\|\s*(ba)?sh)|\beval\s*\(\s*(atob|Buffer\.from)|exec\s*\(\s*(base64\.b64decode|codecs\.decode|bytes\.fromhex)", re.I)),
    ("secret-path", "high", "認証情報の置き場所に触れる", re.compile(r"~/\.ssh|id_rsa|id_ed25519|~/\.aws/credentials|\.aws/credentials|~/\.config/gh|\.netrc|\.npmrc|\.pypirc|Keychain|security\s+find-(generic|internet)-password|\.git-credentials", re.I)),
    ("secret-env", "medium", "API キー・トークンの環境変数を読む", re.compile(r"\$\{?[A-Z0-9_]*(API_KEY|TOKEN|SECRET|PASSWORD|ACCESS_KEY)[A-Z0-9_]*\}?|process\.env\.[A-Z0-9_]*(KEY|TOKEN|SECRET)|os\.environ(\.get)?\[?\(?['\"][A-Z0-9_]*(KEY|TOKEN|SECRET)", re.I)),
    ("dotenv", "medium", ".env ファイルを読む", re.compile(r"(cat|source|open|readFile\w*|load_dotenv)\W[^\n]*\.env\b", re.I)),
    ("network-send", "medium", "外部へ送信する（POST・アップロード）", re.compile(r"curl[^\n]*\s(-d|--data\S*|-F|--form|-T|--upload-file|-X\s*POST)\b|requests\.(post|put)\(|fetch\([^\n]*method\s*:\s*['\"](POST|PUT)|axios\.(post|put)\(|urllib\.request\.urlopen\([^\n]*data=", re.I)),
    ("webhook", "high", "チャットの Webhook やペーストサイトなど、よく情報の持ち出しに使われる送信先", re.compile(r"discord(app)?\.com/api/webhooks|hooks\.slack\.com|api\.telegram\.org/bot|pastebin\.com|transfer\.sh|ngrok\.(io|app)|webhook\.site|requestbin|interact\.sh|burpcollaborator", re.I)),
    ("destructive", "high", "広い範囲を削除・上書きする", re.compile(r"rm\s+-[a-z]*r[a-z]*f?\s+(/|~|\$HOME|\*)(\s|$)|git\s+push\s+[^\n]*(--force|-f)\b|git\s+reset\s+--hard|mkfs|dd\s+if=", re.I)),
    ("persistence", "high", "常駐・自動起動や、ほかの指示ファイルへの書き込み", re.compile(r"crontab\s|launchctl\s+(load|bootstrap)|LaunchAgents|systemctl\s+enable|\.bashrc|\.zshrc|\.profile\b|(>>?|write\w*\(|tee\s)[^\n]*(CLAUDE\.md|AGENTS\.md|SKILL\.md|settings\.json)", re.I)),
    ("prompt-override", "high", "それまでの指示を無視させる・ユーザーに隠させる文言", re.compile(r"ignore (all |any )?(previous|prior|above) (instructions|rules)|disregard (the )?(previous|system)|do not (tell|inform|mention)[^\n]{0,40}(user|human)|without (telling|asking|notifying) the user|これまでの指示を無視|ユーザーに(は)?(伝え|知らせ|言わ)ない", re.I)),
    ("permission-bypass", "high", "確認なしで実行させる設定・フラグ", re.compile(r"--dangerously-skip-permissions|bypassPermissions|--yolo|\"defaultMode\"\s*:\s*\"bypass|--no-verify|--trust-all", re.I)),
    ("install-global", "medium", "パッケージの導入・システムの変更", re.compile(r"\bsudo\b|npm\s+(i|install)\s+-g|pip3?\s+install|brew\s+install|npx\s+-y\s", re.I)),
    ("url", "info", "外部の URL", re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&*+,;=%]+")),
]
LONG_BLOB = re.compile(r"[A-Za-z0-9+/=]{200,}")


def kind_of(path):
    name = os.path.basename(path)
    if name in CONTEXT_NAMES or (name.endswith(".md") and "/.claude/" in path.replace(os.sep, "/")):
        return "context"
    if name in CONFIG_NAMES or name.endswith(".mcp.json"):
        return "config"
    if os.path.splitext(name)[1].lower() in SCRIPT_EXT:
        return "script"
    return "other"


def walk(targets):
    for t in targets:
        if os.path.isfile(t):
            yield t
            continue
        for root, dirs, files in os.walk(t):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                yield os.path.join(root, f)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def scan_config(path, text):
    """settings.json の hooks、.mcp.json のサーバー定義を取り出す。"""
    out = []
    try:
        data = json.loads(text)
    except ValueError:
        return out
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if isinstance(hooks, dict):
        for event, entries in hooks.items():
            for cmd in re.findall(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"', json.dumps(entries)):
                out.append({"rule": "hook", "severity": "high", "detail": f"フック（{event}）がコマンドを実行する: {cmd[:200]}"})
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if isinstance(servers, dict):
        for name, spec in servers.items():
            spec = spec if isinstance(spec, dict) else {}
            target = spec.get("url") or " ".join([str(spec.get("command", ""))] + [str(a) for a in spec.get("args", [])])
            out.append({"rule": "mcp-server", "severity": "medium", "detail": f"MCP サーバー「{name}」: {target[:200]}"})
    if isinstance(data, dict) and isinstance(data.get("env"), dict):
        for k, v in data["env"].items():
            if re.search(r"BASE_URL|ENDPOINT|PROXY", k, re.I):
                out.append({"rule": "endpoint-override", "severity": "high", "detail": f"送信先を差し替える環境変数: {k}={str(v)[:120]}"})
    return out


def scan_file(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return {"path": path, "kind": kind_of(path), "skipped": "大きすぎるため読まなかった"}
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        return {"path": path, "kind": kind_of(path), "skipped": str(e)}
    if b"\x00" in raw[:4096]:
        return {"path": path, "kind": "binary", "findings": [{"rule": "binary", "severity": "medium", "detail": "バイナリファイル。中身を読めないので、なぜ入っているかを確かめる"}]}
    text = raw.decode("utf-8", errors="replace")
    findings = []
    for rule, severity, desc, rx in RULES:
        hits = list(rx.finditer(text))
        if not hits:
            continue
        sample = hits[0].group(0)
        if rule in ("unicode-tag", "zero-width", "bidi-control"):
            hidden = "".join(chr(ord(c) - 0xE0000) for c in "".join(h.group(0) for h in hits) if 0xE0020 <= ord(c) <= 0xE007E)
            sample = f"{len(hits)} 文字" + (f"。復号すると: {hidden[:300]}" if hidden else "")
        findings.append({"rule": rule, "severity": severity, "detail": desc, "line": line_of(text, hits[0].start()), "count": len(hits), "sample": sample[:300]})
    for m in LONG_BLOB.finditer(text):
        findings.append({"rule": "long-blob", "severity": "medium", "detail": "長い Base64 風の文字列（難読化した中身の可能性）", "line": line_of(text, m.start()), "sample": m.group(0)[:80] + "…"})
        break
    if kind_of(path) == "config":
        findings.extend(scan_config(path, text))
    return {"path": path, "kind": kind_of(path), "findings": findings}


def main():
    targets = sys.argv[1:] or ["."]
    files = []
    for p in walk(targets):
        ext = os.path.splitext(p)[1].lower()
        if ext in TEXT_EXT or kind_of(p) != "other" or os.access(p, os.X_OK):
            files.append(scan_file(p))
    order = {"high": 0, "medium": 1, "info": 2}
    summary = {s: 0 for s in order}
    for f in files:
        f.setdefault("findings", [])
        f["findings"].sort(key=lambda x: order.get(x["severity"], 3))
        for x in f["findings"]:
            summary[x["severity"]] = summary.get(x["severity"], 0) + 1
    print(json.dumps({"targets": targets, "summary": summary, "files": [f for f in files if f["findings"] or f.get("skipped")]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
