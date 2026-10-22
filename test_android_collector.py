import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import call, patch

from android_collector import parse_ui_xml, refresh_activity
from score_parser import parse_score


class ScoreParserTests(unittest.TestCase):
    def test_w_unit(self):
        self.assertEqual(parse_score("2085.1w"), (20_851_000, True))

    def test_exact_value(self):
        self.assertEqual(parse_score("推荐值 12,345"), (12_345, False))


class AndroidUiParserTests(unittest.TestCase):
    def test_candidate_cards(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node text="剧综人物" class="android.widget.TextView" />
  <node text="突围赛｜10月16日12点-10月22日18点" class="android.widget.TextView" />
  <node text="" class="android.view.View">
    <node text="" class="android.view.View">
      <node text="十个勤天" class="android.widget.TextView" />
      <node text="团体" class="android.widget.TextView" />
      <node text="" class="android.view.View">
        <node text="推荐值" class="android.widget.TextView" />
        <node text="2085.1w" class="android.widget.TextView" />
      </node>
    </node>
    <node text="" class="android.view.View">
      <node text="苏新皓" class="android.widget.TextView" />
      <node text="05生" class="android.widget.TextView" />
      <node text="" class="android.view.View">
        <node text="推荐值" class="android.widget.TextView" />
        <node text="2068.1w" class="android.widget.TextView" />
      </node>
    </node>
  </node>
</hierarchy>"""
        stage, records = parse_ui_xml(
            ET.fromstring(xml), min_candidates=2, expected_candidates=2
        )
        self.assertEqual(stage, "breakthrough")
        self.assertEqual([record["candidate_name"] for record in records], ["十个勤天", "苏新皓"])
        self.assertEqual(records[0]["score"], 20_851_000)
        self.assertIsNone(records[0]["rank"])


class RefreshTests(unittest.TestCase):
    @patch("android_collector.time.sleep")
    @patch("android_collector.run_adb")
    def test_refresh_reopens_activity_in_weibo(self, run_adb, sleep):
        run_adb.side_effect = ["package:/data/app/com.sina.weibo/base.apk", "Status: ok"]

        refresh_activity(Path("adb.exe"), "127.0.0.1:12345", "https://example.test", 3)

        self.assertEqual(run_adb.call_count, 2)
        self.assertEqual(
            run_adb.call_args_list[1],
            call(
                Path("adb.exe"),
                "shell",
                "am",
                "start",
                "-W",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                "https://example.test",
                "-p",
                "com.sina.weibo",
                serial="127.0.0.1:12345",
            ),
        )
        sleep.assert_called_once_with(3)

    @patch("android_collector.time.sleep")
    @patch("android_collector.run_adb")
    def test_refresh_escapes_query_separator(self, run_adb, _sleep):
        run_adb.side_effect = ["package:/data/app/com.sina.weibo/base.apk", "Status: ok"]

        refresh_activity(
            Path("adb.exe"),
            "device",
            "https://example.test/activity?id=one&cid=two",
            0,
        )

        self.assertIn(r"https://example.test/activity?id=one\&cid=two", run_adb.call_args.args)


if __name__ == "__main__":
    unittest.main()
