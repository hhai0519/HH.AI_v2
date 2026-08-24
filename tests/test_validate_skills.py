import unittest
import sys
from pathlib import Path

# Add project root directory to sys.path so we can import scripts.validate_skills
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_skills import parse_frontmatter


class TestParseFrontmatter(unittest.TestCase):
    def test_valid_frontmatter(self):
        text = (
            "---\n"
            "name: test-skill\n"
            "description: A test skill description\n"
            "---\n"
            "Body content goes here.\n"
        )
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {
            "name": "test-skill",
            "description": "A test skill description"
        })
        self.assertEqual(body, "Body content goes here.\n")

    def test_quoted_values_and_spaces(self):
        text = (
            "---\n"
            'name: "quoted-name"  \n'
            "description: 'quoted description'\n"
            "---\n"
            "Body\n"
        )
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {
            "name": "quoted-name",
            "description": "quoted description"
        })
        self.assertEqual(body, "Body\n")

    def test_comments_and_blank_lines(self):
        text = (
            "---\n"
            "# This is a comment\n"
            "name: test-skill\n"
            "\n"
            "  # Indented comment\n"
            "description: Description\n"
            "---\n"
            "Body\n"
        )
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {
            "name": "test-skill",
            "description": "Description"
        })

    def test_colon_in_value(self):
        text = (
            "---\n"
            "name: test-skill\n"
            "description: See https://example.com for details\n"
            "---\n"
            "Body\n"
        )
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {
            "name": "test-skill",
            "description": "See https://example.com for details"
        })

    def test_no_frontmatter(self):
        text = "Just normal body text without frontmatter."
        fm, body = parse_frontmatter(text)
        self.assertIsNone(fm)
        self.assertEqual(body, text)

    def test_unclosed_frontmatter(self):
        text = "---\nname: test-skill\ndescription: missing end delimiter"
        fm, body = parse_frontmatter(text)
        self.assertIsNone(fm)
        self.assertEqual(body, text)

    def test_indented_lines_and_no_colon_lines(self):
        text = (
            "---\n"
            "name: test-skill\n"
            "  indented_key: value\n"
            "invalid_line_without_colon\n"
            "description: Description\n"
            "---\n"
            "Body\n"
        )
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {
            "name": "test-skill",
            "description": "Description"
        })

    def test_body_containing_dashes(self):
        text = (
            "---\n"
            "name: test-skill\n"
            "description: Skill description\n"
            "---\n"
            "Line 1\n"
            "---\n"
            "Line 2\n"
        )
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {
            "name": "test-skill",
            "description": "Skill description"
        })
        self.assertEqual(body, "Line 1\n---\nLine 2\n")


if __name__ == "__main__":
    unittest.main()
