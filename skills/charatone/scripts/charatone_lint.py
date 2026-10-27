#!/usr/bin/env python3
"""charatone_lint: 台詞の語尾の型を話者ごとに集計し、偏りを警告する。

読む書式:
  - id：台詞            （箇条書き。id の後ろに（条件）が付いてもよい）
  id：台詞
  名前「台詞」
\\n は吹き出し内の改行。見出し（# で始まる行）を場面の区切りとみなす。
"""
import argparse
import re
import sys
from collections import Counter, defaultdict

TYPES = {
    1: "言い切り", 2: "噛みしめる", 3: "柔らかい", 4: "念押し", 5: "軽い/下町",
    6: "女言葉", 7: "古風", 8: "年寄り", 9: "訛り", 10: "ぶつ切り", 11: "言いさし",
    12: "問いかけ", 13: "端正敬語", 14: "柔らか敬語", 15: "軽い敬語", 16: "老人敬語",
    17: "慇懃", 18: "崩れ敬語", 19: "命令形", 0: "その他",
}

# 上から順に判定する（長いもの・特徴的なものを先に）
RULES = [
    (18, r"(でございます？|です、.*ございます)$"),
    (17, r"(存じます|かと|でございましょう|ではございませんか)$"),
    (16, r"(ですな|ますな|ますまい|ございます|ございません|ですかな|ましょうな)$"),
    (15, r"(っす|ですって|ますって|すよね|ですよね|ますよね)$"),
    (14, r"(ですね|ますね|ですよ|ますよ|でしょうか|でしょう|ますか|ですか|ませんか|くださいね|ください)$"),
    (13, r"(です|でした|ます|ました|ません|ませんでした|ましょう)$"),
    (8, r"(じゃのう|のう|わい|じゃて|じゃ)$"),
    (7, r"(ぬ|おる|おった|おったぞ|せよ|であろう|であるか|がよい|よかろう|ではない|まい|てやる|てやろう)$"),
    (6, r"(わね|わよ|のよ|かしら|わ|よね)$"),
    (9, r"(ねえ|ねぇ|べ|だで|やけん|やろ|へん)$"),
    (5, r"(じゃん|じゃねえか|っての|んだよ|だぜ|ぜ|かよ|だろうが)$"),
    (12, r"(だろ？|だろう？|じゃない？|よな？|か？|の？|？)$"),
    (4, r"(だろ|だろう|だぞ|ぞ|だって|だっての|だよな|よな)$"),
    (3, r"(だね|だよ|かな|よね|ね|よ|だったよ|しよう|しようか|ようか|[おこそとのほもよろごぞどぼぽ]う|[おこそとのほもよろごぞどぼぽ]うか)$"),
    (2, r"(だな|だなぁ|だったな|なぁ|な|か|さ|とさ|だとさ)$"),
    (11, r"(けど|けれど|けれども|し|から|って|のに|ので|が)$"),
    (19, r"(しろ|せよ|ろ|れ|え|け|せ|て|ね|め|げ|べ|ぜ|で|こい|来い|な)$"),
    (1, r"(だ|だった|する|した|ない|なかった|いる|いた|ある|あった|う|く|す|つ|る|む|ぶ|ぐ|た)$"),
]

TAIL = re.compile(r"[。、…！!？?」』）)\s―ー〜~]+$")
LINE_PATTERNS = [
    re.compile(r"^\s*-\s*([A-Za-z0-9_]+)(?:（[^）]*）)?：(.+)$"),
    re.compile(r"^\s*([^\s「」：#\-][^「」：]{0,15})：(.+)$"),
    re.compile(r"^\s*([^\s「」#\-]{1,15})「(.+)」\s*$"),
]


VOC = re.compile(r"^(殿下|陛下|王子|閣下|父上|母上|兄上|元帥|将軍|若殿|殿|侯|公|[一-龥ァ-ヶー]{1,6}(殿|様|さん))$")
INTERJ = re.compile(r"^(はて|ああ|うむ|ほう|ふむ|ふん|はい|いいえ|ええ|うん|おう|へえ|えっ?|あ|あっ|あの|その|いや|よし|よしっ|なるほど|左様|失礼|すみません|ありがとう|……)+$")


def classify(sentence: str) -> int:
    q = sentence.endswith(("？", "?"))
    s = TAIL.sub("", sentence)
    if not s or INTERJ.match(s) or VOC.match(s):
        return 0
    if q and not re.search(r"(か|の|だろ|だろう|じゃない|よな|ですか|ますか)$", s):
        s_q = s + "？"
        if re.search(RULES[11][1], s_q):
            return 12
    if q:
        s = s + "？"
    for t, pat in RULES:
        if re.search(pat, s):
            return t
    # 名詞・体言で終わる短い文はぶつ切り
    if len(s) <= 8:
        return 10
    return 0


def last_sentence(text: str) -> str:
    text = text.replace("\\n", "").strip()
    parts = [p for p in re.split(r"(?<=[。！？!?])", text) if p.strip()]
    return parts[-1].strip() if parts else text


def all_sentences(text: str):
    text = text.replace("\\n", "")
    return [p.strip() for p in re.split(r"(?<=[。！？!?])", text) if p.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--speaker", help="この話者だけ詳しく出す")
    ap.add_argument("--min", type=int, default=8, help="集計に出す最少台詞数")
    ap.add_argument("--max-type1", type=float, default=0.35)
    ap.add_argument("--max-rare", type=float, default=0.15, help="型8・型10の上限")
    a = ap.parse_args()

    stats = defaultdict(Counter)
    samples = defaultdict(lambda: defaultdict(list))
    warns = []
    for f in a.files:
        run = []  # 同じ場面で型1が続いた (file, line, speaker)
        for n, raw in enumerate(open(f, encoding="utf-8"), 1):
            line = raw.rstrip("\n")
            if line.startswith("#") or "――" in line[:3]:
                run = []
                continue
            m = None
            for pat in LINE_PATTERNS:
                m = pat.match(line)
                if m:
                    break
            if not m:
                continue
            sp, text = m.group(1).strip(), m.group(2).strip()
            if sp in ("条件", "勝利", "敗北", "書式", "注", "備考"):
                continue
            if sp.startswith("（") or text.startswith("（"):
                continue
            for s in all_sentences(text):
                t = classify(s)
                stats[sp][t] += 1
                if len(samples[sp][t]) < 3:
                    samples[sp][t].append(s)
            t_last = classify(last_sentence(text))
            if t_last == 1:
                run.append((n, sp))
                if len(run) == 3:
                    warns.append(f"{f}:{run[0][0]}: 型1（言い切り）で終わる台詞が3回続く（{'・'.join(x[1] for x in run)}）")
            else:
                run = []

    tops = {}
    print("話者別の語尾の分布（文単位）")
    for sp, c in sorted(stats.items(), key=lambda x: -sum(x[1].values())):
        total = sum(c.values())
        if total < a.min and sp != a.speaker:
            continue
        top = c.most_common(3)
        tops[sp] = top[0][0]
        r1 = c[1] / total
        dist = "  ".join(f"{t}:{TYPES[t]} {v*100/total:.0f}%" for t, v in top)
        print(f"  {sp:<14} {total:>4}文  型1 {r1*100:>3.0f}%  | {dist}")
        if r1 > a.max_type1:
            warns.append(f"{sp}: 型1（言い切り）が {r1*100:.0f}%（上限 {a.max_type1*100:.0f}%）")
        for t in (8, 10):
            r = c[t] / total
            if r > a.max_rare:
                warns.append(f"{sp}: 型{t}（{TYPES[t]}）が {r*100:.0f}%（上限 {a.max_rare*100:.0f}%）")
        if sp == a.speaker:
            for t, v in c.most_common():
                print(f"      {t:>2} {TYPES[t]:<8} {v:>4}  例: {' / '.join(samples[sp][t])}")

    for w in warns:
        print("[WARN]", w)
    if not warns:
        print("警告なし")


if __name__ == "__main__":
    main()
