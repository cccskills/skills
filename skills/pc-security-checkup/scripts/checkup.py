#!/usr/bin/env python3
"""PC の安全性を、読むだけで点検する（macOS・Linux・Windows）。

  python3 -I checkup.py                        結果を JSON で標準出力に出す
  python3 -I checkup.py --save <フォルダ>       結果を <フォルダ>/checkup-<日時>.json にも保存する
  python3 -I checkup.py --diff <前回の.json>    前回から増えた自動起動・待ち受け・未署名の実行ファイルを出す
  python3 -I checkup.py --save <フォルダ> --diff latest --notify
                                               定期実行向け。<フォルダ> の最新の結果と比べ、増えたものがあれば通知する

OS 標準のコマンドを読み取りの用途で呼ぶだけで、ファイルの削除・設定の変更・プロセスの停止・
ネットワーク送信はしない。標準ライブラリだけで動く。
"""
import argparse
import datetime
import glob
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
SYSTEM = platform.system()  # Darwin / Linux / Windows
MAX_SIGN_CHECKS = 400

# 正規のソフトがまず置かない場所。ここから動く実行ファイルや自動起動は重く見る
RISKY_DIR = re.compile(
    r"^(/tmp/|/private/tmp/|/var/tmp/|/private/var/tmp/|/dev/shm/|/Users/Shared/)"
    r"|/Downloads/|/\.Trash/|\\AppData\\Local\\Temp\\|\\Windows\\Temp\\|\\Users\\Public\\|\\Downloads\\",
    re.I,
)
# 隠しフォルダ（.local・.nvm など開発ツールにもよくあるので、署名の有無と合わせて見る）
HIDDEN_DIR = re.compile(r"[/\\]\.[^/\\.][^/\\]*[/\\]")
# 開発ツールが入れる、署名のないことが普通の置き場所
DEV_DIR = re.compile(r"^/opt/homebrew/|^/usr/local/(Cellar|opt|bin)/|/node_modules/|/ms-playwright/|/\.(nvm|cargo|rustup|pyenv|volta|bun|deno|local/share/mise)/|/\.vscode/extensions/|/\.cursor/extensions/")
SHELL_RISK = [
    ("pipe-to-shell", re.compile(r"(curl|wget)[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh\b", re.I)),
    ("decode-exec", re.compile(r"base64\s+(-d|--decode|-D)[^\n]*\|\s*(ba|z)?sh|eval\s+\"?\$\(\s*(echo|printf)[^\n]*base64", re.I)),
    ("reverse-shell", re.compile(r"/dev/tcp/|\bnc\b[^\n]*\s-e\s|\bmkfifo\b[^\n]*\bnc\b", re.I)),
    ("preload", re.compile(r"\b(DYLD_INSERT_LIBRARIES|LD_PRELOAD)\s*=", re.I)),
]
# hosts で向け先を差し替えられると危ない主なドメイン
HOSTS_WATCH = re.compile(r"google|apple|microsoft|windowsupdate|github|npmjs|pypi|bank|paypal|amazon|anthropic|openai|claude", re.I)


def run(cmd, timeout=30):
    """コマンドを読み取りの用途で実行し、標準出力を返す。失敗したら None。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return p.stdout + (p.stderr if not p.stdout else "")
    except (OSError, subprocess.SubprocessError):
        return None


def read_text(path, limit=1_000_000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None


class Report:
    def __init__(self):
        self.findings = []
        self.inventory = {"autostart": [], "listening": [], "unsigned_running": [], "extensions": []}
        self.skipped = []
        self._sign_cache = {}

    def add(self, severity, category, title, detail="", path=""):
        self.findings.append({"severity": severity, "category": category, "title": title, "detail": detail, "path": path})

    # ---- 署名 ----
    def signature(self, path):
        """macOS: apple / developer:<名前> / adhoc / unsigned / missing / unknown。Windows: valid / unsigned / ..."""
        if not path:
            return "unknown"
        if path in self._sign_cache:
            return self._sign_cache[path]
        if not os.path.exists(path):
            self._sign_cache[path] = "missing"
            return "missing"
        if len(self._sign_cache) >= MAX_SIGN_CHECKS:
            return "unknown"
        result = "unknown"
        if SYSTEM == "Darwin":
            out = run(["codesign", "-dvv", path], timeout=10) or ""
            if "not signed at all" in out:
                result = "unsigned"
            elif "Signature=adhoc" in out:
                result = "adhoc"
            elif "Authority=Apple Root CA" in out and "Developer ID" not in out and "Apple Development" not in out:
                result = "apple"
            else:
                m = re.search(r"Authority=(Developer ID Application|Apple Distribution|Apple Development|Apple Mac OS Application Signing): ?(.*)", out)
                result = "developer:" + m.group(2).strip() if m else ("apple" if "Platform identifier=" in out else "unknown")
        elif SYSTEM == "Windows":
            ps = "(Get-AuthenticodeSignature -LiteralPath '" + path.replace("'", "''") + "').Status"
            out = (run(["powershell", "-NoProfile", "-Command", ps], timeout=15) or "").strip().lower()
            result = {"valid": "valid", "notsigned": "unsigned", "hashmismatch": "invalid"}.get(out, out or "unknown")
        self._sign_cache[path] = result
        return result

    def judge_executable(self, path, where, category):
        """実行ファイルの置き場所と署名から重さを決め、所見に足す。返り値は署名。"""
        sig = self.signature(path) if SYSTEM in ("Darwin", "Windows") else "unknown"
        risky = bool(RISKY_DIR.search(path or ""))
        hidden = bool(HIDDEN_DIR.search(path or ""))
        weak = sig in ("unsigned", "adhoc", "invalid")
        dev = bool(DEV_DIR.search(path or ""))
        if sig == "missing":
            self.add("medium", category, f"{where}: 実行ファイルが見つからない", "消えたソフトの残骸か、実行時に作られるファイル", path)
        elif risky:
            self.add("high", category, f"{where}: 一時フォルダ・共有フォルダ・ダウンロードから動いている", f"署名: {sig}", path)
        elif weak and hidden and not dev:
            self.add("high", category, f"{where}: 隠しフォルダにある未署名の実行ファイル", f"署名: {sig}", path)
        elif weak and (dev or sig == "adhoc"):
            self.add("low", category, f"{where}: 正式な署名のない実行ファイル（開発ツールに多い）", f"署名: {sig}", path)
        elif weak:
            self.add("medium", category, f"{where}: 未署名の実行ファイル", f"署名: {sig}（自作・開発ツールなら問題ない）", path)
        return sig


# ---------------- macOS ----------------
def mac_settings(r):
    checks = [
        (["spctl", "--status"], "enabled", "Gatekeeper が無効", "high"),
        (["csrutil", "status"], "enabled", "システム整合性保護（SIP）が無効", "high"),
        (["fdesetup", "status"], "On", "FileVault（ディスクの暗号化）が無効", "medium"),
        (["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"], "enabled", "ファイアウォールが無効", "low"),
    ]
    for cmd, ok_word, title, sev in checks:
        out = run(cmd)
        if out is None:
            r.skipped.append(" ".join(cmd))
        elif ok_word not in out:
            r.add(sev, "settings", title, out.strip())
    xp = "/Library/Apple/System/Library/CoreServices/XProtect.bundle/Contents/Info.plist"
    try:
        with open(xp, "rb") as f:
            ver = plistlib.load(f).get("CFBundleShortVersionString")
        age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(xp))).days
        r.add("medium" if age > 60 else "info", "settings", f"XProtect の定義 {ver}（{age} 日前に更新）",
              "60 日以上更新されていなければ、ソフトウェア・アップデートの自動更新を確かめる" if age > 60 else "")
    except (OSError, plistlib.InvalidFileException, ValueError):
        r.skipped.append("XProtect のバージョン")
    out = run(["sw_vers", "-productVersion"])
    if out:
        r.add("info", "settings", f"macOS {out.strip()}", "最新でなければアップデートを当てる")
    out = run(["profiles", "list"]) or ""
    if "attribute" in out or "profileIdentifier" in out:
        r.add("medium", "settings", "構成プロファイルが入っている", "会社の管理用なら問題ない。心当たりがなければ要確認。システム設定 > 一般 > デバイス管理", out.strip()[:500])


def mac_autostart(r):
    dirs = [
        (os.path.join(HOME, "Library/LaunchAgents"), "ユーザーの LaunchAgent"),
        ("/Library/LaunchAgents", "LaunchAgent"),
        ("/Library/LaunchDaemons", "LaunchDaemon"),
    ]
    for d, label in dirs:
        for plist in sorted(glob.glob(os.path.join(d, "*.plist"))):
            try:
                with open(plist, "rb") as f:
                    data = plistlib.load(f)
            except Exception:
                r.add("medium", "autostart", f"{label}: 読めない plist", "壊れているか、権限で読めない", plist)
                continue
            args = data.get("ProgramArguments") or []
            prog = data.get("Program") or (args[0] if args else "")
            line = " ".join(str(a) for a in args) or prog
            entry = {"kind": label, "label": data.get("Label", os.path.basename(plist)), "file": plist, "program": prog}
            r.inventory["autostart"].append(entry)
            for rule, rx in SHELL_RISK:
                if rx.search(line):
                    r.add("high", "autostart", f"{label}: 起動コマンドに {rule}", line[:300], plist)
            if os.path.basename(prog) in ("sh", "bash", "zsh", "python", "python3", "osascript", "curl", "perl", "ruby", "node"):
                inline = any(a in ("-c", "-lc", "-e") for a in args[1:])
                script = next((a for a in args[1:] if isinstance(a, str) and a.startswith("/")), "")
                if RISKY_DIR.search(line) or (script and HIDDEN_DIR.search(script) and not DEV_DIR.search(script)):
                    r.add("high", "autostart", f"{label}: 一時フォルダ・隠しフォルダのスクリプトを自動起動している", line[:300], plist)
                elif inline:
                    r.add("medium", "autostart", f"{label}: シェルに直接書いたコマンドを自動起動している", line[:300], plist)
                elif script and not os.path.exists(script):
                    r.add("low", "autostart", f"{label}: 参照先のスクリプトがない（消したジョブの残骸か、外付けディスク上）", line[:300], plist)
                else:
                    r.add("low", "autostart", f"{label}: スクリプトを自動起動している", line[:300], plist)
            elif prog:
                entry["signature"] = r.judge_executable(prog, label, "autostart")
    out = run(["crontab", "-l"]) or ""
    for ln in out.splitlines():
        if ln.strip() and not ln.lstrip().startswith("#") and "no crontab" not in ln:
            r.inventory["autostart"].append({"kind": "crontab", "label": ln.strip()[:200], "file": "crontab", "program": ""})
            r.add("info", "autostart", "crontab の登録", ln.strip()[:300])
    r.add("info", "autostart", "ログイン項目は自動では読めない",
          "システム設定 > 一般 > ログイン項目と機能拡張 を開いて、見覚えのないものがないか目で確かめる")


def mac_processes(r):
    out = run(["ps", "-axww", "-o", "pid=,user=,comm="]) or ""
    procs = {}
    for ln in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.+)$", ln)
        if m:
            procs[m.group(1)] = (m.group(2), m.group(3).strip())
    seen = set()
    for pid, (user, path) in procs.items():
        if not path.startswith("/") or path in seen:
            continue
        seen.add(path)
        if path.startswith(("/System/", "/usr/libexec/", "/usr/sbin/", "/usr/bin/", "/sbin/", "/bin/")):
            continue
        sig = r.judge_executable(path, f"実行中のプロセス（{user}）", "process")
        if sig in ("unsigned", "adhoc", "invalid"):
            r.inventory["unsigned_running"].append(path)
    return procs


def suspicious_proc(r, path):
    return RISKY_DIR.search(path) or (path in r.inventory["unsigned_running"] and r._sign_cache.get(path) != "adhoc" and not DEV_DIR.search(path))


def lsof_network(r, procs):
    out = run(["lsof", "-nP", "-iTCP", "-iUDP", "-F", "pcnPT"], timeout=60)
    if out is None:
        r.skipped.append("lsof（通信の一覧）")
        return
    pid = cmd = None
    listen, outbound = set(), {}
    for ln in out.splitlines():
        tag, val = ln[:1], ln[1:]
        if tag == "p":
            pid = val
        elif tag == "c":
            cmd = val
        elif tag == "n":
            path = procs.get(pid, ("", cmd))[1] or cmd
            if "->" in val:
                remote = val.split("->", 1)[1]
                if not re.match(r"(127\.|\[::1\]|localhost)", remote):
                    outbound.setdefault(path, set()).add(remote)
            elif val.startswith(("*:", "0.0.0.0:", "[::]:")):
                listen.add((path, val))
    for path, addr in sorted(listen):
        r.inventory["listening"].append(f"{path} {addr}")
        if suspicious_proc(r, path):
            r.add("high", "network", "未署名・不審な場所のプロセスが外から接続を受け付けている", addr, path)
    for path, remotes in sorted(outbound.items()):
        if suspicious_proc(r, path):
            r.add("medium", "network", "未署名・不審な場所のプロセスが外部と通信している", ", ".join(sorted(remotes)[:10]), path)
    r.add("info", "network", f"外から接続を受け付けているもの {len(listen)} 件・外部と通信中のプロセス {len(outbound)} 件",
          "一覧は inventory.listening")


# ---------------- Linux ----------------
def linux_all(r):
    pre = read_text("/etc/ld.so.preload")
    if pre and pre.strip():
        r.add("high", "settings", "/etc/ld.so.preload に共有ライブラリが登録されている", "ルートキットがよく使う仕掛け。心当たりがなければ要調査", pre.strip()[:300])
    out = run(["ufw", "status"]) if shutil.which("ufw") else None
    if out and "inactive" in out:
        r.add("low", "settings", "ファイアウォール（ufw）が無効")
    units = glob.glob(os.path.join(HOME, ".config/systemd/user/*.service")) + glob.glob("/etc/systemd/system/*.service")
    for u in sorted(units):
        txt = read_text(u) or ""
        m = re.search(r"^ExecStart=(.+)$", txt, re.M)
        prog = m.group(1).strip() if m else ""
        r.inventory["autostart"].append({"kind": "systemd", "label": os.path.basename(u), "file": u, "program": prog})
        if RISKY_DIR.search(prog) or any(rx.search(prog) for _, rx in SHELL_RISK):
            r.add("high", "autostart", "systemd サービスが不審なコマンドを起動する", prog[:300], u)
    for f in sorted(glob.glob(os.path.join(HOME, ".config/autostart/*.desktop"))):
        txt = read_text(f) or ""
        m = re.search(r"^Exec=(.+)$", txt, re.M)
        prog = m.group(1).strip() if m else ""
        r.inventory["autostart"].append({"kind": "xdg-autostart", "label": os.path.basename(f), "file": f, "program": prog})
        if RISKY_DIR.search(prog) or HIDDEN_DIR.search(prog):
            r.add("high", "autostart", "ログイン時の自動起動が不審な場所を指す", prog[:300], f)
    out = run(["crontab", "-l"]) or ""
    for ln in out.splitlines():
        if ln.strip() and not ln.lstrip().startswith("#"):
            r.inventory["autostart"].append({"kind": "crontab", "label": ln.strip()[:200], "file": "crontab", "program": ""})
            r.add("info", "autostart", "crontab の登録", ln.strip()[:300])
    procs = {}
    for exe in glob.glob("/proc/[0-9]*/exe"):
        pid = exe.split("/")[2]
        try:
            path = os.readlink(exe)
        except OSError:
            continue
        procs[pid] = ("", path)
        if path.endswith(" (deleted)"):
            r.add("high", "process", "実行ファイルが消されたまま動いているプロセス", f"pid {pid}", path)
        elif RISKY_DIR.search(path):
            r.add("high", "process", "一時フォルダから動いているプロセス", f"pid {pid}", path)
    if shutil.which("lsof"):
        lsof_network(r, procs)
    else:
        out = run(["ss", "-tulnp"]) or ""
        for ln in out.splitlines()[1:]:
            r.inventory["listening"].append(re.sub(r"\s+", " ", ln.strip()))
    r.add("info", "settings", "署名の確認は Linux では行わない", "パッケージ管理（dpkg -S <パス> / rpm -qf <パス>）に属さない実行ファイルを手で確かめる")


# ---------------- Windows ----------------
def ps_json(script):
    out = run(["powershell", "-NoProfile", "-Command", script + " | ConvertTo-Json -Depth 3 -Compress"], timeout=90)
    try:
        data = json.loads(out) if out and out.strip() else []
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else [data]


def win_all(r):
    d = ps_json("Get-MpComputerStatus | Select-Object AntivirusEnabled,RealTimeProtectionEnabled,AntivirusSignatureAge")
    if d is None:
        r.skipped.append("Microsoft Defender の状態")
    elif d:
        s = d[0]
        if not s.get("RealTimeProtectionEnabled"):
            r.add("high", "settings", "Microsoft Defender のリアルタイム保護が無効", "ほかのウイルス対策ソフトが入っていれば正常")
        if (s.get("AntivirusSignatureAge") or 0) > 7:
            r.add("medium", "settings", f"Defender の定義が {s.get('AntivirusSignatureAge')} 日更新されていない")
    run_keys = ps_json(
        "foreach($k in 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run','HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',"
        "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce','HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce'){"
        "if(Test-Path $k){$p=Get-ItemProperty $k; $p.PSObject.Properties | ? {$_.Name -notlike 'PS*'} | % {[pscustomobject]@{Key=$k;Name=$_.Name;Value=[string]$_.Value}}}}"
    ) or []
    for e in run_keys:
        val = e.get("Value", "")
        m = re.match(r'\s*"([^"]+)"|\s*(\S+\.exe)', val, re.I)
        exe = (m.group(1) or m.group(2)) if m else ""
        r.inventory["autostart"].append({"kind": "Run", "label": e.get("Name"), "file": e.get("Key"), "program": val})
        if re.search(r"powershell[^\n]*(-enc|-e\s|downloadstring|iex)|mshta|wscript|cscript|rundll32[^\n]*javascript", val, re.I):
            r.add("high", "autostart", "Run キーがスクリプトを起動する", val[:300], e.get("Key"))
        elif exe:
            r.judge_executable(exe, "Run キー", "autostart")
    startup = glob.glob(os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup\*"))
    startup += glob.glob(os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\StartUp\*"))
    for f in startup:
        if not f.lower().endswith("desktop.ini"):
            r.inventory["autostart"].append({"kind": "Startup", "label": os.path.basename(f), "file": f, "program": ""})
            r.add("info", "autostart", "スタートアップフォルダの項目", "", f)
    tasks = ps_json("Get-ScheduledTask | ? {$_.TaskPath -notlike '\\Microsoft\\*' -and $_.State -ne 'Disabled'} | "
                    "Select-Object TaskName,TaskPath,@{n='Exec';e={($_.Actions | % {$_.Execute + ' ' + $_.Arguments}) -join ' ; '}}") or []
    for t in tasks:
        ex = t.get("Exec") or ""
        r.inventory["autostart"].append({"kind": "ScheduledTask", "label": t.get("TaskPath", "") + t.get("TaskName", ""), "file": "", "program": ex})
        if RISKY_DIR.search(ex) or re.search(r"-enc|downloadstring|iex|mshta", ex, re.I):
            r.add("high", "autostart", "タスクスケジューラが不審なコマンドを起動する", ex[:300], t.get("TaskName"))
    procs = ps_json("Get-CimInstance Win32_Process | ? {$_.ExecutablePath} | Select-Object ProcessId,ExecutablePath") or []
    seen = set()
    for p in procs:
        path = p.get("ExecutablePath") or ""
        if path in seen or path.lower().startswith(r"c:\windows\system32"):
            continue
        seen.add(path)
        sig = r.judge_executable(path, "実行中のプロセス", "process")
        if sig in ("unsigned", "invalid"):
            r.inventory["unsigned_running"].append(path)
    out = run(["netstat", "-ano"]) or ""
    for ln in out.splitlines():
        if "LISTENING" in ln and not re.search(r"127\.0\.0\.1|\[::1\]", ln):
            r.inventory["listening"].append(re.sub(r"\s+", " ", ln.strip()))


# ---------------- 共通 ----------------
def shell_rc(r):
    names = [".zshrc", ".zprofile", ".zshenv", ".bashrc", ".bash_profile", ".profile", ".config/fish/config.fish"]
    for n in names:
        p = os.path.join(HOME, n)
        txt = read_text(p)
        if not txt:
            continue
        for i, ln in enumerate(txt.splitlines(), 1):
            for rule, rx in SHELL_RISK:
                if rx.search(ln):
                    r.add("high", "shell", f"シェルの起動ファイルに {rule}", ln.strip()[:300], f"{p}:{i}")


def hosts(r):
    p = r"C:\Windows\System32\drivers\etc\hosts" if SYSTEM == "Windows" else "/etc/hosts"
    for ln in (read_text(p) or "").splitlines():
        s = ln.split("#", 1)[0].strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 2 and parts[0] not in ("127.0.0.1", "::1", "255.255.255.255", "fe80::1%lo0", "0.0.0.0") \
                and any(HOSTS_WATCH.search(h) for h in parts[1:]):
            r.add("high", "settings", "hosts ファイルが主要サイトの向け先を書き換えている", s, p)


def browser_extensions(r):
    if SYSTEM == "Darwin":
        bases = [os.path.join(HOME, "Library/Application Support", b) for b in ("Google/Chrome", "Microsoft Edge", "BraveSoftware/Brave-Browser")]
    elif SYSTEM == "Windows":
        la = os.environ.get("LOCALAPPDATA", "")
        bases = [os.path.join(la, b, "User Data") for b in (r"Google\Chrome", r"Microsoft\Edge", r"BraveSoftware\Brave-Browser")]
    else:
        bases = [os.path.join(HOME, ".config", b) for b in ("google-chrome", "chromium", "microsoft-edge", "BraveSoftware/Brave-Browser")]
    exts = {}
    for base in bases:
        for manifest in glob.glob(os.path.join(base, "*", "Extensions", "*", "*", "manifest.json")):
            try:
                m = json.loads(read_text(manifest) or "{}")
            except json.JSONDecodeError:
                continue
            parts = manifest.split(os.sep)
            ext_id, profile = parts[-3], os.path.join(os.path.basename(base), parts[-5])
            e = exts.setdefault(ext_id, {"name": ext_name(m, os.path.dirname(manifest)) or ext_id, "profiles": set(), "perms": set(), "path": manifest})
            e["profiles"].add(profile)
            e["perms"].update(p for p in (m.get("permissions", []) + m.get("host_permissions", [])) if isinstance(p, str))
    for ext_id, e in sorted(exts.items(), key=lambda x: x[1]["name"]):
        broad = e["perms"] & {"<all_urls>", "*://*/*", "http://*/*", "https://*/*"}
        strong = sorted(e["perms"] & {"debugger", "nativeMessaging", "proxy", "webRequestBlocking", "cookies", "management"})
        r.inventory["extensions"].append(f"{e['name']} ({ext_id})")
        if broad and strong:
            r.add("medium", "browser", f"拡張機能「{e['name']}」が全サイトの読み書きと強い権限を持つ",
                  "権限: " + ", ".join(strong) + "／入っている場所: " + ", ".join(sorted(e["profiles"])) + "。心当たりがなければ削除を検討", e["path"])


def ext_name(m, folder):
    name = m.get("name", "")
    mm = re.match(r"__MSG_(\w+)__", name)
    if not mm:
        return name
    for loc in (m.get("default_locale"), "ja", "en", "en_US"):
        msgs = read_text(os.path.join(folder, "_locales", loc or "-", "messages.json"))
        if msgs:
            try:
                d = {k.lower(): v for k, v in json.loads(msgs).items()}
                return d.get(mm.group(1).lower(), {}).get("message", "")
            except (json.JSONDecodeError, AttributeError):
                pass
    return ""


def agent_configs(r):
    p = os.path.join(HOME, ".claude/settings.json")
    try:
        data = json.loads(read_text(p) or "{}")
    except json.JSONDecodeError:
        return
    if data.get("hooks"):
        r.add("info", "agent", "Claude Code のフックが設定されている",
              "AI エージェントの設定も侵入口になる。中身の点検は skill-security-audit で行う", p)


def diff(now, old_path):
    try:
        with open(old_path, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"error": f"前回の結果を読めない: {e}"}
    oi = old.get("inventory", {})
    key = lambda e: f"{e.get('kind')}|{e.get('label')}|{e.get('program')}"
    old_auto = {key(e) for e in oi.get("autostart", [])}
    out = {
        "since": old.get("checked_at"),
        "new_autostart": [e for e in now["inventory"]["autostart"] if key(e) not in old_auto],
        "new_listening": sorted(set(now["inventory"]["listening"]) - set(oi.get("listening", []))),
        "new_unsigned_running": sorted(set(now["inventory"]["unsigned_running"]) - set(oi.get("unsigned_running", []))),
        "new_extensions": sorted(set(now["inventory"]["extensions"]) - set(oi.get("extensions", []))),
    }
    old_titles = {(f["title"], f["path"]) for f in old.get("findings", [])}
    out["new_findings"] = [f for f in now["findings"] if f["severity"] in ("high", "medium") and (f["title"], f["path"]) not in old_titles]
    return out


def notify(text):
    if SYSTEM == "Darwin":
        run(["osascript", "-e", f"display notification {json.dumps(text)} with title \"pc-security-checkup\""])
    elif SYSTEM == "Linux" and shutil.which("notify-send"):
        run(["notify-send", "pc-security-checkup", text])
    elif SYSTEM == "Windows":
        run(["msg", "*", "pc-security-checkup: " + text])


def main():
    ap = argparse.ArgumentParser(description="PC の安全性を読むだけで点検する")
    ap.add_argument("--save", help="結果を保存するフォルダ")
    ap.add_argument("--diff", help="比べる前回の結果（.json）。latest で --save のフォルダの最新を使う")
    ap.add_argument("--notify", action="store_true", help="前回から増えたものがあれば OS の通知を出す")
    a = ap.parse_args()

    r = Report()
    if SYSTEM == "Darwin":
        mac_settings(r)
        mac_autostart(r)
        lsof_network(r, mac_processes(r))
    elif SYSTEM == "Linux":
        linux_all(r)
    elif SYSTEM == "Windows":
        win_all(r)
    else:
        r.skipped.append(f"未対応の OS: {SYSTEM}")
    shell_rc(r)
    hosts(r)
    browser_extensions(r)
    agent_configs(r)

    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    r.findings.sort(key=lambda f: order.get(f["severity"], 9))
    result = {
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "os": f"{SYSTEM} {platform.release()}",
        "user": os.environ.get("USER") or os.environ.get("USERNAME"),
        "summary": {s: sum(1 for f in r.findings if f["severity"] == s) for s in order},
        "findings": r.findings,
        "inventory": r.inventory,
        "skipped": r.skipped,
        "note": "既知の手口に基づく点検で、安全を保証するものではない。ウイルス対策ソフトの代わりにはならない。",
    }

    old_path = a.diff
    if a.diff == "latest":
        old_path = None
        if a.save:
            prev = sorted(glob.glob(os.path.join(os.path.expanduser(a.save), "checkup-*.json")))
            old_path = prev[-1] if prev else None
    if old_path:
        result["diff"] = diff(result, old_path)

    if a.save:
        d = os.path.expanduser(a.save)
        os.makedirs(d, exist_ok=True)
        name = "checkup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        result["saved_to"] = os.path.join(d, name)

    if a.notify and result.get("diff") and "error" not in result["diff"]:
        dd = result["diff"]
        n = len(dd["new_autostart"]) + len(dd["new_unsigned_running"]) + len(dd["new_extensions"]) + len(dd["new_findings"])
        if n:
            notify(f"前回から気になる変化が {n} 件あります。Claude Code で「PC の点検結果を見て」と頼んでください")

    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print()


if __name__ == "__main__":
    main()
