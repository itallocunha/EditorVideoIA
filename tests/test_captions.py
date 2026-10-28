"""Regression checks for font selection, timing and the ASS fallback contract."""
from pathlib import Path
from tempfile import TemporaryDirectory
import re
import unittest
from unittest.mock import patch

from editor import fonts, subtitles


def font_record(ident, family, source="windows", variant="Regular"):
    return {"id": ident, "name": family, "family": family,
            "path": f"C:/Windows/Fonts/{ident}.ttf", "warning": None,
            "source": source, "variant": variant}


class FontSelectionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [font_record("custom-first", "Unrelated Custom", "local"),
                        font_record("impact", "Impact"),
                        font_record("georgia", "Georgia")]

    def test_explicit_font_id_and_family_override_style_default(self):
        with patch.object(fonts, "catalog_fonts", return_value=self.catalog):
            by_id = fonts.resolve_font("georgia", style="hormozi")
            by_family = fonts.resolve_font("Georgia", style="hormozi")
        self.assertEqual(by_id["path"], "C:/Windows/Fonts/georgia.ttf")
        self.assertEqual(by_family["id"], "georgia")

    def test_custom_file_never_implicitly_overrides_preset(self):
        with patch.object(fonts, "catalog_fonts", return_value=self.catalog):
            result = fonts.resolve_font(style="hormozi")
        self.assertEqual(result["family"], "Impact")
        self.assertIsNone(result["warning"])

    def test_unknown_or_injected_request_falls_back_with_warning(self):
        with patch.object(fonts, "catalog_fonts", return_value=self.catalog):
            result = fonts.resolve_font("Georgia';}body{color:red}/*")
        self.assertEqual(result["family"], "Impact")
        self.assertTrue(result["warning"])
        sanitized = fonts.sanitize_family("Evil,Font';{}\\n\\fnInjected\n")
        self.assertNotRegex(sanitized, r"[,;'{}\\\r\n]")

    def test_unavailable_default_does_not_choose_arbitrary_custom_font(self):
        with patch.object(fonts, "catalog_fonts", return_value=self.catalog[:1]):
            result = fonts.resolve_font(style="suave")
        self.assertEqual(result["family"], "Segoe UI")
        self.assertIsNone(result["path"])
        self.assertTrue(result["warning"])


class CaptionGroupingTests(unittest.TestCase):
    def test_maximum_three_words_and_long_pause_are_respected(self):
        words = [{"word": str(i), "start": i * .2, "end": i * .2 + .15}
                 for i in range(5)]
        words[4].update(start=1.5, end=1.7, emph=True)
        groups = subtitles._group(words, 99, 100)
        self.assertEqual([len(g) for g in groups], [3, 1, 1])
        self.assertIs(groups[-1][0], words[-1])
        self.assertTrue(groups[-1][0]["emph"])

    def test_exact_pause_boundary_and_measured_width(self):
        words = [{"word": "one", "start": 0, "end": .25},
                 {"word": "two", "start": .70, "end": .9}]
        self.assertEqual(len(subtitles._group(words, 3, 100)), 1)
        groups = subtitles._group(words, 3, 100, measure=lambda s: len(s) * 10,
                                  max_width=60)
        self.assertEqual([len(g) for g in groups], [1, 1])


class AssRenderingTests(unittest.TestCase):
    def build(self, words, **kwargs):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "captions.ass"
            with patch.object(subtitles, "resolve_font", return_value=font_record("impact", "Impact")), \
                 patch.object(subtitles, "_measure_font", return_value=lambda text: len(text) * 40):
                family = subtitles.build_ass(words, 1080, 1920, dest, **kwargs)
            return family, dest.read_text(encoding="utf-8")

    def test_only_active_word_animates_and_emphasis_increases_peak(self):
        words = [{"word": "primeira", "start": 0, "end": .25},
                 {"word": "forte", "start": .3, "end": .6, "emph": True}]
        family, source = self.build(words)
        events = [line for line in source.splitlines() if line.startswith("Dialogue:")]
        self.assertEqual(family, "Impact")
        self.assertEqual(len(events), 4)
        self.assertTrue(all("\\t(" not in line for line in events if line.startswith("Dialogue: 0,")))
        self.assertIn("\\fscx110", events[0])
        self.assertIn("\\fscx120", events[-1])
        self.assertIn("\\b1", events[-1])
        self.assertIn("\\pos(", source)

    def test_none_removes_transitions_but_retains_active_color_and_emphasis(self):
        _, source = self.build([{"word": "ênfase", "start": 0, "end": .3, "emph": True}],
                               animation="none")
        self.assertNotIn("\\t(", source)
        self.assertIn(subtitles.inline_color("#FFE600"), source)
        self.assertIn("\\b1", source)

    def test_transcript_cannot_inject_ass_tags_or_dialogue_events(self):
        words = [{"word": "ok{\\pos(0,0)}\nDialogue: 0,evil", "start": 0, "end": .4}]
        _, source = self.build(words, animation="none")
        events = [line for line in source.splitlines() if line.startswith("Dialogue:")]
        self.assertEqual(len(events), 1)
        self.assertNotIn("\\pos(0,0)", source)
        self.assertNotIn("{\\pos(0,0)}", source)
        self.assertTrue(events[0].endswith("OKPOS(0,0) DIALOGUE: 0,EVIL"))

    def test_box_style_uses_actual_ass_box_and_font_scale_changes_size(self):
        words = [{"word": "caixa", "start": 0, "end": .4}]
        _, regular = self.build(words, style="caixa", animation="none")
        _, larger = self.build(words, style="caixa", animation="none", font_scale=1.2)
        style = next(line for line in regular.splitlines() if line.startswith("Style: ActiveBox,"))
        self.assertEqual(style.split(",")[15], "3")
        self.assertRegex(regular, r"Dialogue: 1,[^\n]+,ActiveBox,")
        normal_size = float(re.search(r"Style: Default,Impact,([0-9.]+)", regular).group(1))
        large_size = float(re.search(r"Style: Default,Impact,([0-9.]+)", larger).group(1))
        self.assertGreater(large_size, normal_size)


class WindowsFontNamingTests(unittest.TestCase):
    def test_arial_black_windows_face_is_catalogued_as_selectable_family(self):
        from unittest.mock import patch
        from editor.fonts import _read_catalog
        with patch("PIL.ImageFont.truetype") as load:
            load.return_value.getname.return_value = ("Arial", "Black")
            record = _read_catalog.__wrapped__((("windows", "C:/Windows/Fonts/ariblk.ttf", 0, 1),))[0]
        self.assertEqual(record["family"], "Arial Black")
        self.assertEqual(record["name"], "Arial Black")


if __name__ == "__main__":
    unittest.main()
