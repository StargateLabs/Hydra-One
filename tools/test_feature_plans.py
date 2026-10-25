import unittest
from pathlib import Path
import tempfile
from feature_plans import feature_plan,feature_enabled,BASE
from summarize_feature import configs_match
class FeaturePlanTests(unittest.TestCase):
    def test_quarantined_source_builder_cannot_erase_manifest_or_start_build(self):
        import subprocess,sys
        root=Path(__file__).resolve().parents[1]
        manifest=root/'output/verification/hc-small-window-source.json'
        incident=root/'output/verification/hc-small-gpu-incident.json'
        if not incident.exists():self.skipTest('Local incident evidence absent')
        before=manifest.read_bytes()
        result=subprocess.run([sys.executable,str(root/'tools/build_hc_small_window.py')],
                              cwd=root,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('quarantined',result.stderr)
        self.assertEqual(before,manifest.read_bytes())

    def test_hc_small_gpu_fault_blocks_check_benchmark_and_quality_before_preflight(self):
        from feature_plans import require_applicable_plan
        for plan in ('hc-small-check','hc-small-abba','quality-hc-small-paired'):
            with self.assertRaises(RuntimeError):require_applicable_plan(plan)
    def test_hc_small_pair_keeps_cache_vocab_and_all_other_arguments(self):
        from feature_plans import FEATURES
        feature,arms=feature_plan('hc-small-abba')
        self.assertEqual(feature,'hc-small')
        self.assertTrue(all(flags==arms[0][1] for _,flags in arms))
        self.assertTrue(all('--mtp-draft-vocab' in flags for _,flags in arms))
        configs_match([dict(exe='same',args=flags,env={FEATURES[feature]:str(int(feature_enabled(name,feature)))}) for name,flags in arms],FEATURES[feature])

    def test_qfuse_draft_keeps_same_vocab_and_all_other_flags(self):
        from feature_plans import FEATURES
        feature,arms=feature_plan('qfuse-draft-abba')
        self.assertEqual(feature,'qfuse-draft')
        self.assertTrue(all(flags==arms[0][1] for _,flags in arms))
        self.assertTrue(all('--mtp-draft-vocab' in flags for _,flags in arms))
        configs_match([dict(exe='same',args=flags,env={FEATURES[feature]:str(int(feature_enabled(name,feature)))}) for name,flags in arms],FEATURES[feature])

    def test_iq3_spec3_preserves_confidence_and_changes_only_window(self):
        from summarize_feature import configs_match_for_feature
        feature,arms=feature_plan('iq3-spec3-abba')
        self.assertEqual([args[args.index('--spec')+1] for _,args in arms],['4','3','3','4'])
        self.assertTrue(all(args[args.index('--spec-min-p')+1]=='0.7' for _,args in arms))
        configs_match_for_feature([dict(exe='same',args=args,env={}) for _,args in arms],feature)

    def test_hybrid_vocab_pair_has_same_fixed_cache_and_explicit_vocab(self):
        from feature_plans import PARAMETERS
        from summarize_feature import configs_match_for_feature
        feature,arms=feature_plan('hybrid-it-abba')
        self.assertEqual([args[args.index('--expert-cache')+1] for _,args in arms],['10000']*4)
        configs=[dict(exe='same',args=args,env={}) for _,args in arms]
        configs_match_for_feature(configs,feature)
        self.assertEqual([args[-1] for _,args in arms],[PARAMETERS[feature][1],PARAMETERS[feature][2],PARAMETERS[feature][2],PARAMETERS[feature][1]])

    def test_hybrid_spec_window_changes_only_spec(self):
        from summarize_feature import configs_match_for_feature
        feature,arms=feature_plan('hybrid-spec3-abba')
        self.assertEqual([args[args.index('--spec')+1] for _,args in arms],['4','3','3','4'])
        self.assertEqual([args[args.index('--expert-cache')+1] for _,args in arms],['10000']*4)
        self.assertEqual(len(set(args[args.index('--mtp-draft-vocab')+1] for _,args in arms)),1)
        configs_match_for_feature([dict(exe='same',args=args,env={}) for _,args in arms],feature)

    def test_fetch_threads_change_only_numeric_environment(self):
        from feature_plans import FEATURES,ENV_VALUES
        from summarize_feature import configs_match_for_feature
        feature,arms=feature_plan('fetch4-abba')
        self.assertTrue(all(args==BASE for _,args in arms))
        configs=[dict(exe='same',args=args,env={FEATURES[feature]:ENV_VALUES[feature][int(feature_enabled(name,feature))]}) for name,args in arms]
        configs_match_for_feature(configs,feature)
        configs[1]['env'][FEATURES[feature]]='1'
        with self.assertRaises(RuntimeError):configs_match_for_feature(configs,feature)

    def test_persistent_reads_keep_all_other_budgets(self):
        feature,arms=feature_plan('fill-workers-abba')
        self.assertEqual(feature,'fill-workers')
        self.assertTrue(all(args==BASE for _,args in arms))
        self.assertEqual([feature_enabled(name,feature) for name,_ in arms],[False,True,True,False])

    def test_minp_changes_only_confidence_and_rejects_other_drift(self):
        from summarize_feature import configs_match_for_feature
        feature,arms=feature_plan('minp70-abba')
        self.assertEqual(feature,'minp70')
        self.assertEqual([args[-1] for _,args in arms],['0.5','0.7','0.7','0.5'])
        self.assertTrue(all(args[:-2]==BASE for _,args in arms))
        configs=[dict(exe='same',args=args,env={}) for _,args in arms]
        configs_match_for_feature(configs,feature)
        configs[2]['env']['OTHER']='1'
        with self.assertRaises(RuntimeError):configs_match_for_feature(configs,feature)

    def test_hip_batch_changes_only_upload_switch(self):
        feature,arms=feature_plan('hip-batch-abba')
        self.assertEqual(feature,'hip-batch')
        self.assertTrue(all(args==BASE for _,args in arms))
        self.assertEqual([feature_enabled(name,feature) for name,_ in arms],[False,True,True,False])
    def test_device_plan_comparison_has_same_memory_budget(self):
        feature,arms=feature_plan('device-plan-abba')
        self.assertEqual(feature,'device-plan')
        self.assertTrue(all(args==BASE for _,args in arms))
        self.assertEqual([feature_enabled(name,feature) for name,_ in arms],[False,True,True,False])
    def test_partial_cache_lfuse_is_rejected_before_gpu_work(self):
        from feature_plans import require_applicable_plan
        for plan in ('lfuse-check','lfuse-abba','quality-lfuse-paired'):
            with self.assertRaisesRegex(RuntimeError,'100%'):require_applicable_plan(plan)
        require_applicable_plan('qfuse-abba')
    def test_flags_preserve_boolean_switch_and_reject_missing_values(self):
        from feature_plans import apply_flags
        self.assertEqual(apply_flags(['--prefill','auto'],['--prefill','512','--native-bf16-extra']),['--prefill','512','--native-bf16-extra'])
        with self.assertRaises(ValueError):apply_flags([],['--prefill'])
    def test_lfuse_keeps_required_bf16_mode_in_both_arms(self):
        for plan,count in (('lfuse-check',1),('lfuse-abba',4),('quality-lfuse-paired',2)):
            feature,arms=feature_plan(plan)
            self.assertEqual(feature,'lfuse')
            self.assertEqual(len(arms),count)
            self.assertTrue(all(args==BASE+['--native-bf16-extra'] for _,args in arms))
        feature,arms=feature_plan('lfuse-abba')
        self.assertEqual([feature_enabled(name,feature) for name,_ in arms],[False,True,True,False])
    def test_publisher_does_not_mix_combined_and_single_candidates(self):
        from publish_performance_evidence import summary_files
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'output') as directory:
            folder=Path(directory)
            for name in ('20261009-175635-pcie20-abba-summary.json','20261009-183558-qfuse-pcie20-abba-summary.json'):
                (folder/name).write_text('{}')
            self.assertEqual([p.name for p in summary_files(folder,'pcie20','abba')],['20261009-175635-pcie20-abba-summary.json'])
            self.assertEqual(len(summary_files(folder,'qfuse-pcie20','abba')),1)
    def test_checks_quality_and_abba_are_isolated(self):
        for plan,count in (('qfuse-check',1),('qfuse-abba',4),('quality-qfuse-paired',2)):
            feature,arms=feature_plan(plan);self.assertEqual(feature,'qfuse');self.assertEqual(len(arms),count)
            self.assertTrue(all(args==BASE for name,args in arms))
        self.assertIsNone(feature_plan('pcie20-abba'))
    def test_abba_has_only_one_variable(self):
        feature,arms=feature_plan('qfuse-abba');self.assertEqual([feature_enabled(name,feature) for name,args in arms],[False,True,True,False])
        configs=[dict(exe='same',args=list(BASE),env={'STRATA_QFUSE':str(v)}) for v in (0,1,1,0)];configs_match(configs,'STRATA_QFUSE')
        configs[2]['env']['OTHER']='1'
        with self.assertRaises(RuntimeError):configs_match(configs,'STRATA_QFUSE')
    def test_combination_holds_pcie_constant(self):
        for suffix,count in (('check',1),('abba',4),('paired',2)):
            plan='quality-qfuse-pcie20-paired' if suffix=='paired' else 'qfuse-pcie20-'+suffix
            feature,arms=feature_plan(plan)
            self.assertEqual(len(arms),count)
            self.assertTrue(all(args==BASE+['--pcie-frac','0.20'] for name,args in arms))
            if count==4:self.assertEqual([feature_enabled(name,feature) for name,args in arms],[False,True,True,False])
if __name__=='__main__':unittest.main()
