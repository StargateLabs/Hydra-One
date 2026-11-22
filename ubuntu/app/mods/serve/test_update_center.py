import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from serve.update_center import UpdateCenter


class Updates(unittest.TestCase):
    def test_soup_release_tag_normalizes_and_busy_update_cannot_start(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            with self.assertRaisesRegex(ValueError,'Stop active'):center.prepare_soup('v0.76.0')
            center.operational_idle=lambda:True
            with patch('serve.update_center.threading') as threading_mock:
                worker=threading_mock.Thread
                state=center.prepare_soup('v0.76.0')
                self.assertEqual(state['download']['version'],'0.76.0')
                worker.return_value.start.assert_called_once()
            with self.assertRaisesRegex(ValueError,'already running'):center.prepare_soup('v0.76.0')
            with self.assertRaisesRegex(ValueError,'Unsupported'):center.prepare_soup('../bad')
    def test_two_dashboards_share_the_latest_completed_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            first=UpdateCenter(folder);second=UpdateCenter(folder)
            first.job={'state':'prepared','component':'strata','version':'v0.1.43'};first._persist_job()
            self.assertEqual(second.status()['download']['component'],'strata')
            first.job={'state':'prepared','component':'llama.cpp','version':'b2'};first._persist_job()
            self.assertEqual(second.status()['download']['version'],'b2')

    def test_single_component_plan_keeps_other_versions_pinned(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            center.result['components']=[{'id':'transformers','version':'5.19.0'}]
            center.result['environments']=[{'name':'Strata','python':'python.exe','update_check':{'state':'checked'},'packages':[{'name':'transformers','version':'5.5.0','available_version':'5.19.0'},{'name':'numpy','version':'2.2.0','available_version':'2.4.0'},{'name':'torch','version':'2.11.0+rocm7','available_version':'2.12.0'}]}]
            with patch('serve.update_center.threading.Thread'):
                result=center.dependency_plan('Strata','transformers','5.19.0')
            pins=(Path(result['download']['plan_directory'])/'requirements.txt').read_text(encoding='utf-8')
            self.assertIn('transformers==5.19.0',pins);self.assertIn('numpy==2.2.0',pins);self.assertIn('torch==2.11.0+rocm7',pins)
            self.assertNotIn('numpy==2.4.0',pins)
            self.assertEqual(result['download']['component'],'transformers')
            with self.assertRaises(ValueError):center.dependency_plan('Strata','transformers','unknown')

    def test_status_counts_only_newer_versions_and_recognizes_selected_gpu(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir()
            (root/'data/runtime-gpu-selection.json').write_text(json.dumps({'active':{'directory':'candidate','version':'b2'}}),encoding='utf-8')
            center=UpdateCenter(root)
            center.result['components']=[{'id':'opencode','repository':'anomalyco/opencode','version':'1.0','assets':[]},{'id':'llama.cpp','repository':'unslothai/llama.cpp','version':'b2','assets':[]}]
            center.job={'state':'prepared','component':'llama.cpp','result':{'candidate_directory':'candidate'}}
            with patch.object(center,'installed_versions',return_value={'opencode':{'installed_version':'2.0'},'llama.cpp':{'installed_version':'b2'}}),patch('serve.llama_gpu_update.proof',return_value={'passed':True}):
                result=center.status()
            states={row['id']:row['update_state'] for row in result['components']}
            self.assertEqual(states['opencode'],'ahead');self.assertEqual(states['llama.cpp'],'current')
            self.assertEqual(result['operation_state'],'selected_gpu')
            self.assertEqual(result['download']['state'],'prepared')

    def test_voicestudio_version_comes_from_installed_executable_without_backend(self):
        from serve.voicestudio import desktop_inventory
        with patch('serve.voicestudio.desktop_executable',return_value=Path('VoiceStudio.exe')), \
             patch('serve.native_libraries.file_version',return_value='0.5.6.0'):
            result=desktop_inventory()
        self.assertEqual(result['installed_version'],'0.5.6')
        self.assertEqual(result['installed_source'],'windows_file_version_resource')
        self.assertTrue(result['desktop_installed'])
        self.assertFalse(result['runtime_validated'])

    def test_installed_inventory_never_contacts_voicestudio_backend(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            with patch('serve.voicestudio.VoiceStudio.status',side_effect=AssertionError('Inventory must not wait for HTTP')):
                result=center.installed_versions()
            self.assertIn('voicestudio',result)
            self.assertFalse(result['voicestudio']['runtime_validated'])

    def test_studio_version_is_not_compared_to_python_and_soup_cli_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            center.result['environments']=[{'name':'Unsloth','packages':[{'name':'unsloth','version':'2026.10.3'}]},{'name':'Soup','packages':[{'name':'soup-cli','version':'0.75.0'}]}]
            with patch('serve.studio_inventory.installed_studio',return_value=None):installed=center.installed_versions()
            self.assertIsNone(installed['unsloth']['installed_version']);self.assertFalse(installed['unsloth']['version_comparable'])
            self.assertEqual(installed['unsloth']['installed_runtime_version'],'2026.10.3')
            self.assertEqual(installed['soup']['installed_version'],'0.75.0')

    def test_strata_selection_returns_status_without_locking_and_survives_restart(self):
        import threading
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.operational_idle=lambda:True
            center.configuration_provider=lambda:'fixture.json'
            center.job={'state':'prepared','component':'strata','result':{}}
            values=[]
            with patch('serve.strata_update.activate',return_value={'version':'0.1.42'}):
                worker=threading.Thread(target=lambda:values.append(center.activate()),daemon=True)
                worker.start();worker.join(2)
                self.assertFalse(worker.is_alive(),'Selection must not deadlock while building status')
            self.assertEqual(values[0]['download']['state'],'selected_strata')
            restored=UpdateCenter(folder)
            self.assertEqual(restored.job['state'],'selected_strata')
            restored.operational_idle=lambda:True
            with patch('serve.strata_update.rollback',return_value={}):
                self.assertEqual(restored.rollback('strata')['download']['state'],'rolled_back')

    def test_live_version_preserves_manifest_backend(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'engine').mkdir()
            (root/'engine/BUILD.json').write_text(json.dumps({'version':'0.1.40','backend':'hip'}),encoding='utf-8')
            center=UpdateCenter(root)
            center.installed_provider=lambda:{'strata':{'installed_version':'0.1.40.3','installed_source':'engine_reported_version'}}
            metadata=center.installed_versions()['strata']
            self.assertEqual(metadata['installed_backend'],'hip')
            self.assertEqual(metadata['installed_version'],'0.1.40.3')

    def test_recommendation_matches_amd_runtime_and_gpu_target(self):
        from serve.update_center import recommend_package
        def asset(number,name):return {'id':number,'name':name,'digest':'sha256:abc','platform_compatibility':{'state':'platform_matches'}}
        assets=[asset(1,'windows-x64-cuda12.zip'),asset(2,'windows-x64-rocm-gfx120X.zip'),asset(3,'windows-x64-rocm-gfx110X.zip')]
        row={'id':'llama.cpp','installed_backend':'rocm','installed_gpu_target':'gfx110X','assets':assets}
        self.assertEqual(recommend_package(row)['asset_id'],3)
        row['assets']=assets[:2]
        self.assertIsNone(recommend_package(row)['asset_id'])

    def test_strata_recommendation_never_selects_model_specific_or_unproven_builds(self):
        from serve.update_center import recommend_package
        def asset(number,name):return {'id':number,'name':name,'digest':'sha256:'+'a'*64,'platform_compatibility':{'state':'platform_matches'}}
        def declared(archs):return {'section':'engine','backend':'hip','platform':'windows-x86_64','variant':'rdna3','archs':archs}
        engine='strata-engine-0.1.55-windows-x86_64-hip-rdna3.tar.gz'
        model='strata-dsv41-0.1.55-windows-x86_64-hip-rdna3.tar.gz'
        control='strata-control-0.1.55-windows-x86_64.zip'
        row={'id':'strata','installed_backend':'hip','installed_gpu_archs':['gfx1100'],
             'assets':[asset(1,model),asset(2,control),asset(3,engine)],
             'release_packages':{engine:declared(['gfx1100','gfx1101','gfx1102','gfx1151']),model:declared(['gfx1100'])}}
        self.assertEqual(recommend_package(row)['asset_id'],3)
        row['assets']=[asset(1,model),asset(2,control)]
        self.assertIsNone(recommend_package(row)['asset_id'])
        row={'id':'strata','installed_backend':'hip','installed_gpu_archs':['gfx1100'],'assets':[asset(3,engine)],
             'release_packages':{engine:declared(['gfx1151'])}}
        self.assertIsNone(recommend_package(row)['asset_id'])
        row['installed_gpu_archs']=[]
        selection=recommend_package(row)
        self.assertIsNone(selection['asset_id']);self.assertEqual(selection['reason'],'gpu_target_unverified')
        row['installed_gpu_archs']=['gfx1100'];row['release_packages']={}
        self.assertIsNone(recommend_package(row)['asset_id'])

    def test_release_feed_declarations_require_matching_asset_digest(self):
        import json as json_module
        from unittest.mock import patch
        from serve.update_center import strata_feed_packages
        digest='b'*64;engine='strata-engine-9-windows-x86_64-hip-rdna3.tar.gz';model='strata-dsv41-9-windows-x86_64-hip-rdna3.tar.gz'
        release={'tag_name':'v9','assets':[{'name':engine,'digest':'sha256:'+digest},{'name':model,'digest':'sha256:'+'c'*64}]}
        feed={'engine':{'packages':[{'url':engine,'sha256':digest,'backend':'hip','platform':'windows-x86_64','archs':['gfx1100']}]},
              'dsv41':{'packages':[{'url':model,'sha256':'d'*64,'backend':'hip','archs':['gfx1100']}]}}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):return json_module.dumps(feed).encode()
        with patch('serve.update_center.urllib.request.urlopen',return_value=Response()):
            declared=strata_feed_packages(release)
        self.assertIn(engine,declared)
        self.assertNotIn(model,declared)

    def test_full_profile_strata_validation_requires_fresh_operator_approval(self):
        import json
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);center=UpdateCenter(root);center.folder.mkdir(parents=True)
            center.job={'state':'prepared','component':'strata','result':{'candidate_directory':str(center.folder/'candidates/test'),'files':[{'path':'strata.exe','sha256':'a'*64}]}}
            center.operational_idle=lambda:True
            center.validate_strata_startup=Mock()
            with self.assertRaisesRegex(ValueError,'blocked'):
                center.validate_strata_inference()
            center.validate_strata_startup.assert_not_called()
            self.assertEqual(center.job['state'],'prepared')
            (root/'data').mkdir(exist_ok=True)
            approval=root/'data/strata-full-profile-approval.json'
            approval.write_text(json.dumps({'approved':True,'reason':'manual retest'}),encoding='utf-8')
            with patch('serve.update_center.threading.Thread') as thread:
                center.validate_strata_inference()
            self.assertEqual(center.job['state'],'validating')
            self.assertFalse(approval.exists())
            thread.return_value.start.assert_called_once()

    def test_strata_startup_does_not_certify_inference(self):
        import json
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            directory=center.folder/'candidates/test'
            directory.mkdir(parents=True)
            (directory/'rocm/bin').mkdir(parents=True)
            (directory/'BUILD.json').write_text(json.dumps({'version':'0.1.42','backend':'hip','lib_dirs':['rocm/bin']}))
            (directory/'strata.exe').write_bytes(b'fixture')
            files=[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in directory.iterdir() if p.is_file()]
            center.job={'state':'prepared','component':'strata','result':{'candidate_directory':str(directory),'files':files}}
            with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,'strata generate','')) as run:
                center.validate('')
                self.assertEqual(run.call_args.kwargs['env']['HIP_VISIBLE_DEVICES'],'-1')
                self.assertIn(str(directory/'rocm/bin'),run.call_args.kwargs['env']['PATH'])
            self.assertEqual(center.job['state'],'prepared')
            self.assertTrue(center.job['result']['startup_validation']['passed'])
            self.assertFalse(center.job['result']['runtime_validated'])
            with self.assertRaises(ValueError):center.activate()
            (directory/'strata.exe').write_bytes(b'changed')
            with patch('subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'changed'):center.validate('')
                run.assert_not_called()

    def test_preparation_reuses_intact_copy_but_never_old_validation(self):
        import zipfile
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.folder.mkdir(parents=True)
            archive=center.folder/'test.zip'
            with zipfile.ZipFile(archive,'w') as bundle:bundle.writestr('engine.exe',b'original')
            staged={'path':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'source':'https://github.com/Niko1221/Strata/releases/download/v1/test.zip'}
            center.job={'state':'staged','component':'strata','result':staged}
            center.prepare();first=dict(center.job['result'])
            center.job={'state':'staged','component':'strata','result':staged}
            center.prepare();self.assertEqual(center.job['result']['candidate_directory'],first['candidate_directory'])
            self.assertTrue(center.job['result']['reused_verified_copy'])
            self.assertFalse(center.job['result']['runtime_validated'])
            (Path(first['candidate_directory'])/'engine.exe').write_bytes(b'tampered')
            center.job={'state':'staged','component':'strata','result':staged}
            center.prepare();self.assertNotEqual(center.job['result']['candidate_directory'],first['candidate_directory'])
            self.assertEqual((Path(center.job['result']['candidate_directory'])/'engine.exe').read_bytes(),b'original')

    def test_tar_gz_release_is_extracted_into_an_isolated_candidate(self):
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.folder.mkdir(parents=True)
            archive=center.folder/'release.tar.gz'
            with tarfile.open(archive,'w:gz') as bundle:
                for name,data in [('strata.exe',b'exe'),('BUILD.json',b'{}'),('rocm/bin/lib.dll',b'lib')]:
                    info=tarfile.TarInfo(name);info.size=len(data);bundle.addfile(info,io.BytesIO(data))
            staged={'path':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'source':'https://github.com/Niko1221/Strata/releases/download/v1/release.tar.gz'}
            center.job={'state':'staged','component':'strata','result':staged}
            center.prepare()
            self.assertEqual(center.job['state'],'prepared')
            candidate=Path(center.job['result']['candidate_directory'])
            self.assertTrue(candidate.is_relative_to((center.folder/'candidates').resolve()))
            self.assertEqual((candidate/'strata.exe').read_bytes(),b'exe')
            hashes={row['path']:row['sha256'] for row in center.job['result']['files']}
            self.assertEqual(hashes['rocm/bin/lib.dll'],hashlib.sha256(b'lib').hexdigest())
            self.assertFalse(center.job['result']['runtime_validated']);self.assertFalse(center.job['result']['activated'])

    def test_tar_gz_traversal_and_links_are_rejected_without_partial_output(self):
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.folder.mkdir(parents=True)
            for label in ('traversal','link'):
                archive=center.folder/(label+'.tar.gz')
                with tarfile.open(archive,'w:gz') as bundle:
                    if label=='traversal':bundle.addfile(tarfile.TarInfo('../evil'),io.BytesIO(b'x'))
                    else:
                        link=tarfile.TarInfo('link');link.type=tarfile.SYMTYPE;link.linkname='strata.exe';bundle.addfile(link)
                center.job={'state':'staged','component':'strata','result':{'path':str(archive),
                    'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                    'source':'https://github.com/Niko1221/Strata/releases/download/v1/'+archive.name}}
                with self.assertRaises(ValueError):center.prepare()
                self.assertEqual(center.job['state'],'staged')
                self.assertFalse(list((center.folder/'candidates').glob('*')))

    def test_unknown_and_unsigned_assets_cannot_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            with self.assertRaises(ValueError):center.stage('unknown',1)
            center.result['components']=[{'id':'strata','repository':'Niko1221/Strata','assets':[{'id':1}]}]
            with self.assertRaisesRegex(ValueError,'SHA-256'):center.stage('strata',1)

    def test_integrity_failure_removes_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);target=Path(folder)/'candidate.zip'
            asset={'url':'https://github.com/Niko1221/Strata/releases/download/v1/a.zip',
                   'bytes':3,'digest':'sha256:'+'0'*64}
            with patch('urllib.request.urlopen',return_value=io.BytesIO(b'abc')):center._download(asset,target)
            self.assertEqual(center.job['state'],'failed')
            self.assertFalse(target.exists());self.assertFalse(target.with_name('candidate.zip.partial').exists())

    def test_staged_copy_is_never_activated(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);target=Path(folder)/'candidate.zip'
            asset={'url':'https://github.com/Niko1221/Strata/releases/download/v1/a.zip',
                   'bytes':3,'digest':'sha256:'+hashlib.sha256(b'abc').hexdigest()}
            with patch('urllib.request.urlopen',return_value=io.BytesIO(b'abc')):center._download(asset,target)
            self.assertEqual(center.job['state'],'staged')
            self.assertFalse(center.job['result']['activated'])
            self.assertFalse(center.job['result']['runtime_validated'])
            self.assertEqual(target.read_bytes(),b'abc')
            self.assertEqual(UpdateCenter(folder).job['state'],'staged')

    def test_restart_removes_only_known_dead_workers_partial_file(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);center=UpdateCenter(root);center.folder.mkdir(parents=True)
            target=center.folder/'known.zip';partial=target.with_name('known.zip.partial');partial.write_bytes(b'partial')
            unrelated=center.folder/'other.zip.partial';unrelated.write_bytes(b'keep')
            center.job={'state':'downloading','download_path':str(target),'owner_pid':2147483646};center._persist_job()
            with patch('psutil.pid_exists',return_value=False):restored=UpdateCenter(root)
            self.assertEqual(restored.job['removed_partial_bytes'],7);self.assertFalse(partial.exists());self.assertTrue(unrelated.exists())
            self.assertEqual(restored.job['state'],'interrupted')

    def test_restart_never_removes_partial_of_a_live_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.folder.mkdir(parents=True)
            target=center.folder/'known.zip';partial=target.with_name('known.zip.partial');partial.write_bytes(b'keep')
            center.job={'state':'downloading','download_path':str(target),'owner_pid':2147483646};center._persist_job()
            with patch('psutil.pid_exists',return_value=True):restored=UpdateCenter(folder)
            self.assertTrue(partial.exists())
            self.assertEqual(restored.job['state'],'downloading')

    def test_second_manager_does_not_interrupt_a_live_python_validation(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.job={'state':'validating_python','owner_pid':os.getpid()};center._persist_job()
            restored=UpdateCenter(folder)
            self.assertEqual(restored.job['state'],'validating_python')
            self.assertEqual(__import__('json').loads(center.job_path.read_text())['state'],'validating_python')

    def test_recent_check_does_not_repeat_network(self):
        import time
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.result['checked_at']=time.time();center.result['environments']=[];center.result['library_updates_checked']=True;center.result['native_libraries']={};center.result['runtimes']=[]
            from serve.update_center import SOURCES,ENVIRONMENT_INVENTORY_VERSION
            center.result['environment_inventory_version']=ENVIRONMENT_INVENTORY_VERSION
            center.result['components']=[{'id':name,'repository':repo} for name,repo in SOURCES.items()]
            with patch('urllib.request.urlopen') as fetch:center.check()
            fetch.assert_not_called()

    def test_old_environment_inventory_is_refreshed_without_running_check_inline(self):
        import time
        from serve.update_center import SOURCES
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            center.result.update(state='complete',checked_at=time.time(),environments=[],library_updates_checked=True,native_libraries={},runtimes=[],components=[{'id':name,'repository':repo} for name,repo in SOURCES.items()])
            with patch('serve.update_center.threading.Thread') as thread:
                center.check()
            thread.assert_called_once();thread.return_value.start.assert_called_once()
            self.assertEqual(center.result['state'],'checking')

    def test_verified_archive_is_reused_without_another_download(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.folder.mkdir(parents=True)
            payload=b'archive';digest=hashlib.sha256(payload).hexdigest();name='cpu.zip'
            target=center.folder/(digest[:12]+'-'+name);target.write_bytes(payload)
            url='https://github.com/unslothai/audio.cpp/releases/download/v1/cpu.zip'
            target.with_name(target.name+'.json').write_text(json.dumps({'path':str(target),'sha256':digest,'source':url,'bytes':len(payload)}))
            center.result['components']=[{'id':'audio.cpp','repository':'unslothai/audio.cpp','version':'v1','assets':[{'id':1,'name':name,'bytes':len(payload),'digest':'sha256:'+digest,'url':url}]}]
            with patch('serve.update_center.threading') as threading_mock:
                worker=threading_mock.Thread
                result=center.stage('audio.cpp',1)
            worker.assert_not_called();self.assertTrue(result['download']['reused_verified_copy']);self.assertEqual(result['download']['state'],'staged')
            self.assertEqual(result['download']['result']['published_version'],'v1')
            target.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'integrity'):center.stage('audio.cpp',1)

    def test_file_hashing_does_not_load_the_entire_archive(self):
        from serve.update_center import file_sha256
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'file';data=b'x'*(2*1024**2+3);target.write_bytes(data)
            with patch('pathlib.Path.read_bytes',side_effect=AssertionError('unbounded read')):
                self.assertEqual(file_sha256(target),hashlib.sha256(data).hexdigest())

    def test_cancelled_download_never_promoted(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);target=Path(folder)/'candidate.zip';center.cancel()
            asset={'url':'https://github.com/Niko1221/Strata/releases/download/v1/a.zip',
                   'bytes':3,'digest':'sha256:'+hashlib.sha256(b'abc').hexdigest()}
            with patch('urllib.request.urlopen',return_value=io.BytesIO(b'abc')):center._download(asset,target)
            self.assertEqual(center.job['state'],'cancelled');self.assertFalse(target.exists())

    def test_installed_and_available_versions_are_separate(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'engine').mkdir()
            (root/'engine/BUILD.json').write_text(json.dumps({'version':'0.1.custom'}))
            center=UpdateCenter(root)
            center.result['components']=[{'id':'strata','repository':'Niko1221/Strata','version':'v0.2'}]
            row=center.status()['components'][0]
            self.assertEqual(row['installed_version'],'0.1.custom')
            self.assertEqual(row['version'],'v0.2')
            center.installed_provider=lambda:{'strata':{'installed_version':'0.1.runtime','installed_source':'engine_reported_version'}}
            self.assertEqual(center.status()['components'][0]['installed_version'],'0.1.runtime')

    def test_upstream_llama_cache_cannot_replace_unsloth_fork(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            center.result['components']=[{'id':'llama.cpp','repository':'ggml-org/llama.cpp','version':'v999','assets':[{'id':1}]}]
            row=center.status()['components'][0]
            self.assertEqual(row['state'],'source_changed');self.assertEqual(row['assets'],[])
            self.assertIsNone(row['version'])

    def test_dependency_conflicts_are_not_reported_healthy(self):
        import subprocess
        from serve.update_center import check_dependencies
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],1,'package requires missing dependency','')):
            self.assertEqual(check_dependencies('python')['state'],'conflicts')
        with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('python',30)):
            self.assertEqual(check_dependencies('python')['state'],'unavailable')

    def test_wrong_source_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            center.result['components']=[{'id':'llama.cpp','repository':'ggml-org/llama.cpp','assets':[{'id':1}]}]
            with self.assertRaisesRegex(ValueError,'source'):
                center.stage('llama.cpp',1)

    def _zip_candidate(self, folder, name, content):
        import zipfile
        center=UpdateCenter(folder);center.folder.mkdir(parents=True)
        target=center.folder/'release.zip'
        with zipfile.ZipFile(target,'w') as archive:archive.writestr(name,content)
        center.job={'state':'staged','result':{'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}}
        return center,target

    def test_prepare_preserves_live_mod_and_records_isolated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            live=Path(folder)/'custom.py';live.write_bytes(b'local improvements')
            center,target=self._zip_candidate(folder,'bin/engine.exe',b'candidate')
            result=center.prepare()['download']['result']
            self.assertFalse(result['activated']);self.assertFalse(result['runtime_validated'])
            self.assertEqual(live.read_bytes(),b'local improvements')
            self.assertEqual((Path(result['candidate_directory'])/'bin/engine.exe').read_bytes(),b'candidate')
            self.assertEqual(result['files'][0]['sha256'],hashlib.sha256(b'candidate').hexdigest())

    def test_prepare_rejects_traversal_and_changed_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            center,target=self._zip_candidate(folder,'../custom.py',b'overwrite')
            with self.assertRaisesRegex(ValueError,'Unsafe'):center.prepare()
            self.assertFalse((Path(folder)/'custom.py').exists())
            target.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):center.prepare()

    def test_validation_rejects_unprepared_or_wrong_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            with self.assertRaisesRegex(ValueError,'Prepare'):center.validate('anything')
            center.job={'state':'prepared','component':'unsloth'}
            with self.assertRaisesRegex(ValueError,'llama.cpp'):center.validate('anything')

    def test_download_cannot_replace_running_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.job={'state':'validating'}
            with self.assertRaisesRegex(ValueError,'already running'):center.stage('strata',1)

    def test_activation_and_rollback_preserve_original_runtime(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            center,target=self._zip_candidate(folder,'bin/llama-server.exe',b'candidate')
            center.prepare();center.operational_idle=lambda:True
            center.job.update(state='validated',component='llama.cpp')
            center.job['result'].update(runtime_validated=True,validation={'backend':'cpu'})
            original=Path(folder)/'engine/original.exe';original.parent.mkdir();original.write_bytes(b'original')
            center.activate()
            selection=json.loads((Path(folder)/'data/runtime-selection.json').read_text())
            self.assertEqual(selection['active']['scope'],'llama_cpu')
            self.assertEqual(original.read_bytes(),b'original')
            center.rollback()
            self.assertIsNone(json.loads((Path(folder)/'data/runtime-selection.json').read_text())['active'])
            self.assertEqual(original.read_bytes(),b'original')

    def test_activation_rejects_changed_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            center,target=self._zip_candidate(folder,'llama-server.exe',b'candidate')
            center.prepare();center.operational_idle=lambda:True
            center.job.update(state='validated',component='llama.cpp')
            center.job['result'].update(runtime_validated=True,validation={'backend':'cpu'})
            (Path(center.job['result']['candidate_directory'])/'llama-server.exe').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):center.activate()

    def test_audio_activation_and_rollback_do_not_change_llama_selection(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            center,target=self._zip_candidate(folder,'audiocpp_server.exe',b'audio candidate')
            center.prepare();center.operational_idle=lambda:True
            center.job.update(state='validated',component='audio.cpp')
            center.job['result'].update(runtime_validated=True,validation={'backend':'cpu','task':'tts'})
            center.activate()
            selection=json.loads((Path(folder)/'data/audio-runtime-selection.json').read_text())
            self.assertEqual(selection['active']['scope'],'audio_cpu')
            self.assertFalse((Path(folder)/'data/runtime-selection.json').exists())
            center.rollback('audio.cpp')
            self.assertIsNone(json.loads((Path(folder)/'data/audio-runtime-selection.json').read_text())['active'])
            center.activate()
            self.assertEqual(json.loads((Path(folder)/'data/audio-runtime-selection.json').read_text())['active']['scope'],'audio_cpu')

    def test_prepared_candidate_survives_restart_without_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            center,target=self._zip_candidate(folder,'llama-server.exe',b'candidate')
            center.prepare()
            restored=UpdateCenter(folder)
            self.assertEqual(restored.job['state'],'prepared')
            self.assertEqual(restored.job['result']['candidate_directory'],center.job['result']['candidate_directory'])
            self.assertFalse(restored.job['result']['activated'])

    def test_interrupted_operations_are_not_automatically_restarted(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir()
            for state,expected in [('downloading','interrupted'),('preparing','staged'),('validating','prepared')]:
                (root/'data/update-job.json').write_text(json.dumps({'state':state}))
                restored=UpdateCenter(root)
                self.assertEqual(restored.job['state'],expected)
                self.assertIn('interrupted',restored.job['error'])

    def test_dependency_plan_preserves_vendor_gpu_pin(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder)
            center.result['environments']=[{'name':'Unsloth','python':'python','update_check':{'state':'checked'},
                'packages':[{'name':'torch','version':'2.11.0+rocm7.14.0','available_version':'2.12.0'}]}]
            with patch('threading.Thread'):
                result=center.dependency_plan('Unsloth')
            pins=(Path(result['download']['plan_directory'])/'requirements.txt').read_text()
            self.assertIn('torch==2.11.0+rocm7.14.0',pins)
            self.assertEqual(result['download']['protected_packages'],['torch'])

    def test_resolver_failure_never_installs_or_activates(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);plan=Path(folder)/'plan';plan.mkdir()
            (plan/'requirements.txt').write_text('package==1')
            with patch('subprocess.run',return_value=subprocess.CompletedProcess([],1,'','incompatible')) as run:
                center._resolve_dependencies('python',plan)
            self.assertIn('--dry-run',run.call_args.args[0])
            self.assertIn('--only-binary=:all:',run.call_args.args[0])
            self.assertEqual(center.job['state'],'resolution_failed')
            self.assertFalse((Path(folder)/'data/runtime-selection.json').exists())

    def test_candidate_install_rejects_unofficial_wheel(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.operational_idle=lambda:True
            plan=center.folder/'python-plans/test';plan.mkdir(parents=True)
            (plan/'pip-report.json').write_text(json.dumps({'install':[{'download_info':{
                'url':'https://example.com/a.whl','archive_info':{'hashes':{'sha256':'a'*64}}}}]}))
            center.job={'state':'resolved','plan_directory':str(plan)}
            with self.assertRaisesRegex(ValueError,'official PyPI'):center.install_dependencies()
            self.assertFalse((plan/'environment').exists())

    def test_candidate_failure_preserves_active_environment(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);plan=Path(folder)/'plan';plan.mkdir()
            source=Path(folder)/'active';source.mkdir();(source/'marker').write_text('unchanged')
            with patch('subprocess.run',return_value=subprocess.CompletedProcess([],1,'','failed')):
                center._install_dependencies('python',plan)
            self.assertEqual(center.job['state'],'candidate_failed')
            self.assertEqual((source/'marker').read_text(),'unchanged')

    def test_python_selection_requires_functional_startup_evidence(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.operational_idle=lambda:True
            plan=center.folder/'python-plans/test';plan.mkdir(parents=True)
            (plan/'environment-manifest.json').write_text(json.dumps({'dependency_health':{'state':'healthy'},'server_suite':{'passed':True}}))
            center.job={'state':'candidate_installed','name':'Strata','result':{'plan_directory':str(plan)}}
            with self.assertRaisesRegex(ValueError,'actual dashboard'):center.select_python()
            self.assertFalse((Path(folder)/'data/dashboard-python-selection.json').exists())

    def test_wrong_platform_assets_are_rejected(self):
        from serve.update_center import platform_compatibility
        with patch('platform.system',return_value='Windows'),patch('platform.machine',return_value='AMD64'):
            self.assertEqual(platform_compatibility('engine-linux-x64.zip')['state'],'incompatible')
            self.assertEqual(platform_compatibility('engine-windows-arm64.zip')['state'],'incompatible')
            self.assertEqual(platform_compatibility('engine-windows-x64-cpu.zip')['state'],'platform_matches')

    def test_selection_and_rollback_cannot_interfere_with_running_operations(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.operational_idle=lambda:True
            for state in ('downloading','preparing','validating','resolving','installing_candidate'):
                center.job={'state':state}
                for action in (center.rollback,center.select_python,lambda:center.select_python(rollback=True)):
                    with self.assertRaisesRegex(ValueError,'already running'):action()
                self.assertEqual(center.job['state'],state)

    def test_python_candidate_requires_current_sources(self):
        import json
        from serve.update_center import source_fingerprint
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.operational_idle=lambda:True
            plan=center.folder/'python-plans/test';plan.mkdir(parents=True)
            python=plan/'environment/Scripts/python.exe';python.parent.mkdir(parents=True);python.touch()
            manifest={'python':str(python),'dependency_health':{'state':'healthy'},'server_suite':{'passed':True},'dashboard_start_verified':True,'core_source_sha256':source_fingerprint(folder)}
            (plan/'environment-manifest.json').write_text(json.dumps(manifest))
            center.job={'state':'candidate_installed','name':'Strata','result':{'plan_directory':str(plan)}}
            center.select_python()
            source=Path(folder)/'serve/new.py';source.parent.mkdir();source.write_text('changed=True')
            with self.assertRaisesRegex(ValueError,'sources have changed'):center.select_python()
            center.job['error']='probe failed'
            with self.assertRaisesRegex(ValueError,'validation failed'):center.select_python()

    def test_failed_python_suite_keeps_previous_installation(self):
        import json,subprocess
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);plan=center.folder/'python-plans/test';plan.mkdir(parents=True)
            original=Path(folder)/'data/dashboard-python-selection.json';original.parent.mkdir(exist_ok=True);original.write_text('{"active":"original"}')
            center.job={'state':'validating_python'}
            with patch('subprocess.run',return_value=subprocess.CompletedProcess([],1)):
                center._validate_python(plan,Path('python'),Path('config'))
            self.assertEqual(center.job['state'],'candidate_installed');self.assertIn('suite failed',center.job['error'])
            self.assertEqual(json.loads(original.read_text())['active'],'original')

    def test_python_probe_explicitly_uses_unloaded_strata_and_stops_child(self):
        import json,subprocess
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);plan=center.folder/'python-plans/test';plan.mkdir(parents=True)
            config=Path(folder)/'config.json';config.write_text('{}')
            (plan/'environment-manifest.json').write_text('{"dependency_health":{"state":"healthy"}}')
            def suite(command,**kwargs):
                kwargs['stdout'].write('Ran 1 test in 0.01s\nOK\n');return subprocess.CompletedProcess(command,0)
            def response(url,**kwargs):
                data={'live':{'state':'unloaded'}}
                if url.endswith('/v1/models'):data={'data':[{'id':json.loads((plan/'dashboard-probe.json').read_text())['model_name']}]}
                return io.BytesIO(json.dumps(data).encode())
            child=Mock();child.poll.return_value=None
            with patch('subprocess.run',side_effect=suite),patch('subprocess.Popen',return_value=child) as launch,patch('urllib.request.urlopen',side_effect=response):
                center._validate_python(plan,Path('python'),config)
            command=launch.call_args.args[0]
            self.assertEqual(command[command.index('--engine')+1],'strata');self.assertIn('--lazy',command)
            child.terminate.assert_called_once();self.assertEqual(center.job['state'],'candidate_installed')
            self.assertTrue(center.job['result']['dashboard_start_verified'])

    def test_runtime_change_refreshes_installed_versions_without_network(self):
        from serve.update_center import refresh_running_environment
        from types import SimpleNamespace
        environment={'packages':[{'name':'example','version':'1','available_version':'2'}]}
        packages=[SimpleNamespace(metadata={'Name':'example'},version='2'),SimpleNamespace(metadata={'Name':'new-package'},version='1')]
        with patch('importlib.metadata.distributions',return_value=packages),patch('serve.update_center.check_dependencies',return_value={'state':'healthy'}),patch('urllib.request.urlopen') as network:
            refresh_running_environment(environment,'candidate-python')
        network.assert_not_called()
        self.assertEqual(environment['packages'][0]['version'],'2');self.assertEqual(environment['packages'][0]['update_state'],'current')
        self.assertIsNone(environment['packages'][1]['available_version']);self.assertEqual(environment['python'],'candidate-python')

    def test_check_inventory_failure_persists_error_and_allows_retry(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.result['state']='checking'
            with patch('serve.update_center.SOURCES',{}),patch('serve.python_inference_update.selected_python',side_effect=RuntimeError('Inventory exploded')),patch('urllib.request.urlopen') as network:
                center._check()
            network.assert_not_called()
            self.assertEqual(center.result['state'],'error')
            self.assertIn('Inventory exploded',center.result['error'])
            self.assertEqual(json.loads(center.cache.read_text())['state'],'error')
            with patch('serve.update_center.threading.Thread') as worker:
                center.check()
            worker.return_value.start.assert_called_once()
            self.assertEqual(center.result['state'],'checking')

    def test_download_cleanup_failure_preserves_original_error_and_exits_busy_state(self):
        with tempfile.TemporaryDirectory() as folder:
            center=UpdateCenter(folder);center.job={'state':'downloading'}
            target=Path(folder)/'candidate.zip'
            asset={'url':'https://github.com/Niko1221/Strata/releases/download/v1/a.zip','bytes':3,'digest':'sha256:'+'0'*64}
            with patch.object(center,'_persist_job'),patch('serve.customization_backup.snapshot',return_value={}),patch('urllib.request.urlopen',return_value=io.BytesIO(b'abc')),patch('pathlib.Path.unlink',side_effect=PermissionError('cleanup denied')):
                center._download(asset,target)
            self.assertEqual(center.job['state'],'failed')
            self.assertIn('Release size or SHA-256 verification failed',center.job['error'])
            self.assertIn('cleanup denied',center.job['partial_cleanup_error'])
            self.assertTrue(target.with_name(target.name+'.partial').exists())

    def test_desktop_platform_aliases_are_classified_without_cross_os_matches(self):
        from serve.update_center import platform_compatibility
        with patch('platform.system',return_value='Windows'),patch('platform.machine',return_value='AMD64'):
            for name in ('VoiceStudio-0.5.7-win-x64.exe','electron-stable-win32-x64.yml','tool-win64-x64.zip'):
                self.assertEqual(platform_compatibility(name)['state'],'platform_matches',name)
            for name in ('VoiceStudio-0.5.7-mac-x64.dmg','tool-macos-x64.zip','tool-darwin-x64.zip'):
                self.assertEqual(platform_compatibility(name)['state'],'incompatible',name)
        with patch('platform.system',return_value='Darwin'),patch('platform.machine',return_value='x86_64'):
            self.assertEqual(platform_compatibility('VoiceStudio-0.5.7-mac-x64.dmg')['state'],'platform_matches')
            self.assertEqual(platform_compatibility('VoiceStudio-0.5.7-win-x64.exe')['state'],'incompatible')
