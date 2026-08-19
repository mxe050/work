from __future__ import annotations

from panelist_dialogue_v3 import DIALOGUE as _BASE_DIALOGUE

DIALOGUE = [dict(item) for item in _BASE_DIALOGUE]

_REPLACEMENTS = {
    "図四は、MCIDという表現からMIDという表現へ重点が移っている理由を示しています。":
        "図四は、MCIDという表現からMIDという表現へ重点が移っている理由を、説明用に単純化して示しています。",
    "臨床家が重要性を決めるのではなく、患者さんにとって重要かを中心に考える、という意味ですね。":
        "ただし、MCIDという言葉が、必ず医師主導の判断だけを意味するわけではないのですね。",
    "そのとおりです。大切なのは、用語の文字だけではなく、患者重要アウトカムと患者の価値観を基準にすることです。":
        "はい。大切なのは、用語の文字だけではなく、患者重要アウトカムと患者の価値観を基準にすることです。",
}

for item in DIALOGUE:
    if item.get("text") in _REPLACEMENTS:
        item["text"] = _REPLACEMENTS[item["text"]]

assert len(DIALOGUE) == 99
