import unittest
import xml.etree.ElementTree as ET

from android_collector import parse_ui_xml
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


if __name__ == "__main__":
    unittest.main()
