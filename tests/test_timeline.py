"""Regression checks use synthetic words and require no user media.

Run from the project root: python -m unittest discover -s tests
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import tempfile
import unittest

from editor import cuts, hyperframes_fx, motion, subtitles


class CutTimelineTests(unittest.TestCase):
    def test_remapping_preserves_emphasis_and_word_metadata(self):
        words = [
            {"word": "antes", "start": 0.2, "end": 0.4},
            {"word": "importante", "start": 3.2, "end": 3.6,
             "emph": True, "speaker": "A"},
        ]
        result = cuts.remap_words(words, [(0.0, 1.0), (3.0, 4.0)])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["start"], 1.2)
        self.assertEqual(result[1]["end"], 1.6)
        self.assertTrue(result[1]["emph"])
        self.assertEqual(result[1]["speaker"], "A")
        self.assertEqual(words[1]["start"], 3.2)

    def test_word_overlapping_first_kept_boundary_is_clipped(self):
        words = [{"word": "sim", "start": 0.9, "end": 1.2, "emph": True}]
        result = cuts.remap_words(words, [(1.0, 2.0)])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["word"], "sim")
        self.assertEqual(result[0]["start"], 0.0)
        self.assertAlmostEqual(result[0]["end"], 0.2, places=3)
        self.assertTrue(result[0]["emph"])

    def test_removed_words_are_omitted_and_edited_time_stays_in_bounds(self):
        words = [
            {"word": "cortada", "start": 1.2, "end": 1.4},
            {"word": "mantida", "start": 2.8, "end": 3.3},
        ]
        result = cuts.remap_words(words, [(0.0, 1.0), (2.0, 3.0)])
        self.assertEqual([word["word"] for word in result], ["mantida"])
        self.assertAlmostEqual(result[0]["start"], 1.8, places=3)
        self.assertAlmostEqual(result[0]["end"], 2.0, places=3)

    def test_frame_alignment_encloses_speech_instead_of_trimming_it(self):
        words = [{"word": "fala", "start": 0.21, "end": 0.39}]
        keep = cuts.compute_keep(words, 2.0, pad=0.0, fps=30)
        self.assertEqual(len(keep), 1)
        self.assertAlmostEqual(keep[0][0], 0.2, places=3)
        self.assertAlmostEqual(keep[0][1], 0.4, places=3)
        self.assertLessEqual(keep[0][0], words[0]["start"])
        self.assertGreaterEqual(keep[0][1], words[0]["end"])

    def test_short_answer_survives_without_restoring_the_whole_video(self):
        words = [{"word": "sim", "start": 0.52, "end": 0.58}]
        keep = cuts.compute_keep(words, 10.0, pad=0.0, fps=30)
        self.assertEqual(len(keep), 1)
        self.assertLessEqual(keep[0][0], 0.52)
        self.assertGreaterEqual(keep[0][1], 0.58)
        self.assertLess(keep[0][1] - keep[0][0], 0.5)


class MotionPlanningTests(unittest.TestCase):
    @staticmethod
    def words():
        return [{"word": str(i), "start": i * 0.5, "end": i * 0.5 + 0.25}
                for i in range(60)]

    def test_motion_is_deterministic_ordered_and_inside_the_edited_duration(self):
        events = motion.plan_events(self.words(), 30.0)
        self.assertEqual(events, motion.plan_events(self.words(), 30.0))
        self.assertTrue(events)
        self.assertEqual(events, sorted(events, key=lambda event: event["start"]))
        for event in events:
            self.assertGreaterEqual(event["start"], 0.0)
            self.assertGreater(event["duration"], 0.0)
            self.assertLessEqual(event["start"] + event["duration"], 30.0001)
            self.assertIn(event["type"], {"number", "keyword"})
        for previous, following in zip(events, events[1:]):
            self.assertLessEqual(previous["start"] + previous["duration"], following["start"])

    def test_motion_respects_disabled_mode_and_occupied_image_intervals(self):
        self.assertEqual(motion.plan_events(self.words(), 30, "off"), [])
        self.assertEqual(motion.plan_events(self.words(), 30, occupied=[(0, 30)]), [])
        occupied = [(5.0, 12.0), (20.0, 25.0)]
        events = motion.plan_events(self.words(), 30, occupied=occupied)
        for event in events:
            start, end = event["start"], event["start"] + event["duration"]
            self.assertFalse(any(start < b and end > a for a, b in occupied))

    def test_numeric_callout_keeps_the_number_and_spoken_unit(self):
        words = [
            {"word": "20", "start": 1.0, "end": 1.3},
            {"word": "reais", "start": 1.31, "end": 1.8},
        ]
        events = motion.plan_events(words, 5)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["text"], "20 reais")
        self.assertEqual(events[0]["type"], "number")

    def test_intensity_increases_density(self):
        counts = [len(motion.plan_events(self.words(), 30, intensity))
                  for intensity in ("subtle", "balanced", "bold")]
        self.assertEqual(counts, sorted(counts))
        self.assertGreater(counts[-1], counts[0])


class CompositionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = None
        self.groups = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "data-composition-id" in values:
            self.root = values
        if "grp" in values.get("class", "").split():
            self.groups.append(values)


class CaptionCompositionTests(unittest.TestCase):
    def test_grouping_breaks_on_pauses_and_never_exceeds_three_words(self):
        words = [{"word": "palavra", "start": i * 0.2, "end": i * 0.2 + 0.1}
                 for i in range(7)]
        groups = subtitles._group(words, 8, 200)
        self.assertTrue(all(len(group) <= 3 for group in groups))
        words = [{"word": "antes", "start": 0.0, "end": 0.2},
                 {"word": "depois", "start": 3.0, "end": 3.2}]
        self.assertEqual(len(subtitles._group(words, 3, 100)), 2)

    def test_caption_clips_stop_at_duration_and_do_not_bridge_long_silences(self):
        words = [{"word": "teste", "start": 0.2, "end": 0.5},
                 {"word": "final", "start": 4.8, "end": 5.3}]
        html = hyperframes_fx.build_captions_html(words, (1080, 1920), 5.0)
        parser = CompositionParser()
        parser.feed(html)
        self.assertEqual(parser.root["data-composition-id"], "main")
        self.assertEqual(float(parser.root["data-duration"]), 5.0)
        self.assertEqual(len(parser.groups), 2)
        for group in parser.groups:
            self.assertLessEqual(float(group["data-start"]) + float(group["data-duration"]), 5.0001)
        self.assertLess(float(parser.groups[0]["data-duration"]), 1.0)

    def test_full_duration_stays_seekable_after_the_last_caption(self):
        words = [{"word": "teste", "start": 0.1, "end": 0.5}]
        html = hyperframes_fx.build_captions_html(words, (1080, 1920), 5.0)
        self.assertRegex(html, r"timeline\(\s*\{\s*paused\s*:\s*true\s*\}")
        self.assertRegex(html, r"tl\.set\(\s*\{\}\s*,\s*\{\}\s*,\s*5(?:\.0+)?\s*\)")
        self.assertRegex(html, r"window\.__timelines(?:\[\"main\"\]|\.main)\s*=\s*tl")

    def test_caption_text_is_html_escaped_and_local_font_is_attached(self):
        words = [{"word": "<b>&teste", "start": 0.1, "end": 1.0}]
        html = hyperframes_fx.build_captions_html(words, (1080, 1920), 5.0,
                                               font_file="userfont.ttf", animation="none")
        self.assertIn("&lt;B&gt;&amp;TESTE", html)
        self.assertNotIn("<b>&teste", html.lower())
        self.assertIn("@font-face", html)
        self.assertIn("userfont.ttf", html)
        self.assertNotIn("tl.fromTo", html)

    def test_card_layer_also_preserves_the_requested_full_duration(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "card.png"
            Image.new("RGBA", (120, 80), (255, 0, 0, 255)).save(image)
            html = hyperframes_fx.build_html(
                [{"path": str(image), "start": 0.2, "duration": 1.0, "animation": "pop"}],
                (1080, 1920), 5.0)
        self.assertRegex(html, r"tl\.set\(\s*\{\}\s*,\s*\{\}\s*,\s*5(?:\.0+)?\s*\)")


if __name__ == "__main__":
    unittest.main()
