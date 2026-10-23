"""Strict local avatar matching for the name-hidden Wbox ranking.

Reference images and capture artifacts stay on the collector computer. The
matcher never guesses: every reference must be explicitly approved and every
query must clear both an absolute similarity threshold and a best-vs-second
margin before a snapshot can be written.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from score_parser import parse_score


STAGE_NAMES = {"入围赛": "qualifier", "突围赛": "breakthrough", "巅峰赛": "final"}
STAGE_RE = re.compile(r"^(入围赛|突围赛|巅峰赛)[｜|]")
BOUNDS_RE = re.compile(r"^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$")
PROFILE_RE = re.compile(r"^(?:\d{2}[生花]|团体)$")
REFERENCE_VERSION = 1


@dataclass
class AvatarObservation:
    position: int
    score: int
    approximate: bool
    signature: str
    bounds: tuple[int, int, int, int]
    image: Image.Image
    screen_index: int


def parse_bounds(value: str) -> tuple[int, int, int, int]:
    match = BOUNDS_RE.match(value or "")
    if not match:
        return 0, 0, 0, 0
    return tuple(int(part) for part in match.groups())


def _text_nodes(element: ET.Element) -> list[ET.Element]:
    return [node for node in element.iter("node") if node.attrib.get("text", "").strip()]


def _stage_from_root(root: ET.Element) -> str:
    texts = [node.attrib.get("text", "").strip() for node in root.iter("node")]
    if "剧综人物" not in texts:
        raise ValueError("当前界面不是“剧综人物”榜单")
    label = next((text for text in texts if STAGE_RE.match(text)), None)
    if not label:
        raise ValueError("无法确认当前赛段")
    return STAGE_NAMES[STAGE_RE.match(label).group(1)]


def _score_after_label(label: ET.Element, value_group: ET.Element) -> tuple[int, bool]:
    seen = False
    for node in _text_nodes(value_group):
        if node is label:
            seen = True
            continue
        if seen:
            try:
                return parse_score(node.attrib["text"])
            except ValueError:
                continue
    raise ValueError("候选卡片中没有可解析的推荐值")


def _card_signature(card: ET.Element) -> str:
    texts = [
        node.attrib["text"].strip()
        for node in _text_nodes(card)
        if node.attrib.get("class") == "android.widget.TextView"
    ]
    profile = next((text for text in texts if PROFILE_RE.match(text)), "")
    works = next((text for text in texts if text.startswith("《")), "")
    if not profile or not works:
        raise ValueError("候选卡片缺少可用于一致性检查的分类或作品信息")
    return f"{profile}\u241f{works}"


def crop_avatar(screen: Image.Image, bounds: tuple[int, int, int, int]) -> Image.Image:
    """Crop the upper portion of the circular avatar while excluding labels."""

    x1, y1, x2, _ = bounds
    center_x = (x1 + x2) // 2
    box = (center_x - 66, y1 - 66, center_x + 66, y1 + 36)
    if box[0] < 0 or box[1] < 0 or box[2] > screen.width or box[3] > screen.height:
        raise ValueError(f"头像裁剪区域越界: {box}")
    image = screen.crop(box).convert("RGB").resize((132, 102), Image.Resampling.LANCZOS)
    if float(np.asarray(image.convert("L"), dtype=np.float32).std()) < 12:
        raise ValueError("头像区域缺少足够图像信息")
    return image


def observations_from_files(
    xml_path: str | Path,
    screenshot_path: str | Path,
    *,
    screen_index: int,
    min_candidates: int = 15,
    expected_candidates: int | None = None,
    min_avatar_y: int = 500,
    max_avatar_y: int = 1600,
) -> tuple[str, int, list[AvatarObservation]]:
    root = ET.parse(xml_path).getroot()
    stage = _stage_from_root(root)
    parent_map = {child: parent for parent in root.iter() for child in parent}
    labels = [node for node in root.iter("node") if node.attrib.get("text", "").strip() == "推荐值"]
    if len(labels) < min_candidates:
        raise ValueError(f"UI 中仅有 {len(labels)} 张候选卡片，低于下限 {min_candidates}")
    if expected_candidates is not None:
        if len(labels) < expected_candidates:
            raise ValueError(f"UI 中有 {len(labels)} 张候选卡片，少于目标 {expected_candidates} 张")
        # The page lazily appends lower-ranked candidates while scrolling. The
        # monitor deliberately keeps its configured top-N scope.
        labels = labels[:expected_candidates]

    screen = Image.open(screenshot_path).convert("RGB")
    observations = []
    for position, label in enumerate(labels, start=1):
        value_group = parent_map.get(label)
        card = parent_map.get(value_group) if value_group is not None else None
        if value_group is None or card is None:
            raise ValueError("推荐值节点缺少候选卡片父节点")
        bounds = parse_bounds(card.attrib.get("bounds", ""))
        if not bounds[2] or not (min_avatar_y <= bounds[1] <= max_avatar_y):
            continue
        score, approximate = _score_after_label(label, value_group)
        observations.append(
            AvatarObservation(
                position=position,
                score=score,
                approximate=approximate,
                signature=_card_signature(card),
                bounds=bounds,
                image=crop_avatar(screen, bounds),
                screen_index=screen_index,
            )
        )
    return stage, len(labels), observations


def _masked_pixels(image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    data = np.asarray(image.resize((96, 72), Image.Resampling.LANCZOS), dtype=np.float32)
    height, width = data.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width]
    ellipse = ((xx - width * 0.5) / (width * 0.46)) ** 2 + (
        (yy - height * 0.64) / (height * 0.67)
    ) ** 2 <= 1
    # Ranking badges overlap the upper-left of top-three avatars.
    rank_badge = (xx < width * 0.34) & (yy < height * 0.43)
    mask = ellipse & ~rank_badge
    return data, mask


def _dhash(image: Image.Image, hash_size: int = 16) -> np.ndarray:
    gray = np.asarray(
        image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    )
    return gray[:, 1:] > gray[:, :-1]


def avatar_similarity(left: Image.Image, right: Image.Image) -> float:
    left_data, mask = _masked_pixels(left)
    right_data, right_mask = _masked_pixels(right)
    mask &= right_mask
    pixel_similarity = 1.0 - float(np.abs(left_data[mask] - right_data[mask]).mean() / 255.0)

    left_hash = _dhash(left)
    right_hash = _dhash(right)
    hash_similarity = 1.0 - float(np.count_nonzero(left_hash != right_hash) / left_hash.size)

    histogram_scores = []
    for channel in range(3):
        left_hist, _ = np.histogram(left_data[:, :, channel][mask], bins=16, range=(0, 256))
        right_hist, _ = np.histogram(right_data[:, :, channel][mask], bins=16, range=(0, 256))
        left_hist = left_hist / max(1, left_hist.sum())
        right_hist = right_hist / max(1, right_hist.sum())
        histogram_scores.append(float(np.minimum(left_hist, right_hist).sum()))
    histogram_similarity = sum(histogram_scores) / len(histogram_scores)
    return 0.55 * pixel_similarity + 0.30 * hash_similarity + 0.15 * histogram_similarity


def collect_avatar_observations(
    adb,
    serial: str,
    artifact_dir: str | Path,
    *,
    capture_ui_xml: Callable,
    capture_screenshot: Callable,
    run_adb: Callable,
    min_candidates: int = 15,
    expected_candidates: int | None = None,
    max_scrolls: int = 12,
    scroll_wait_seconds: float = 1.5,
) -> tuple[str, list[AvatarObservation]]:
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    selected: dict[int, AvatarObservation] = {}
    stage = None
    known_total = 0
    previous_total = 0
    stable_total_screens = 0

    for screen_index in range(max_scrolls + 1):
        xml_path = artifact_dir / f"screen_{screen_index}.xml"
        image_path = artifact_dir / f"screen_{screen_index}.png"
        capture_ui_xml(adb, serial, xml_path)
        capture_screenshot(adb, serial, image_path)
        current_stage, total_cards, visible = observations_from_files(
            xml_path,
            image_path,
            screen_index=screen_index,
            min_candidates=min_candidates,
            expected_candidates=expected_candidates,
        )
        if total_cards < known_total:
            raise ValueError("滚动采集期间候选卡片数量减少")
        known_total = max(known_total, total_cards)
        if total_cards == previous_total:
            stable_total_screens += 1
        else:
            stable_total_screens = 0
        previous_total = total_cards
        if stage is None:
            stage = current_stage
        elif stage != current_stage:
            raise ValueError("滚动采集期间赛段发生变化")

        for observation in visible:
            previous = selected.get(observation.position)
            if previous is not None:
                overlap_similarity = avatar_similarity(previous.image, observation.image)
                if overlap_similarity < 0.84:
                    raise ValueError(
                        f"滚动期间第 {observation.position} 位头像发生变化 "
                        f"({overlap_similarity:.3f})"
                    )
            # Prefer a crop near the vertical center, away from sticky headers
            # and the fixed bottom action bar.
            if previous is None or abs(observation.bounds[1] - 1050) < abs(previous.bounds[1] - 1050):
                selected[observation.position] = observation

        target_total = expected_candidates or known_total
        if (
            len(selected) == target_total
            and target_total >= min_candidates
            and (expected_candidates is not None or stable_total_screens >= 1)
        ):
            break
        if screen_index < max_scrolls:
            run_adb(
                adb,
                "shell",
                "input",
                "swipe",
                "540",
                "1500",
                "540",
                "950",
                "600",
                serial=serial,
            )
            time.sleep(scroll_wait_seconds)

    target_total = expected_candidates or known_total
    if len(selected) != target_total:
        missing = sorted(set(range(1, target_total + 1)) - set(selected))
        raise ValueError(f"多屏截图仅取得 {len(selected)} 张完整头像，缺少位置 {missing}")
    return stage or "", [selected[position] for position in sorted(selected)]


def _historical_profiles(xml_path: str | Path) -> list[dict]:
    root = ET.parse(xml_path).getroot()
    parent_map = {child: parent for parent in root.iter() for child in parent}
    profiles = []
    labels = [node for node in root.iter("node") if node.attrib.get("text", "").strip() == "推荐值"]
    for label in labels:
        value_group = parent_map[label]
        card = parent_map[value_group]
        score, _ = _score_after_label(label, value_group)
        text_nodes = [
            node
            for node in _text_nodes(card)
            if node.attrib.get("class") == "android.widget.TextView"
        ]
        name = next(
            (
                node.attrib["text"].strip()
                for node in text_nodes
                if not PROFILE_RE.match(node.attrib["text"].strip())
                and not node.attrib["text"].strip().startswith("《")
                and node.attrib["text"].strip() != "推荐值"
                and not re.search(r"\d+(?:\.\d+)?[wW万亿]?", node.attrib["text"].strip())
            ),
            None,
        )
        if not name:
            raise ValueError("历史 UI 文件中缺少人物名称")
        profiles.append(
            {"candidate_name": name, "score": score, "signature": _card_signature(card)}
        )
    return profiles


def _suggest_names(
    observations: list[AvatarObservation], historical_xml: str | Path
) -> dict[int, tuple[str, str]]:
    histories = _historical_profiles(historical_xml)[: len(observations)]
    current_by_signature: dict[str, list[AvatarObservation]] = defaultdict(list)
    history_by_signature: dict[str, list[dict]] = defaultdict(list)
    for observation in observations:
        current_by_signature[observation.signature].append(observation)
    for profile in histories:
        history_by_signature[profile["signature"]].append(profile)

    suggestions = {}
    if set(current_by_signature) != set(history_by_signature):
        raise ValueError("当前卡片分类/作品信息与历史名单不一致，无法安全生成建议")
    for signature, current_group in current_by_signature.items():
        history_group = history_by_signature[signature]
        if len(current_group) != len(history_group):
            raise ValueError("同类候选人数与历史名单不一致，无法安全生成建议")
        current_group.sort(key=lambda item: item.score, reverse=True)
        history_group.sort(key=lambda item: item["score"], reverse=True)
        basis = "metadata_exact" if len(current_group) == 1 else "metadata_and_score_order"
        for observation, profile in zip(current_group, history_group):
            suggestions[observation.position] = (profile["candidate_name"], basis)
    return suggestions


def _font(size: int):
    for path in (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
    ):
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def build_reference_gallery(
    observations: list[AvatarObservation],
    historical_xml: str | Path,
    reference_dir: str | Path,
    *,
    stage: str | None = None,
) -> Path:
    reference_dir = Path(reference_dir)
    image_dir = reference_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    suggestions = _suggest_names(observations, historical_xml)
    entries = []

    for observation in observations:
        name, basis = suggestions[observation.position]
        candidate_id = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
        filename = f"{observation.position:02d}_{candidate_id}.png"
        observation.image.save(image_dir / filename)
        entries.append(
            {
                "position_at_enrollment": observation.position,
                "candidate_id": candidate_id,
                "candidate_name": name,
                "score_at_enrollment": observation.score,
                "signature": observation.signature,
                "image": f"images/{filename}",
                "suggestion_basis": basis,
                "approved": False,
            }
        )

    manifest = {
        "version": REFERENCE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "approved": False,
        "candidates": entries,
    }
    manifest_path = reference_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    cell_width, cell_height = 330, 220
    column_count = 3
    row_count = (len(observations) + column_count - 1) // column_count
    sheet = Image.new(
        "RGB", (cell_width * column_count, cell_height * row_count), "#17100f"
    )
    draw = ImageDraw.Draw(sheet)
    title_font = _font(24)
    detail_font = _font(18)
    for index, (observation, entry) in enumerate(zip(observations, entries)):
        column, row = index % column_count, index // column_count
        x, y = column * cell_width, row * cell_height
        sheet.paste(observation.image.resize((198, 153), Image.Resampling.LANCZOS), (x + 10, y + 10))
        draw.text((x + 218, y + 18), f"#{entry['position_at_enrollment']}", fill="#f4c272", font=title_font)
        draw.text((x + 218, y + 58), entry["candidate_name"], fill="#fff4e8", font=detail_font)
        draw.text((x + 218, y + 92), f"{entry['score_at_enrollment']:,}", fill="#c6b8ad", font=detail_font)
        draw.text((x + 10, y + 174), "待人工确认", fill="#ff8e73", font=detail_font)
        draw.rectangle((x, y, x + cell_width - 1, y + cell_height - 1), outline="#684433", width=2)
    sheet.save(reference_dir / "contact_sheet.png")
    return manifest_path


def _load_reference_manifest(
    reference_dir: str | Path, *, require_approved: bool
) -> tuple[dict, list[dict]]:
    reference_dir = Path(reference_dir)
    manifest_path = reference_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"头像参考库不存在: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != REFERENCE_VERSION:
        raise ValueError("头像参考库版本不受支持")
    candidates = manifest.get("candidates", [])
    if not candidates:
        raise ValueError("头像参考库没有候选人")
    if require_approved and (
        not manifest.get("approved") or any(not item.get("approved") for item in candidates)
    ):
        raise ValueError("头像参考库尚未经过人工确认，已拒绝自动匹配")
    names = [str(item.get("candidate_name", "")).strip() for item in candidates]
    candidate_ids = [str(item.get("candidate_id", "")).strip() for item in candidates]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("头像参考库人物名称为空或重复")
    if any(not candidate_id for candidate_id in candidate_ids) or len(set(candidate_ids)) != len(
        candidate_ids
    ):
        raise ValueError("头像参考库人物 ID 为空或重复")

    reference_root = reference_dir.resolve()
    references = []
    for item in candidates:
        image_path = (reference_dir / item["image"]).resolve()
        if reference_root not in image_path.parents:
            raise ValueError("头像参考图片路径超出参考库目录")
        if not image_path.is_file():
            raise ValueError(f"头像参考图片不存在: {image_path}")
        references.append({**item, "loaded_image": Image.open(image_path).convert("RGB")})
    return manifest, references


def load_approved_references(reference_dir: str | Path) -> list[dict]:
    _, references = _load_reference_manifest(reference_dir, require_approved=True)
    return references


def approve_reference_gallery(
    reference_dir: str | Path, confirmed_names: list[str]
) -> Path:
    """Approve only when the caller repeats every displayed name in rank order."""

    reference_dir = Path(reference_dir)
    manifest_path = reference_dir / "manifest.json"
    manifest, _ = _load_reference_manifest(reference_dir, require_approved=False)
    expected_names = [item["candidate_name"] for item in manifest["candidates"]]
    if confirmed_names != expected_names:
        raise ValueError(
            "确认名称与参考库顺序不完全一致；请按联系表排名逐一核对后重新输入"
        )
    for item in manifest["candidates"]:
        item["approved"] = True
    manifest["approved"] = True
    manifest["approved_at"] = datetime.now(timezone.utc).isoformat()
    temporary_path = manifest_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary_path.replace(manifest_path)
    return manifest_path


def _strict_matches(
    observations: list[AvatarObservation],
    references: list[dict],
    *,
    threshold: float,
    margin: float,
) -> list[dict]:
    if len(observations) != len(references):
        raise ValueError(
            f"头像数量 {len(observations)} 与参考库数量 {len(references)} 不一致"
        )
    matches = []
    used_ids = set()
    for observation in observations:
        ranked = sorted(
            (
                (avatar_similarity(observation.image, reference["loaded_image"]), reference)
                for reference in references
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, best = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        if best_score < threshold:
            raise ValueError(
                f"第 {observation.position} 位头像最高相似度 {best_score:.3f} "
                f"低于阈值 {threshold:.3f}"
            )
        if best_score - second_score < margin:
            raise ValueError(
                f"第 {observation.position} 位头像匹配差距 {best_score - second_score:.3f} "
                f"低于阈值 {margin:.3f}"
            )
        if observation.signature != best.get("signature"):
            raise ValueError(
                f"第 {observation.position} 位头像虽接近 {best['candidate_name']}，"
                "但分类/作品信息不一致"
            )
        if best["candidate_id"] in used_ids:
            raise ValueError(f"头像参考 {best['candidate_name']} 被重复匹配")
        used_ids.add(best["candidate_id"])
        matches.append(
            {
                "observation": observation,
                "reference": best,
                "similarity": best_score,
                "second_similarity": second_score,
            }
        )

    expected_ids = {reference["candidate_id"] for reference in references}
    if used_ids != expected_ids:
        raise ValueError("并非所有头像都完成一对一唯一匹配")
    return matches


def _match_diagnostics(matches: list[dict]) -> list[dict]:
    return [
        {
            "position": match["observation"].position,
            "candidate_name": match["reference"]["candidate_name"],
            "similarity": round(match["similarity"], 4),
            "margin": round(match["similarity"] - match["second_similarity"], 4),
        }
        for match in matches
    ]


def validate_reference_gallery(
    observations: list[AvatarObservation],
    reference_dir: str | Path,
    *,
    threshold: float = 0.88,
    margin: float = 0.05,
    stage: str,
) -> list[dict]:
    """Validate pending or approved references without creating database rows."""

    manifest, references = _load_reference_manifest(reference_dir, require_approved=False)
    enrolled_stage = manifest.get("stage")
    if enrolled_stage and enrolled_stage != stage:
        raise ValueError(
            f"当前赛段 {stage} 与头像参考库赛段 {enrolled_stage} 不一致"
        )
    return _match_diagnostics(
        _strict_matches(observations, references, threshold=threshold, margin=margin)
    )


def match_observations(
    observations: list[AvatarObservation],
    reference_dir: str | Path,
    *,
    threshold: float = 0.88,
    margin: float = 0.05,
    observed_at: datetime | None = None,
    stage: str = "final",
) -> tuple[list[dict], list[dict]]:
    manifest, references = _load_reference_manifest(reference_dir, require_approved=True)
    enrolled_stage = manifest.get("stage")
    if enrolled_stage and enrolled_stage != stage:
        raise ValueError(
            f"当前赛段 {stage} 与头像参考库赛段 {enrolled_stage} 不一致"
        )
    matches = _strict_matches(
        observations, references, threshold=threshold, margin=margin
    )
    timestamp = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    records = []
    for match in matches:
        observation = match["observation"]
        reference = match["reference"]
        records.append(
            {
                "stage": stage,
                "category": "剧综人物",
                "candidate_id": reference["candidate_id"],
                "candidate_name": reference["candidate_name"],
                "score": observation.score,
                "score_approx": observation.approximate,
                "rank": None,
                "observed_at": timestamp,
                "source": "mumu_avatar_match",
            }
        )
    return records, _match_diagnostics(matches)
