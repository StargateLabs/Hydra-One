import unittest
from import_prompt_catalog import compile_catalog
class CatalogTests(unittest.TestCase):
    def test_preserves_multiline_and_markup_as_data(self):
        raw = b'act,prompt,for_devs,type,contributor\nExample,"<script>alert(1)</script>\nsecond line",TRUE,TEXT,author\n'
        item = compile_catalog(raw)["items"][0]
        self.assertEqual(item["text"], "<script>alert(1)</script>\nsecond line")
        self.assertTrue(item["developer"])
    def test_empty_prompt_rejected(self):
        with self.assertRaises(ValueError): compile_catalog(b'act,prompt\nExample,\n')
if __name__ == "__main__": unittest.main()
