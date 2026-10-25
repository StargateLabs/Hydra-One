"""Every shipped script and stylesheet must carry a content digest in the page."""
import re
import unittest
from pathlib import Path
from serve.web_asset_versions import versioned_html

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'serve' / 'web'

class AssetCoverageTests(unittest.TestCase):
    def test_reference_without_a_token_gets_a_digest(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'app.js').write_text('body')
            page = root / 'index.html'
            page.write_text('<script src="web/app.js"></script>')
            out = versioned_html(page)
            self.assertIn(b'?v=', out, 'a reference without ?v= is left cacheable')
            self.assertIn(b'web/app.js?v=', out)

    def test_existing_token_is_replaced_not_duplicated(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'app.js').write_text('body')
            page = root / 'index.html'
            page.write_text('<script src="web/app.js?v=stale-token" defer></script>')
            out = versioned_html(page)
            self.assertNotIn(b'stale-token', out)
            self.assertEqual(out.count(b'?v='), 1)
            self.assertIn(b'defer', out, 'attributes after the URL must survive')

    def test_non_js_css_urls_are_untouched(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'sprite.svg').write_text('<svg/>')
            page = root / 'index.html'
            page.write_text('<img src="web/sprite.svg">')
            self.assertEqual(versioned_html(page), b'<img src="web/sprite.svg">')

    def test_every_shipped_script_and_stylesheet_has_a_digest(self):
        page = WEB / 'index.html'
        source = page.read_text(encoding='utf-8')
        served = versioned_html(page).decode('utf-8')
        references = re.findall(r'(?:src|href)="web/([^"?]+)', source)
        missing = []
        for name in sorted(set(references)):
            path = WEB / name
            if not path.is_file() or path.suffix not in ('.js', '.css'):
                continue
            if f'web/{name}?v=' not in served:
                missing.append(name)
        self.assertEqual(missing, [], 'shipped assets without a digest: ' + ', '.join(missing))

if __name__ == '__main__':
    unittest.main()
