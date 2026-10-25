import tempfile,unittest
from pathlib import Path
from serve.web_asset_versions import versioned_html
class AssetVersions(unittest.TestCase):
 def test_asset_change_updates_version_without_altering_source(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);page=root/'index.html';css=root/'control.css';css.write_text('first');original='<link href="web/control.css?v=old"><script src="web/fixed.js"></script>';page.write_text(original)
   before=versioned_html(page);self.assertNotIn(b'?v=old',before);self.assertIn(b'web/fixed.js',before)
   css.write_text('second version');after=versioned_html(page);self.assertNotEqual(before,after);self.assertEqual(page.read_text(),original)
 def test_missing_assets_keep_original_url(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'index.html';path.write_text('<script src="web/missing.js?v=old"></script>')
   self.assertIn(b'?v=old',versioned_html(path))
