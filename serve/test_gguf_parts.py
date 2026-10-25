import hashlib,io,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from serve.gguf_parts import identity,local_parts,remote_parts,weight_bytes
from serve.optional_catalogue import OptionalCatalogue

class PartsTests(unittest.TestCase):
    def test_complete_set_first_part_and_total_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            first=Path(folder)/'model-00001-of-00002.gguf';second=first.with_name('model-00002-of-00002.gguf')
            first.write_bytes(b'GGUFfirst')
            with self.assertRaisesRegex(ValueError,'Missing'):local_parts(first)
            second.write_bytes(b'GGUFsecond');self.assertEqual(weight_bytes(first),19)
            with self.assertRaisesRegex(ValueError,'first'):local_parts(second)
            with self.assertRaises(ValueError):identity('model-00001-of-00000.gguf')
    def test_remote_groups_require_every_part(self):
        files=[{'path':'quant/model-00001-of-00002.gguf'},{'path':'quant/model-00002-of-00002.gguf'}]
        self.assertEqual(remote_parts(files[0],files),files);self.assertFalse(remote_parts(files[0],files[:1]));self.assertFalse(remote_parts(files[1],files))
    def catalogue(self,root):
        return OptionalCatalogue(SimpleNamespace(root=root,binary=root/'server.exe',models_root=root/'models'))
    def entry(self,root):
        parts=[]
        for number,content in [(1,b'GGUFfirst'),(2,b'GGUFsecond')]:
            parts.append({'path':str(root/'models'/f'model-{number:05d}-of-00002.gguf'),'url':f'https://huggingface.co/part{number}','bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()})
        return {'path':parts[0]['path'],'shards':parts,'bytes':19}
    def test_download_progress_is_total_and_all_parts_are_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);catalogue=self.catalogue(root);entry=self.entry(root)
            with patch('serve.optional_catalogue.urllib.request.urlopen',side_effect=[io.BytesIO(b'GGUFfirst'),io.BytesIO(b'GGUFsecond')]):catalogue._download_shards(entry)
            self.assertEqual(catalogue.job['state'],'complete');self.assertEqual(catalogue.job['bytes_done'],19);self.assertEqual(catalogue.job['parts_done'],2)
    def test_failed_second_part_cleans_only_created_parts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);catalogue=self.catalogue(root);entry=self.entry(root)
            with patch('serve.optional_catalogue.urllib.request.urlopen',side_effect=[io.BytesIO(b'GGUFfirst'),io.BytesIO(b'bad')]):catalogue._download_shards(entry)
            self.assertEqual(catalogue.job['state'],'failed');self.assertFalse(list((root/'models').glob('*.gguf*')))
            Path(entry['shards'][0]['path']).write_bytes(b'existing')
            catalogue._download_shards(entry)
            self.assertEqual(Path(entry['shards'][0]['path']).read_bytes(),b'existing')

    def test_local_removal_deletes_the_selected_group_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);catalogue=self.catalogue(root);entry=self.entry(root)
            for part in entry['shards']:
                path=Path(part['path']);path.parent.mkdir(exist_ok=True);path.write_bytes(b'GGUFtest')
            unrelated=root/'models/other.gguf';unrelated.write_bytes(b'GGUFkeep')
            catalogue.manager.lock=threading.RLock();catalogue.manager.models_roots=[root/'models']
            catalogue.manager.status=lambda:{'status':'idle','local_models':[{'path':entry['path'],'name':'model','bytes':16}]}
            result=catalogue.delete_local(entry['path'])
            self.assertTrue(result['removed']);self.assertTrue(unrelated.exists())
            self.assertFalse(any(Path(part['path']).exists() for part in entry['shards']))

if __name__=='__main__':unittest.main()
