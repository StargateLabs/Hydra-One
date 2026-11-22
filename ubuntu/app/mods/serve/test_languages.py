import json
from pathlib import Path
import unittest
from tools.build_language_assets import validate
ROOT=Path(__file__).resolve().parents[1]

class LanguageCatalogueTests(unittest.TestCase):
    def test_new_engine_and_catalogue_copy_is_registered(self):
        from tools.sync_optional_language import pairs
        data=json.loads((ROOT/'serve/locales/ui-it-en.json').read_text(encoding='utf-8'))
        for name in ('optional-backends.js','optional-catalogue.js','local-training.js','local-audio.js','local-speech.js','local-separation.js','ai-lab.js','lab-evidence.js','performance-spectrum.js','performance-workspace.js','chat-context.js','local-export.js','local-vision.js','local-generation.js','training-runtime.js','multimedia-studio.js','media-studio-design.js'):
            for source,_ in pairs((ROOT/'serve/web'/name).read_text(encoding='utf-8')):
                self.assertIn(source,data['pairs'],name+': '+source)
    def test_all_shipped_bilingual_copy_is_registered(self):
        import re
        from tools.sync_optional_language import pairs
        data=json.loads((ROOT/'serve/locales/ui-it-en.json').read_text(encoding='utf-8'))
        html=(ROOT/'serve/web/index.html').read_text(encoding='utf-8')
        for relative in re.findall(r'<script[^>]+src="(web/[^"?]+)',html):
            path=ROOT/'serve'/relative
            if path.name in ('language-data.js','language.js') or not path.is_file():continue
            for source,target in pairs(path.read_text(encoding='utf-8')):
                if source.strip() and target.strip():self.assertTrue(source in data['pairs'],path.name+': '+source)

    def test_control_id_lists_are_not_translated(self):
        from tools.sync_optional_language import pairs
        self.assertEqual(list(pairs("configGroup('generation','speculative',['backend-draft-path','backend-draft-max','backend-draft-min']);")),[])
        self.assertIn(('Token draft massimi','Maximum draft tokens'),list(pairs("[['backend-draft-max','Token draft massimi','Maximum draft tokens',1]]")))

    def test_interface_has_no_corrupt_utf8_sequences(self):
        markers=('\u00c2\u00b7','\u00c3\u00a0','\u00c3\u00a8','\u00e2\u20ac\u2122','\u00e2\u20ac\xa6')
        for folder in ('serve/web','serve/locales'):
            for path in (ROOT/folder).rglob('*'):
                if path.suffix in ('.js','.json','.html','.css'):
                    source=path.read_text(encoding='utf-8-sig')
                    for marker in markers:self.assertNotIn(marker,source,str(path))

    def test_browser_can_parse_both_language_scripts_in_order(self):
        from html.parser import HTMLParser
        class Scripts(HTMLParser):
            def __init__(self):super().__init__();self.sources=[]
            def handle_starttag(self,tag,attrs):
                if tag=='script':self.sources.append(dict(attrs).get('src','').split('?')[0])
        parser=Scripts();parser.feed((ROOT/'serve/web/index.html').read_text(encoding='utf-8'))
        self.assertIn('web/language-data.js',parser.sources)
        self.assertIn('web/language.js',parser.sources)
        self.assertLess(parser.sources.index('web/language-data.js'),parser.sources.index('web/language.js'))

    def test_all_entries_and_placeholders_are_valid(self):
        data=json.loads((ROOT/'serve/locales/ui-it-en.json').read_text(encoding='utf-8'));validate(data)
        self.assertGreater(len(data['pairs']),900)
        self.assertEqual(data['pairs']['Modello non disponibile'],'Model unavailable')
    def test_missing_placeholder_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Placeholder'):validate({'pairs':{'{0} token':'tokens'},'aliases':{}})
    def test_dangling_alias_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Alias'):validate({'pairs':{'Ciao':'Hello'},'aliases':{'legacy':'missing'}})
    def test_generated_asset_matches_reviewed_source(self):
        data=json.loads((ROOT/'serve/locales/ui-it-en.json').read_text(encoding='utf-8'))
        asset=(ROOT/'serve/web/language-data.js').read_text(encoding='utf-8')
        self.assertEqual(json.loads(asset.split('window.StrataLanguageData=',1)[1].removesuffix(';\n')),data)
    def test_navigation_has_both_languages_and_preserves_form_identifiers(self):
        source=(ROOT/'serve/web/index.html').read_text(encoding='utf-8')
        self.assertEqual(source.count('data-language="it"'),1);self.assertEqual(source.count('data-language="en"'),1)
        for key in ('lab-model','lab-prompt','monitor-source','ctrl-model','input'):
            self.assertEqual(source.count(f'id="{key}"'),1)

if __name__=='__main__':unittest.main()
