from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

BASE = Path(__file__).with_name("panelist_dialogue_v3_final.py")
spec = importlib.util.spec_from_file_location("panelist_dialogue_v3_final_base", BASE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
DIALOGUE = [dict(item) for item in module.DIALOGUE]

_OVERRIDES = {
    10: '小さな変化から大きな変化まで、いくつかの場面を小さいと大きいの交互に見る方法ですね。',
    22: 'そして、何を変えて判断するのかを理解してから回答へ進みます。',
    34: '術後のみの群間差と、患者内変化を群間差として比較する２つのパターンがあります。ただし文献では略語の使い方が統一されていません。',
    40: 'はい。今回のフォームも、リスク比などの相対的でなく千人中何人の脳卒中を追加で防げるかという絶対的な群間差として読んでください。',
    52: 'ここからは、論文に付随した動画を改変したものです。。',
    53: '視聴が終わったら、この研修動画へ戻ります。',
    54: 'それでは、切り替わります。',
    56: 'ここからは、現在のGoogleフォームの画面に沿って進めます。',
    60: '十分な説明を受けた患者の集団なら、この効果を重要と考えるかを推定して答えます。',
    61: '匿名にする場合はメールアドレスなしですが誰が回答したか不明になり回答が集まらない場合困ります。',
    64: '現在のフォームは、脳卒中の患者に対する治療の仮想CQです。',
    65: 'CQとPICOまで記載してもよいでしょう。',
    66: 'また、九十パーセント以上は、超えるという表現のが精確ですが、そこまでこだわらない方が良いです。',
    83: '治療の費用、副作用、通院負担などは、今回は考慮しませんが、最終的な推奨文決定時には考慮します。',
    84: 'アンケート後の転換点の読み方を、回答後の分析という立場から簡単に解説します。',
    91: '判断に使った考え方、分かりにくかった言葉、二つの選択肢で迷った理由などを書いて構いませんが、できるだけ判断してください。',
    93: '本番では、まず一人で独立して回答します。',
    96: '後から勘違いで間違っているということがないように不明な点は事前に質問してください。。',
    97: 'これで事前研修は終了です。実際のアンケートへ進んでください。',
}
for index, text in _OVERRIDES.items():
    DIALOGUE[index]["text"] = text

assert len(DIALOGUE) == 99
assert hashlib.sha256("\n".join(item["text"] for item in DIALOGUE).encode("utf-8")).hexdigest() == "82aaf1f6409396234ef14067f8f844d2657b181c94b6b71eed672c5c5aece597"
