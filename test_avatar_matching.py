import json
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw

from avatar_matching import (
    AvatarObservation,
    avatar_similarity,
    ensure_ranking_top,
    first_candidate_bounds,
    match_observations,
    validate_reference_gallery,
)


def patterned_avatar(color, diagonal=False):
    image = Image.new("RGB", (132, 102), color)
    draw = ImageDraw.Draw(image)
    if diagonal:
        draw.line((12, 82, 112, 8), fill="white", width=14)
    else:
        draw.ellipse((32, 18, 100, 86), fill="white")
    return image


class AvatarSimilarityTests(unittest.TestCase):
    @staticmethod
    def _ranking_xml(first_y: int) -> str:
        cards = []
        for index in range(15):
            y1 = first_y + index * 10
            cards.append(
                f'<node bounds="[100,{y1}][300,{y1 + 300}]">'
                '<node bounds="[100,0][300,0]">'
                '<node text="推荐值" class="android.widget.TextView"/>'
                '<node text="1.0w" class="android.widget.TextView"/>'
                '</node></node>'
            )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hierarchy><node text="剧综人物"/>'
            '<node text="巅峰赛｜测试"/>'
            + "".join(cards)
            + '</hierarchy>'
        )

    def test_first_candidate_bounds(self):
        directory = Path.cwd() / f".test-avatar-top-{uuid4().hex}"
        directory.mkdir()
        try:
            path = directory / "window.xml"
            path.write_text(self._ranking_xml(720), encoding="utf-8")
            self.assertEqual(first_candidate_bounds(path), (100, 720, 300, 1020))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_top_reset_swipes_until_rank_one_is_visible(self):
        directory = Path.cwd() / f".test-avatar-top-{uuid4().hex}"
        directory.mkdir()
        try:
            states = iter((0, 720))
            swipes = []

            def capture_ui_xml(_adb, _serial, destination):
                destination.write_text(self._ranking_xml(next(states)), encoding="utf-8")

            def run_adb(_adb, *args, **kwargs):
                swipes.append((args, kwargs))

            count, bounds = ensure_ranking_top(
                Path("adb.exe"),
                "serial",
                directory,
                capture_ui_xml=capture_ui_xml,
                run_adb=run_adb,
                swipe_wait_seconds=0,
            )

            self.assertEqual(count, 1)
            self.assertEqual(bounds, (100, 720, 300, 1020))
            self.assertEqual(len(swipes), 1)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_same_avatar_scores_above_different_avatar(self):
        first = patterned_avatar("#9a3412")
        second = patterned_avatar("#1d4ed8", diagonal=True)
        self.assertGreater(avatar_similarity(first, first), avatar_similarity(first, second))

    def test_strict_one_to_one_match(self):
        directory = Path.cwd() / f".test-avatar-{uuid4().hex}"
        image_dir = directory / "images"
        image_dir.mkdir(parents=True)
        try:
            first = patterned_avatar("#9a3412")
            second = patterned_avatar("#1d4ed8", diagonal=True)
            first.save(image_dir / "first.png")
            second.save(image_dir / "second.png")
            manifest = {
                "version": 1,
                "approved": True,
                "candidates": [
                    {
                        "candidate_id": "first",
                        "candidate_name": "人物甲",
                        "signature": "sig-a",
                        "image": "images/first.png",
                        "approved": True,
                    },
                    {
                        "candidate_id": "second",
                        "candidate_name": "人物乙",
                        "signature": "sig-b",
                        "image": "images/second.png",
                        "approved": True,
                    },
                ],
            }
            (directory / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            observations = [
                AvatarObservation(1, 200, True, "sig-a", (0, 0, 1, 1), first, 0),
                AvatarObservation(2, 100, True, "sig-b", (0, 0, 1, 1), second, 0),
            ]

            records, diagnostics = match_observations(
                observations,
                directory,
                threshold=0.80,
                margin=0.05,
            )

            self.assertEqual([record["candidate_name"] for record in records], ["人物甲", "人物乙"])
            self.assertEqual(len(diagnostics), 2)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_metadata_mismatch_is_rejected(self):
        directory = Path.cwd() / f".test-avatar-{uuid4().hex}"
        image_dir = directory / "images"
        image_dir.mkdir(parents=True)
        try:
            avatar = patterned_avatar("#9a3412")
            avatar.save(image_dir / "first.png")
            manifest = {
                "version": 1,
                "stage": "final",
                "approved": False,
                "candidates": [
                    {
                        "candidate_id": "first",
                        "candidate_name": "人物甲",
                        "signature": "expected-signature",
                        "image": "images/first.png",
                        "approved": False,
                    }
                ],
            }
            (directory / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            observations = [
                AvatarObservation(1, 200, True, "changed-signature", (0, 0, 1, 1), avatar, 0)
            ]
            with self.assertRaisesRegex(ValueError, "分类/作品信息不一致"):
                validate_reference_gallery(
                    observations,
                    directory,
                    threshold=0.80,
                    margin=0.05,
                    stage="final",
                )
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
