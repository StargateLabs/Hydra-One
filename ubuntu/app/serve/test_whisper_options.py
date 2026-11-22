import unittest
from serve.whisper_options import decoding_options,decoding_flags

class WhisperOptionsTests(unittest.TestCase):
    def test_original_defaults(self):
        self.assertEqual(decoding_flags(decoding_options({})),['--best-of','2','--beam-size','-1','--max-len','0'])
    def test_prompt_is_one_argument_and_optional_flags_forward(self):
        options=decoding_options({'initial_prompt':'names "quoted"; no shell','best_of':4,'beam_size':3,'max_segment_length':42,'split_on_word':True,'suppress_non_speech':True})
        flags=decoding_flags(options)
        self.assertEqual(flags[flags.index('--prompt')+1],options['initial_prompt'])
        self.assertIn('--split-on-word',flags);self.assertIn('--suppress-nst',flags)
    def test_reject_invalid_before_process_start(self):
        for payload in [{'best_of':True},{'beam_size':0},{'max_segment_length':501},{'initial_prompt':'x'*1001},{'initial_prompt':'x\0y'},{'split_on_word':'true'}]:
            with self.subTest(payload=payload),self.assertRaises(ValueError):decoding_options(payload)

    def test_dtw_word_timestamps_forward_model_and_threshold(self):
        options=decoding_options({'dtw':True,'dtw_model':'C:/models/ggml-tdtw.bin','word_thold':0.2})
        flags=decoding_flags(options)
        self.assertEqual(flags[flags.index('--dtw')+1],'C:/models/ggml-tdtw.bin')
        self.assertEqual(flags[flags.index('--word-thold')+1],'0.2')
        self.assertNotIn('--dtw',decoding_flags(decoding_options({'dtw':False})))

    def test_dtw_requires_a_model_and_valid_threshold(self):
        for payload in [{'dtw':True},{'dtw':True,'dtw_model':''},{'dtw':True,'dtw_model':'x'*4097},{'dtw':True,'dtw_model':'model.bin','word_thold':'high'},{'dtw':True,'dtw_model':'model.bin','word_thold':float('nan')},{'dtw':True,'dtw_model':'model.bin','word_thold':1.5},{'word_thold':-0.1}]:
            with self.subTest(payload=payload),self.assertRaises(ValueError):decoding_options(payload)

if __name__=='__main__':unittest.main()
