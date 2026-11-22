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
    def test_failed_second_part_keeps_completed_first_part_for_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);catalogue=self.catalogue(root);entry=self.entry(root)
            with patch('serve.optional_catalogue.urllib.request.urlopen',side_effect=[io.BytesIO(b'GGUFfirst'),io.BytesIO(b'bad')]):catalogue._download_shards(entry)
            self.assertEqual(catalogue.job['state'],'failed')
            self.assertEqual(Path(entry['shards'][0]['path']).read_bytes(),b'GGUFfirst')
            self.assertFalse(Path(entry['shards'][1]['path']).exists())
            self.assertFalse(Path(entry['shards'][1]['path']).with_suffix('.gguf.download').exists())

    def test_existing_complete_part_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);catalogue=self.catalogue(root);entry=self.entry(root)
            first=Path(entry['shards'][0]['path']);first.parent.mkdir(parents=True,exist_ok=True);first.write_bytes(b'GGUFfirst')
            with patch('serve.optional_catalogue.urllib.request.urlopen',return_value=io.BytesIO(b'GGUFsecond')) as urlopen:
                catalogue._download_shards(entry)
            self.assertEqual(catalogue.job['state'],'complete');self.assertEqual(urlopen.call_count,1)
            self.assertEqual(catalogue.job['bytes_done'],19);self.assertEqual(catalogue.job['parts_done'],2)

    def test_partial_second_part_resumes_with_range(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);catalogue=self.catalogue(root);entry=self.entry(root)
            first=Path(entry['shards'][0]['path']);first.parent.mkdir(parents=True,exist_ok=True);first.write_bytes(b'GGUFfirst')
            second=Path(entry['shards'][1]['path']);second.with_suffix('.gguf.download').write_bytes(b'GGUF')
            class Response(io.BytesIO):
                status=206
                headers={'Content-Range':'bytes 4-9/10'}
            with patch('serve.optional_catalogue.urllib.request.urlopen',return_value=Response(b'second')) as urlopen:
                catalogue._download_shards(entry)
            self.assertEqual(catalogue.job['state'],'complete');self.assertEqual(second.read_bytes(),b'GGUFsecond')
            self.assertEqual(urlopen.call_args.args[0].get_header('Range'),'bytes=4-')

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
