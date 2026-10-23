import json
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw

from avatar_matching import (
    AvatarObservation,
    avatar_similarity,
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
