import unittest
from build_skill_catalog import compile_skills
class SkillCatalogTests(unittest.TestCase):
 def test_original_text_identity_and_provenance(self):
  rows=[{"id":"x","path":"skills/x","name":"Example","category":"coding","description":"Original description"}]
  item=compile_skills(rows,{"skills/x":"<script>not executable</script>"},"abc")[0]
  self.assertEqual(item["description"],"Original description")
  self.assertEqual(item["source"],"skills");self.assertIn("/blob/abc/skills/x/SKILL.md",item["url"])
 def test_missing_document_fails_import(self):
  with self.assertRaises(ValueError):compile_skills([{"id":"x","path":"skills/x"}],{},"abc")
if __name__=="__main__":unittest.main()
