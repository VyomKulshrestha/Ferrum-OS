"""Regressions for complete primary-source URLs in report references."""
import unittest

from build_world_model_technical_report_v1_2 import inline, make_styles


class ReferenceTests(unittest.TestCase):
    def test_url_is_not_cut_at_letters_from_html_entity(self):
        url = "https://www.nasa.gov/missions/ingenuity/aircraft-investigation/"
        self.assertIn(f"href='{url}'", inline(url))

    def test_arxiv_html_version_is_preserved(self):
        url = "https://arxiv.org/html/2609.14858v1"
        self.assertIn(f"href='{url}'", inline(url))

    def test_query_entities_remain_escaped_for_markup(self):
        self.assertIn("href='https://example.org/result?a=1&amp;b=2'",
                      inline("https://example.org/result?a=1&b=2"))

    def test_reference_wraps_and_does_not_leave_single_line_continuation(self):
        style = make_styles()["reference"]
        self.assertTrue(style.splitLongWords)
        self.assertFalse(style.allowWidows)
        self.assertFalse(style.allowOrphans)


if __name__ == "__main__":
    unittest.main()
