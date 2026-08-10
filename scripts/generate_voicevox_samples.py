#!/usr/bin/env python3
"""Generate short Japanese VOICEVOX audition samples for the NMA video.

The script talks to a running VOICEVOX Engine HTTP server, discovers speaker
IDs by speaker/style name, synthesizes several female and male candidates, and
creates two combined dialogue previews.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Any

BASE_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021").rstrip("/")
OUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output/voice_samples"))
SPEED_SCALE = float(os.environ.get("SPEED_SCALE", "1.25"))
PRE_PHONEME = float(os.environ.get("PRE_PHONEME_LENGTH", "0.08"))
POST_PHONEME = float(os.environ.get("POST_PHONEME_LENGTH", "0.08"))

FEMALE_TEXT = (
    "ネットワークメタ分析という言葉は聞いたことがあります。"
    "でも、治療を一位、二位、三位とランキングする分析、"
    "というくらいの理解です。"
)

MALE_TEXT = (
    "それだけの理解では危険です。"
    "ネットワークメタ分析の本質は、複数の治療を順位づけることではありません。"
    "直接比較と間接比較をつないで、複数の治療を同じ統計的な枠組みで比較する方法です。"
)

CANDIDATES = [
    {"key": "female_metan", "role": "female", "speaker": "四国めたん", "style": "ノーマル", "text": FEMALE_TEXT},
    {"key": "female_tsumugi", "role": "female", "speaker": "春日部つむぎ", "style": "ノーマル", "text": FEMALE_TEXT},
    {"key": "female_himari", "role": "female", "speaker": "冥鳴ひまり", "style": "ノーマル", "text": FEMALE_TEXT},
    {"key": "male_ryusei", "role": "male", "speaker": "青山龍星", "style": "ノーマル", "text": MALE_TEXT},
    {"key": "male_takehiro", "role": "male", "speaker": "玄野武宏", "style": "ノーマル", "text": MALE_TEXT},
    {"key": "male_kenzaki", "role": "male", "speaker": "剣崎雌雄", "style": "ノーマル", "text": MALE_TEXT},
]


def request_bytes(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    timeout: int = 180,
) -> bytes:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    headers: dict[str, str] = {}
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def request_json(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
) -> Any:
    return json.loads(request_bytes(method, path, params=params, json_body=json_body).decode("utf-8"))


def wait_for_engine() -> None:
    last_error: Exception | None = None
    for _ in range(180):
        try:
            version = request_bytes("GET", "/version", timeout=5).decode("utf-8").strip()
            print(f"VOICEVOX Engine ready: {version}")
            return
        except Exception as exc:  # noqa: BLE001 - we want a robust readiness loop
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"VOICEVOX Engine did not become ready: {last_error}")


def find_style_id(speakers: list[dict[str, Any]], speaker_name: str, style_name: str) -> tuple[int, str]:
    for speaker in speakers:
        if speaker.get("name") != speaker_name:
            continue
        styles = speaker.get("styles", [])
        for style in styles:
            if style.get("name") == style_name:
                return int(style["id"]), str(style["name"])
        if styles:
            first = styles[0]
            return int(first["id"]), str(first.get("name", ""))
    available = ", ".join(sorted(str(s.get("name")) for s in speakers))
    raise KeyError(f"Speaker not found: {speaker_name}. Available: {available}")


def synthesize(text: str, style_id: int, destination: Path) -> dict[str, Any]:
    query = request_json(
        "POST",
        "/audio_query",
        params={"text": text, "speaker": style_id},
    )
    query["speedScale"] = SPEED_SCALE
    query["pitchScale"] = 0.0
    query["intonationScale"] = 1.0
    query["volumeScale"] = 1.0
    query["prePhonemeLength"] = PRE_PHONEME
    query["postPhonemeLength"] = POST_PHONEME
    query["outputSamplingRate"] = 48000
    query["outputStereo"] = False

    wav_bytes = request_bytes(
        "POST",
        "/synthesis",
        params={"speaker": style_id, "enable_interrogative_upspeak": "true"},
        json_body=query,
    )
    destination.write_bytes(wav_bytes)

    with wave.open(str(destination), "rb") as wav_file:
        duration = wav_file.getnframes() / float(wav_file.getframerate())
        info = {
            "duration_seconds": round(duration, 3),
            "sample_rate": wav_file.getframerate(),
            "channels": wav_file.getnchannels(),
            "sample_width": wav_file.getsampwidth(),
        }
    return info


def concatenate_wavs(paths: list[Path], destination: Path, silence_seconds: float = 0.12) -> None:
    if not paths:
        raise ValueError("No WAV files supplied")

    with wave.open(str(paths[0]), "rb") as first:
        params = first.getparams()
        frames = [first.readframes(first.getnframes())]
        sample_rate = first.getframerate()
        channels = first.getnchannels()
        sample_width = first.getsampwidth()

    silence_frames = int(sample_rate * silence_seconds)
    silence = b"\x00" * silence_frames * channels * sample_width

    for path in paths[1:]:
        with wave.open(str(path), "rb") as wav_file:
            if (
                wav_file.getframerate() != sample_rate
                or wav_file.getnchannels() != channels
                or wav_file.getsampwidth() != sample_width
            ):
                raise ValueError(f"WAV format mismatch: {path}")
            frames.append(silence)
            frames.append(wav_file.readframes(wav_file.getnframes()))

    with wave.open(str(destination), "wb") as output:
        output.setparams(params)
        output.writeframes(b"".join(frames))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wait_for_engine()

    speakers = request_json("GET", "/speakers")
    (OUT_DIR / "speaker_catalog.json").write_text(
        json.dumps(speakers, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest: dict[str, Any] = {
        "engine_url": BASE_URL,
        "speedScale": SPEED_SCALE,
        "prePhonemeLength": PRE_PHONEME,
        "postPhonemeLength": POST_PHONEME,
        "samples": [],
        "errors": [],
    }
    generated: dict[str, Path] = {}

    for candidate in CANDIDATES:
        try:
            style_id, actual_style = find_style_id(
                speakers, str(candidate["speaker"]), str(candidate["style"])
            )
            destination = OUT_DIR / f"{candidate['key']}.wav"
            audio_info = synthesize(str(candidate["text"]), style_id, destination)
            generated[str(candidate["key"])] = destination
            manifest["samples"].append(
                {
                    **candidate,
                    "style_id": style_id,
                    "actual_style": actual_style,
                    "file": destination.name,
                    **audio_info,
                }
            )
            print(f"Generated {destination} ({audio_info['duration_seconds']} s)")
        except Exception as exc:  # noqa: BLE001 - keep producing remaining auditions
            message = f"{candidate['key']}: {type(exc).__name__}: {exc}"
            print(message, file=sys.stderr)
            manifest["errors"].append(message)

    preview_pairs = [
        ("preview_metan_ryusei.wav", "female_metan", "male_ryusei"),
        ("preview_tsumugi_takehiro.wav", "female_tsumugi", "male_takehiro"),
        ("preview_himari_kenzaki.wav", "female_himari", "male_kenzaki"),
    ]
    for filename, female_key, male_key in preview_pairs:
        if female_key in generated and male_key in generated:
            concatenate_wavs(
                [generated[female_key], generated[male_key]], OUT_DIR / filename
            )
            manifest.setdefault("previews", []).append(
                {"file": filename, "female": female_key, "male": male_key}
            )

    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not generated:
        print("No samples were generated", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
