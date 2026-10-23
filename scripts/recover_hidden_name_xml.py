"""Recover complete snapshots from downloaded UI XML versions with hidden names.

Identity mapping is constrained by the approved avatar manifest. Unique
category/work signatures map directly; candidates sharing one signature map by
their score order, which is also checked across the full database timeline.
The default mode is read-only. Pass --write only after reviewing the preflight.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from avatar_matching import _card_signature, _score_after_label, _stage_from_root
from storage import fetch_snapshots, insert_snapshots


FILENAME_RE = re.compile(r"^window_live_(\d{1,2})_(\d{2})\.xml$")


def timestamp_from_filename(path: Path, date: str, hour_offset: int) -> str:
    match = FILENAME_RE.match(path.name)
    if not match:
        raise ValueError(f"文件名不符合 window_live_H_MM.xml: {path.name}")
    hour, minute = (int(value) for value in match.groups())
    hour += hour_offset
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"文件名时间无效: {path.name}")
    local_date = datetime.strptime(date, "%Y-%m-%d")
    local_time = local_date.replace(
        hour=hour, minute=minute, second=0, microsecond=0, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    return local_time.astimezone(timezone.utc).isoformat()


def parse_hidden_xml(path: Path) -> tuple[str, list[dict]]:
    root = ET.parse(path).getroot()
    stage = _stage_from_root(root)
    parent_map = {child: parent for parent in root.iter() for child in parent}
    labels = [
        node
        for node in root.iter("node")
        if node.attrib.get("text", "").strip() == "推荐值"
    ]
    observations = []
    for position, label in enumerate(labels, start=1):
        value_group = parent_map.get(label)
        card = parent_map.get(value_group) if value_group is not None else None
        if value_group is None or card is None:
            raise ValueError(f"{path.name}: 推荐值节点缺少卡片父节点")
        score, approximate = _score_after_label(label, value_group)
        observations.append(
            {
                "position": position,
                "score": score,
                "score_approx": approximate,
                "signature": _card_signature(card),
            }
        )
    return stage, observations


def map_observations(observations: list[dict], candidates: list[dict], path: Path) -> list[dict]:
    if len(observations) != len(candidates):
        raise ValueError(
            f"{path.name}: XML 有 {len(observations)} 人，参考库有 {len(candidates)} 人"
        )
    observed_groups: dict[str, list[dict]] = defaultdict(list)
    reference_groups: dict[str, list[dict]] = defaultdict(list)
    for observation in observations:
        observed_groups[observation["signature"]].append(observation)
    for candidate in candidates:
        reference_groups[candidate["signature"]].append(candidate)
    if Counter({key: len(value) for key, value in observed_groups.items()}) != Counter(
        {key: len(value) for key, value in reference_groups.items()}
    ):
        raise ValueError(f"{path.name}: 分类/作品签名集合与已批准参考库不一致")

    mapped = []
    for signature, group in observed_groups.items():
        references = reference_groups[signature]
        group.sort(key=lambda item: item["score"], reverse=True)
        references.sort(key=lambda item: item["score_at_enrollment"], reverse=True)
        if len(group) != len(references):
            raise ValueError(f"{path.name}: 同签名候选人数发生变化")
        for observation, candidate in zip(group, references):
            mapped.append({**observation, **candidate})
    names = [item["candidate_name"] for item in mapped]
    if len(set(names)) != len(candidates):
        raise ValueError(f"{path.name}: 姓名映射不唯一")
    return mapped


def main() -> None:
    parser = argparse.ArgumentParser(description="恢复人物名称隐藏期间下载的历史 UI XML")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--date", default="2026-10-23", help="文件对应的北京时间日期")
    parser.add_argument(
        "--hour-offset",
        type=int,
        default=12,
        help="文件名小时到24小时制的偏移；5:00 PM 下载文件默认加12",
    )
    parser.add_argument(
        "--reference-dir", type=Path, default=PROJECT_ROOT / "avatar_references"
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    manifest = json.loads((args.reference_dir / "manifest.json").read_text(encoding="utf-8"))
    candidates = manifest.get("candidates", [])
    if not manifest.get("approved") or manifest.get("stage") != "final":
        raise RuntimeError("需要已批准的 final 赛段头像参考库")
    if len(candidates) != 15 or any(not item.get("approved") for item in candidates):
        raise RuntimeError("头像参考库必须包含 15 个已批准人物")

    file_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in args.files]
    if len(set(file_hashes)) != len(file_hashes):
        raise RuntimeError("下载文件中存在内容完全相同的重复版本")

    records = []
    snapshot_summary = []
    for path in args.files:
        stage, observations = parse_hidden_xml(path)
        if stage != manifest["stage"]:
            raise RuntimeError(f"{path.name}: 赛段 {stage} 与参考库不一致")
        mapped = map_observations(observations, candidates, path)
        observed_at = timestamp_from_filename(path, args.date, args.hour_offset)
        for item in mapped:
            records.append(
                {
                    "stage": stage,
                    "category": "剧综人物",
                    "candidate_id": item["candidate_id"],
                    "candidate_name": item["candidate_name"],
                    "score": item["score"],
                    "score_approx": item["score_approx"],
                    "rank": None,
                    "observed_at": observed_at,
                    "source": "recovered_onedrive_xml",
                }
            )
        snapshot_summary.append(
            {
                "file": path.name,
                "observed_at": observed_at,
                "candidates": len(mapped),
                "maximum": max(item["score"] for item in mapped),
                "minimum": min(item["score"] for item in mapped),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:12],
            }
        )

    target_times = [item["observed_at"] for item in snapshot_summary]
    if len(set(target_times)) != len(target_times):
        raise RuntimeError("两个文件被映射到同一采样时间")
    if len(records) != len(args.files) * len(candidates):
        raise RuntimeError("恢复记录数量不完整")

    existing = fetch_snapshots(stage="final", hours=12)
    existing_at_targets = [row for row in existing if row["observed_at"] in target_times]
    if existing_at_targets:
        raise RuntimeError("数据库已存在一个或多个目标整点快照，请先核对后再处理")

    timeline: dict[str, list[tuple[datetime, int, str]]] = defaultdict(list)
    for row in existing + records:
        timeline[row["candidate_name"]].append(
            (datetime.fromisoformat(row["observed_at"]), int(row["score"]), row["source"])
        )
    expected_names = {item["candidate_name"] for item in candidates}
    if not expected_names.issubset(timeline):
        raise RuntimeError("数据库边界快照缺少参考库人物")
    for name in expected_names:
        points = sorted(timeline[name])
        for previous, current in zip(points, points[1:]):
            if current[1] < previous[1]:
                raise RuntimeError(
                    f"{name} 分值逆序: {previous[0].isoformat()}={previous[1]} -> "
                    f"{current[0].isoformat()}={current[1]}"
                )

    snapshot_summary.sort(key=lambda item: item["observed_at"])
    print(json.dumps(snapshot_summary, ensure_ascii=False, indent=2))
    print(f"RECOVERY_VALID snapshots={len(snapshot_summary)} rows={len(records)}")
    if args.write:
        insert_snapshots(records)
        print("RECOVERY_WRITE_OK")
    else:
        print("DRY_RUN no database write")


if __name__ == "__main__":
    main()
