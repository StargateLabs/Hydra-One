import base64,json,tempfile,unittest,zipfile,io
from pathlib import Path
from unittest.mock import patch
from serve import open_webui_runtime as runtime

class CandidateWorkerScope(unittest.TestCase):
    def test_candidate_worker_does_not_shadow_the_installed_mcp_package(self):
        source=(Path(__file__).resolve().parent/'open_webui_candidate_worker.py').read_text(encoding='utf-8')
        self.assertNotIn("sys.path.insert(0,str(Path(__file__).resolve().parent))",source)
        self.assertIn('from serve.open_webui_runtime import',source)

class OpenWebUIIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_prepare_completes_after_pip_returns_completed_process(self):
        from subprocess import CompletedProcess
        python=runtime.directory(self.root)/'venv/Scripts/python.exe'
        python.parent.mkdir(parents=True);python.touch()
        metadata={'info':{'name':'open-webui','version':'0.12.0','requires_python':'>=3.11'},
                  'urls':[{'filename':'open_webui-0.12.0-py3-none-any.whl',
                           'url':'https://files.pythonhosted.org/open_webui.whl',
                           'digests':{'sha256':'a'*64}}]}
        proof={name:{'chunks':[{'text':'local source'}]} for name in ('txt','docx','pdf','csv','json')}
        proof.update(search={'matches':[{'page':1}]},context={'estimated_tokens':1},device={'device':'cpu'})
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(metadata).encode())), \
             patch.object(runtime.shutil,'which',return_value=None), \
             patch.object(runtime.shutil,'disk_usage',return_value=type('Disk',(),{'free':10*1024**3})()), \
             patch.object(runtime.subprocess,'run',side_effect=[CompletedProcess([],1),CompletedProcess([],0),CompletedProcess([],0),CompletedProcess([],0),CompletedProcess([],0)]), \
             patch('serve.open_webui_python_update.selection',return_value=None), \
             patch.object(runtime,'worker',return_value=proof), \
             patch.object(runtime,'source_hash',return_value='source'), \
             patch.object(runtime,'runtime_hash',return_value='runtime'), \
             patch.object(runtime,'status',return_value={'ready':True}):
            self.assertTrue(runtime.prepare(self.root)['ready'])
        self.assertFalse((self.root/'data/open-webui/setup.lock').exists())

    def test_upload_rejects_paths_binary_and_oversize_before_worker(self):
        with patch.object(runtime,'require_ready'),patch.object(runtime,'worker') as worker:
            for payload in ({'name':'../data.txt','data':'eA=='},{'name':'app.exe','data':'eA=='},
                            {'name':'data.pdf','data':'?'},{'name':'data.pdf','data':''},
                            {'name':'data.pdf','data':'A'*(runtime.MAX_UPLOAD*4//3+9)}):
                with self.assertRaises(ValueError):runtime.upload(self.root,payload)
            worker.assert_not_called()

    def test_docx_inflation_is_rejected_before_native_loader(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('word/document.xml','x'*(33*1024*1024))
        with patch.object(runtime,'require_ready'),patch.object(runtime,'worker') as worker:
            with self.assertRaises(ValueError):runtime.upload(self.root,{'name':'large.docx','data':base64.b64encode(raw.getvalue()).decode()})
            worker.assert_not_called()

    def test_upload_search_remove_use_owned_ids_and_preserve_sources(self):
        extracted={'processor':'Open WebUI','version':'0.12.0','pages':1,'chunks':[{'text':'exact source < & >','page':1}]}
        with patch.object(runtime,'require_ready'),patch.object(runtime,'worker',return_value=extracted):
            row=runtime.upload(self.root,{'name':'notes.txt','data':base64.b64encode(b'exact source < & >').decode()})
        self.assertEqual(row['preview'],'exact source < & >')
        with patch.object(runtime,'require_ready'),patch.object(runtime,'worker',return_value={'matches':extracted['chunks']}) as worker:
            found=runtime.search(self.root,{'id':row['id'],'query':'source'})
            self.assertEqual(found['name'],'notes.txt');self.assertEqual(worker.call_args[0][1]['chunks'],extracted['chunks'])
        self.assertTrue(runtime.remove(self.root,{'id':row['id']})['removed'])
        with self.assertRaises(ValueError):runtime.document(self.root,row['id'])
        with self.assertRaises(ValueError):runtime.document(self.root,'../anything')
        self.assertFalse(list((self.root/'data/open-webui/documents').glob('upload-*')))

    def test_library_lists_saved_documents_without_upload_payload(self):
        folder=self.root/'data/open-webui/documents';folder.mkdir(parents=True)
        (folder/('a'*32+'.json')).write_text(json.dumps({'id':'a'*32,'name':'note.txt','created_at':1,'chunks':[]}),encoding='utf-8')
        self.assertEqual(runtime.library(self.root)['items'][0]['name'],'note.txt')

    def test_library_reports_document_facts_the_interface_shows(self):
        folder=self.root/'data/open-webui/documents';folder.mkdir(parents=True)
        identity='a'*32
        (folder/(identity+'.json')).write_text(json.dumps({'id':identity,'name':'note.pdf','created_at':1,'sha256':'abc123','collection':'Progetto',
            'pages':7,'chunks':[{'text':'primo','page':1},{'text':'secondo','page':2}]}),encoding='utf-8')
        row=runtime.library(self.root)['items'][0]
        self.assertEqual(row['chunks'],2)
        self.assertEqual(row['characters'],12)
        self.assertEqual(row['format'],'pdf')
        self.assertEqual(row['sha256'],'abc123')
        self.assertEqual(row['pages'],7)

    def test_hybrid_fuses_native_rankings_and_preserves_source_positions(self):
        lists=[{'matches':[{'chunk':1,'page':2,'text':'shared'},{'chunk':0,'page':1,'text':'lexical'}]},
               {'matches':[{'chunk':2,'page':3,'text':'semantic'},{'chunk':1,'page':2,'text':'shared'}]}]
        result=runtime.fuse_rankings(*lists)
        self.assertEqual(result[0]['chunk'],1)
        self.assertEqual(result[0]['page'],2)
        self.assertEqual(len(result),3)
        self.assertGreater(result[0]['rrf_score'],result[1]['rrf_score'])

    def test_hybrid_uses_both_workers_and_requires_local_model(self):
        identity='b'*32;folder=self.root/'data/open-webui/documents';folder.mkdir(parents=True)
        (folder/(identity+'.json')).write_text(json.dumps({'id':identity,'name':'notes.txt','chunks':[{'text':'source','page':1}]}),encoding='utf-8')
        with patch.object(runtime,'require_ready'),patch.object(runtime,'embedding_models',return_value=[{'path':'local-model','bytes':1}]),patch.object(runtime,'worker',side_effect=[{'matches':[{'chunk':0,'text':'source','page':1}]},{'matches':[{'chunk':0,'text':'source','page':1}]}]) as worker:
            result=runtime.search(self.root,{'id':identity,'query':'source','method':'hybrid','embedding_model':'local-model'})
            self.assertEqual(worker.call_count,2)
            self.assertEqual(worker.call_args_list[0].args[1]['action'],'semantic')
            self.assertEqual(worker.call_args_list[1].args[1]['action'],'search')
            self.assertEqual(result['matches'][0]['page'],1)
        with patch.object(runtime,'require_ready'),patch.object(runtime,'embedding_models',return_value=[]),patch.object(runtime,'worker') as worker:
            with self.assertRaises(ValueError):runtime.search(self.root,{'id':identity,'query':'source','method':'hybrid'})
            worker.assert_not_called()

    def test_collection_metadata_persists_and_rejects_invalid_names(self):
        identity='c'*32;folder=self.root/'data/open-webui/documents';folder.mkdir(parents=True)
        (folder/(identity+'.json')).write_text(json.dumps({'id':identity,'name':'manual.txt','chunks':[{'text':'full source','page':1}]}))
        runtime.metadata(self.root,{'id':identity,'collection':'Progetto'})
        self.assertEqual(runtime.library(self.root)['items'][0]['collection'],'Progetto')
        with self.assertRaises(ValueError):runtime.metadata(self.root,{'id':identity,'collection':'x'*81})
        self.assertEqual(runtime.read(self.root,{'id':identity})['matches'][0]['text'],'full source')

    def test_full_document_never_silently_truncates(self):
        identity='d'*32;folder=self.root/'data/open-webui/documents';folder.mkdir(parents=True)
        (folder/(identity+'.json')).write_text(json.dumps({'id':identity,'name':'large.txt','chunks':[{'text':'x'*24001,'page':1}]}))
        with self.assertRaises(ValueError):runtime.read(self.root,{'id':identity})

    def test_library_search_preserves_document_identity_and_collection_scope(self):
        folder=self.root/'data/open-webui/documents';folder.mkdir(parents=True)
        for identity,collection in [('e'*32,'A'),('f'*32,'B')]:
            (folder/(identity+'.json')).write_text(json.dumps({'id':identity,'name':collection+'.txt','collection':collection,'chunks':[{'text':'source','page':2}]}))
        with patch.object(runtime,'require_ready'),patch.object(runtime,'worker',return_value={'matches':[{'chunk':0,'page':2,'text':'source'}],'method':'BM25'}) as search:
            result=runtime.search_library(self.root,{'query':'source','collection':'A'})
        self.assertEqual(search.call_count,1)
        self.assertEqual(result['matches'][0]['document_id'],'e'*32)
        self.assertEqual(result['matches'][0]['name'],'A.txt')
        with patch.object(runtime,'require_ready'),patch.object(runtime,'worker',return_value={'matches':[{'chunk':1,'text':'source'}]}) as worker:
            result=runtime.search_library(self.root,{'query':'source'})
        self.assertEqual(worker.call_count,1)
        self.assertEqual(result['matches'][0]['document_id'],'f'*32)

    def test_invalid_selected_runtime_reports_validation_required(self):
        with patch('serve.open_webui_python_update.selection',side_effect=ValueError('validation required')):
            result=runtime.status(self.root)
        self.assertFalse(result['ready']);self.assertTrue(result['requires_validation']);self.assertFalse(result['setup_busy'])
        self.assertEqual(result['error'],'validation required')

    def test_changed_original_runtime_invalidates_ready(self):
        folder=runtime.directory(self.root);(folder/'venv/Scripts').mkdir(parents=True)
        (folder/'venv/Scripts/python.exe').write_bytes(b'fixture')
        (folder/'integration-manifest.json').write_text(json.dumps({'passed':True,'source_sha256':'source','runtime_sha256':'original'}))
        with patch.object(runtime,'source_hash',return_value='source'),patch.object(runtime,'runtime_hash',return_value='changed'):
            self.assertFalse(runtime.status(self.root)['ready'])

if __name__=='__main__':unittest.main()
