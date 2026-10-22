"""Read the visible Wbox ranking from a permitted Android/MuMu UI tree.

This module opens the public activity deep link and calls Android's read-only
UI dump/screenshot commands. It does not tap, swipe, log in, vote, solve
challenges, or bypass app controls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from score_parser import parse_score
from storage import insert_snapshots


load_dotenv()

WEIBO_PACKAGE = "com.sina.weibo"
DEFAULT_ACTIVITY_URL = "https://m.weibo.cn/c/wbox?id=l331zrkexk&cid=1420"

STAGE_NAMES = {
    "入围赛": "qualifier",
    "突围赛": "breakthrough",
    "巅峰赛": "final",
}
STAGE_RE = re.compile(r"^(入围赛|突围赛|巅峰赛)[｜|]")
COMMON_ADB_PATHS = (
    Path(r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"),
    Path(r"C:\Program Files\Netease\MuMu\nx_main\adb.exe"),
    Path(r"D:\Program Files\Netease\MuMu\nx_device\15.0\shell\adb.exe"),
    Path(r"C:\Program Files\Netease\MuMu\nx_device\15.0\shell\adb.exe"),
)
COMMON_MUMU_CLI_PATHS = (
    Path(r"D:\Program Files\Netease\MuMu\nx_main\mumu-cli.exe"),
    Path(r"C:\Program Files\Netease\MuMu\nx_main\mumu-cli.exe"),
)


def resolve_adb(cli_path: str | None = None) -> Path:
    candidates = [cli_path, os.getenv("ADB_PATH"), shutil.which("adb")]
    candidates.extend(str(path) for path in COMMON_ADB_PATHS)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RuntimeError("找不到 adb.exe；请用 --adb-path 或 ADB_PATH 指定 MuMu 自带的 ADB")


def run_adb(
    adb: Path,
    *args: str,
    serial: str | None = None,
    accept_nonzero_if: str | None = None,
) -> str:
    command = [str(adb)]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if completed.returncode and not (accept_nonzero_if and accept_nonzero_if in combined):
        detail = combined
        raise RuntimeError(f"ADB 命令失败 ({completed.returncode}): {detail}")
    return completed.stdout.strip()


def list_adb_devices(adb: Path) -> list[str]:
    output = run_adb(adb, "devices", "-l")
    devices = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def resolve_mumu_cli() -> Path | None:
    configured = os.getenv("MUMU_CLI_PATH")
    candidates = ([Path(configured)] if configured else []) + list(COMMON_MUMU_CLI_PATHS)
    return next((path for path in candidates if path.is_file()), None)


def auto_connect_mumu() -> list[str]:
    """Ask MuMu for every running instance and connect its advertised ADB port."""

    cli = resolve_mumu_cli()
    if cli is None:
        return []
    completed = subprocess.run(
        [str(cli), "info", "--vmindex", "all"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        return []
    try:
        instances = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []

    connected = []
    for index, info in instances.items():
        if not info.get("is_android_started"):
            continue
        result = subprocess.run(
            [str(cli), "adb", "--vmindex", str(index), "--cmd", "connect"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            connected.append(f"{info.get('adb_host_ip', '127.0.0.1')}:{info.get('adb_port')}")
    if connected:
        time.sleep(1)
    return connected


def choose_device(adb: Path, requested_serial: str | None = None) -> str:
    devices = list_adb_devices(adb)
    if not devices or (requested_serial and requested_serial not in devices):
        auto_connect_mumu()
        devices = list_adb_devices(adb)

    if requested_serial:
        if requested_serial not in devices:
            raise RuntimeError(f"指定设备 {requested_serial!r} 未连接；当前设备: {devices}")
        return requested_serial
    if len(devices) != 1:
        raise RuntimeError(f"需要且只能有一个可用 Android 设备；当前设备: {devices}")
    return devices[0]


def capture_ui_xml(adb: Path, serial: str, destination: Path) -> None:
    remote = "/sdcard/weibo_monitor_window.xml"
    # Some MuMu Android images return 139 after uiautomator has already
    # completed the dump.  Accept that only when its success message exists;
    # the pulled file is validated immediately afterward.
    run_adb(
        adb,
        "shell",
        "uiautomator",
        "dump",
        remote,
        serial=serial,
        accept_nonzero_if="UI hierchary dumped to",
    )
    run_adb(adb, "pull", remote, str(destination), serial=serial)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("ADB 未生成有效的 UI XML")


def capture_screenshot(adb: Path, serial: str, destination: Path) -> None:
    remote = "/sdcard/weibo_monitor_screen.png"
    run_adb(adb, "shell", "screencap", "-p", remote, serial=serial)
    run_adb(adb, "pull", remote, str(destination), serial=serial)


def refresh_activity(adb: Path, serial: str, url: str, wait_seconds: float) -> None:
    """Reload the activity in Weibo without screen-coordinate automation."""

    if not url.startswith("https://") or any(char in url for char in "\r\n'\";|`$"):
        raise ValueError("活动链接必须是安全的 HTTPS URL")
    package_path = run_adb(adb, "shell", "pm", "path", WEIBO_PACKAGE, serial=serial)
    if not package_path.startswith("package:"):
        raise RuntimeError("MuMu 中未找到官方微博 App，无法刷新活动页面")
    output = run_adb(
        adb,
        "shell",
        "am",
        "start",
        "-W",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        # adb shell joins its arguments into a remote shell command. Escape the
        # query separator so ``&cid=...`` is not interpreted as a background job.
        url.replace("&", r"\&"),
        "-p",
        WEIBO_PACKAGE,
        serial=serial,
    )
    if "Error:" in output or "Exception" in output:
        raise RuntimeError(f"重新打开微博活动失败: {output}")
    time.sleep(wait_seconds)


def _text_nodes(element: ET.Element) -> list[ET.Element]:
    return [node for node in element.iter("node") if node.attrib.get("text", "").strip()]


def _candidate_from_label(
    label: ET.Element, parent_map: dict[ET.Element, ET.Element]
) -> tuple[str, int, bool]:
    value_group = parent_map.get(label)
    card = parent_map.get(value_group) if value_group is not None else None
    if value_group is None or card is None:
        raise ValueError("推荐值节点缺少候选卡片父节点")

    score = None
    approximate = None
    seen_label = False
    for node in _text_nodes(value_group):
        if node is label:
            seen_label = True
            continue
        if seen_label:
            try:
                score, approximate = parse_score(node.attrib["text"])
                break
            except ValueError:
                continue
    if score is None or approximate is None:
        raise ValueError("候选卡片中没有可解析的推荐值")

    name = None
    for node in _text_nodes(card):
        if node is label:
            break
        if node.attrib.get("class") == "android.widget.TextView":
            name = node.attrib["text"].strip()
            break
    if not name:
        raise ValueError("候选卡片中没有可解析的人物名称")
    return name, score, approximate


def parse_ui_xml(
    xml_path: str | Path | ET.Element,
    *,
    observed_at: datetime | None = None,
    min_candidates: int = 3,
    expected_candidates: int | None = None,
) -> tuple[str, list[dict]]:
    root = xml_path if isinstance(xml_path, ET.Element) else ET.parse(xml_path).getroot()
    nodes = list(root.iter("node"))
    texts = [node.attrib.get("text", "").strip() for node in nodes]

    if "剧综人物" not in texts:
        raise ValueError("当前界面不是“剧综人物”榜单，已拒绝写入")

    stage_label = next((text for text in texts if STAGE_RE.match(text)), None)
    if not stage_label:
        raise ValueError("无法从当前界面确认赛段，已拒绝写入")
    stage_name = STAGE_RE.match(stage_label).group(1)
    stage = STAGE_NAMES[stage_name]

    parent_map = {child: parent for parent in root.iter() for child in parent}
    labels = [node for node in nodes if node.attrib.get("text", "").strip() == "推荐值"]
    parsed = [_candidate_from_label(label, parent_map) for label in labels]

    if len(parsed) < min_candidates:
        raise ValueError(f"仅解析到 {len(parsed)} 位人物，低于安全下限 {min_candidates}，已拒绝写入")
    if expected_candidates is not None and len(parsed) != expected_candidates:
        raise ValueError(
            f"解析到 {len(parsed)} 位人物，但预期 {expected_candidates} 位，已拒绝写入"
        )

    names = [name for name, _, _ in parsed]
    if len(set(names)) != len(names):
        raise ValueError("解析到重复人物名称，已拒绝写入")

    timestamp = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    records = []
    for name, score, approximate in parsed:
        records.append(
            {
                "stage": stage,
                "category": "剧综人物",
                "candidate_id": hashlib.sha256(name.encode("utf-8")).hexdigest()[:16],
                "candidate_name": name,
                "score": score,
                "score_approx": approximate,
                # UI XML has no reliable rank text.  The dashboard will label
                # score sorting as an observed order rather than official rank.
                "rank": None,
                "observed_at": timestamp,
                "source": "mumu_uiautomator",
            }
        )
    return stage, records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读采集 MuMu 中的微博剧综人物榜单")
    parser.add_argument("--xml", help="解析已有 window.xml；不访问模拟器")
    parser.add_argument("--adb-path", help="MuMu 自带 adb.exe 的路径")
    parser.add_argument("--serial", help="ADB 设备序列号；仅连接一个设备时可省略")
    parser.add_argument("--dry-run", action="store_true", help="只打印解析结果，不写数据库")
    parser.add_argument("--quiet", action="store_true", help="仅输出适合定时任务日志的状态行")
    parser.add_argument("--save-artifacts", action="store_true", help="保存 XML 和同屏截图到 debug/")
    parser.add_argument("--min-candidates", type=int, default=15)
    parser.add_argument("--retries", type=int, default=3, help="实时 UI 树不完整时的重试次数")
    parser.add_argument(
        "--refresh-strategy",
        choices=("deeplink", "none"),
        default=os.getenv("MUMU_REFRESH_STRATEGY", "deeplink"),
        help="采集前刷新方式；默认用微博深链重新载入活动",
    )
    parser.add_argument(
        "--refresh-wait-seconds",
        type=float,
        default=float(os.getenv("MUMU_REFRESH_WAIT_SECONDS", "8")),
        help="重新载入活动后等待页面渲染的秒数",
    )
    parser.add_argument(
        "--activity-url",
        default=os.getenv("WEIBO_ACTIVITY_URL", DEFAULT_ACTIVITY_URL),
        help="需要在微博 App 中重新打开的活动链接",
    )
    parser.add_argument(
        "--expected-candidates",
        type=int,
        help="可选：锁定完整榜单人数；不设置时仅执行最少人数和重复项校验",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.retries < 1:
        raise ValueError("--retries 必须至少为 1")
    if args.refresh_wait_seconds < 0:
        raise ValueError("--refresh-wait-seconds 不能小于 0")
    live_capture = not bool(args.xml)
    if args.xml:
        xml_path = Path(args.xml)
    else:
        adb = resolve_adb(args.adb_path)
        serial = choose_device(adb, args.serial or os.getenv("ADB_SERIAL"))
        if args.refresh_strategy == "deeplink":
            refresh_activity(adb, serial, args.activity_url, args.refresh_wait_seconds)
        if args.save_artifacts:
            debug_dir = Path("debug")
            debug_dir.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            xml_path = debug_dir / f"window_{stamp}.xml"
            capture_screenshot(adb, serial, debug_dir / f"screen_{stamp}.png")
        else:
            debug_dir = Path("debug")
            debug_dir.mkdir(exist_ok=True)
            xml_path = debug_dir / "window_live.xml"
    last_error = None
    attempts = args.retries if live_capture else 1
    for attempt in range(1, attempts + 1):
        if live_capture:
            capture_ui_xml(adb, serial, xml_path)
        try:
            stage, records = parse_ui_xml(
                xml_path,
                min_candidates=args.min_candidates,
            )
            expected_candidates = args.expected_candidates
            if expected_candidates is not None and len(records) != expected_candidates:
                raise ValueError(
                    f"{stage} 赛段解析到 {len(records)} 位人物，但预期 {expected_candidates} 位"
                )
            break
        except ValueError as exc:
            last_error = exc
            if attempt == attempts:
                raise RuntimeError(f"连续 {attempts} 次未取得完整榜单 UI 树: {last_error}") from exc
            time.sleep(2)
    preview = sorted(records, key=lambda item: item["score"], reverse=True)
    approximate_count = sum(record["score_approx"] for record in records)
    if args.quiet:
        print(
            f"COLLECTION_OK stage={stage} candidates={len(records)} "
            f"approximate={approximate_count} minimum={args.min_candidates} "
            f"expected={expected_candidates or 'unset'} "
            f"refresh={args.refresh_strategy if live_capture else 'offline'}"
        )
    else:
        print(
            f"赛段={stage}，解析人物={len(records)}，"
            f"近似分数={approximate_count}，"
            f"完整性预期={expected_candidates or '未配置'}"
        )
        print(json.dumps(preview, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("DRY_RUN no database write" if args.quiet else "DRY RUN：未写入数据库")
        return
    insert_snapshots(records)
    print("DATABASE_WRITE_OK" if args.quiet else "快照已写入数据库")


if __name__ == "__main__":
    main()
