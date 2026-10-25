import unittest
from tools.train_unsloth_qlora import conversation_tokens
class Masks(unittest.TestCase):
 def test_prompt_is_ignored_and_assistant_is_supervised(self):
  class Tokenizer:
   def apply_chat_template(self,*args,**kwargs):return {'input_ids':[3,4,5,6],'assistant_masks':[0,0,1,1]}
  row=conversation_tokens(Tokenizer(),{'messages':[]},128)
  self.assertEqual(row['labels'],[-100,-100,5,6]);self.assertEqual(row['attention_mask'],[1]*4)
 def test_missing_truncated_or_full_prompt_masks_are_rejected(self):
  for mask in ([],[0,0,0],[1,1,1],[0,0]):
   class Tokenizer:
    def apply_chat_template(self,*args,**kwargs):return {'input_ids':[3,4,5],'assistant_masks':mask}
   with self.assertRaises(ValueError):conversation_tokens(Tokenizer(),{'messages':[]},128)
if __name__=='__main__':unittest.main()
