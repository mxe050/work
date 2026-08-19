from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

SPEAKERS = ["冥鳴ひまり", "青山龍星"]


def run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def media_duration(path: Path) -> float:
    result = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)
    ], capture=True)
    return float(json.loads(result.stdout)["format"]["duration"])


def import_dialogue(path: Path) -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("dialogue_v3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import dialogue: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = getattr(module, "DIALOGUE")
    if not isinstance(data, list) or not data:
        raise ValueError("DIALOGUE must be a non-empty list")
    return data


def voice_text(text: str) -> str:
    replacements = {
        "Minimally Important Difference": "ミニマリー インポータント ディファレンス",
        "Minimum Important Difference": "ミニマム インポータント ディファレンス",
        "Googleフォーム": "グーグルフォーム",
        "Google": "グーグル",
        "VOICEVOX": "ボイスボックス",
        "YouTube": "ユーチューブ",
        "QRコード": "キューアールコード",
        "MCID": "エムシーアイディー",
        "MID": "エムアイディー",
        "MIC": "エムアイシー",
        "MDC": "エムディーシー",
        "GRADE": "グレード",
        "Group Analysis": "グループ アナリシス",
    }
    result = text
    for before, after in replacements.items():
        result = result.replace(before, after)
    return result.replace("vs", "対")


def wait_engine(base_url: str, timeout: int = 240) -> str:
    end = time.time() + timeout
    last: Exception | None = None
    while time.time() < end:
        try:
            response = requests.get(f"{base_url}/version", timeout=5)
            if response.ok:
                return response.text.strip()
        except Exception as exc:
            last = exc
        time.sleep(2)
    raise RuntimeError(f"VOICEVOX engine did not become ready: {last}")


def resolve_speaker_ids(base_url: str) -> dict[str, int]:
    response = requests.get(f"{base_url}/speakers", timeout=30)
    response.raise_for_status()
    speakers = response.json()
    resolved: dict[str, int] = {}
    for target in SPEAKERS:
        speaker = next((s for s in speakers if s.get("name") == target or target in s.get("name", "")), None)
        if speaker is None:
            raise RuntimeError(f"Speaker not found: {target}")
        styles = speaker.get("styles") or []
        if not styles:
            raise RuntimeError(f"No styles for speaker: {target}")
        style = next((s for s in styles if "ノーマル" in s.get("name", "")), styles[0])
        resolved[target] = int(style["id"])
        print(f"speaker {target}: {resolved[target]} ({style.get('name')})", flush=True)
    return resolved


def request(method: str, url: str, **kwargs: Any) -> requests.Response:
    last: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.request(method, url, timeout=180, **kwargs)
            response.raise_for_status()
            return response
        except Exception as exc:
            last = exc
            print(f"request failed {attempt + 1}/4: {url}: {exc}", flush=True)
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"Request failed: {url}: {last}")


def synthesize(base_url: str, speaker_id: int, text: str, out: Path, speed: float) -> None:
    query = request(
        "POST", f"{base_url}/audio_query",
        params={"text": voice_text(text), "speaker": speaker_id},
    ).json()
    query["speedScale"] = speed
    query["pitchScale"] = 0.0
    query["intonationScale"] = 1.0
    query["volumeScale"] = 1.0
    query["prePhonemeLength"] = 0.08
    query["postPhonemeLength"] = 0.10
    data = request(
        "POST", f"{base_url}/synthesis",
        params={"speaker": speaker_id, "enable_interrogative_upspeak": True},
        json=query,
        headers={"Content-Type": "application/json"},
    ).content
    out.write_bytes(data)


def normalize(raw: Path, normalized: Path, gap: float) -> tuple[float, float]:
    raw_duration = media_duration(raw)
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(raw),
        "-af", f"apad=pad_dur={gap:.3f}",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(normalized),
    ])
    return raw_duration, media_duration(normalized)


def dialogue_digest(dialogue: list[dict[str, Any]]) -> str:
    canonical = json.dumps(dialogue, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--voicevox-url", default=os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021"))
    parser.add_argument("--speed", type=float, default=1.15)
    args = parser.parse_args()

    out = args.output
    raw_dir = out / "raw"
    wav_dir = out / "wav"
    raw_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)

    dialogue = import_dialogue(args.script)
    version = wait_engine(args.voicevox_url)
    speaker_ids = resolve_speaker_ids(args.voicevox_url)
    manifest: dict[str, Any] = {
        "engine_version": version,
        "speed": args.speed,
        "dialogue_count": len(dialogue),
        "dialogue_sha256": dialogue_digest(dialogue),
        "speaker_ids": speaker_ids,
        "segments": [],
    }

    cumulative = 0.0
    for index, item in enumerate(dialogue, 1):
        raw = raw_dir / f"{index:03d}.wav"
        normalized = wav_dir / f"{index:03d}.wav"
        synthesize(args.voicevox_url, speaker_ids[item["speaker"]], item["text"], raw, args.speed)
        gap = 0.22 + float(item.get("hold_after", 0.0))
        raw_duration, duration = normalize(raw, normalized, gap)
        segment = {
            "index": index,
            "speaker": item["speaker"],
            "name": item["name"],
            "slide": item["slide"],
            "text": item["text"],
            "file": f"wav/{index:03d}.wav",
            "raw_duration": raw_duration,
            "duration": duration,
            "start": cumulative,
            "end": cumulative + duration,
            "gap": gap,
        }
        manifest["segments"].append(segment)
        cumulative += duration
        print(f"[{index:03d}/{len(dialogue)}] {item['speaker']} {duration:.2f}s", flush=True)

    manifest["total_duration"] = cumulative
    (out / "audio_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "engine_version.txt").write_text(version + "\n", encoding="utf-8")
    print(json.dumps({
        "dialogue_count": len(dialogue),
        "total_duration": cumulative,
        "dialogue_sha256": manifest["dialogue_sha256"],
        "engine_version": version,
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
