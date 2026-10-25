"""Reject malformed learned profiles before model loading."""
from pathlib import Path
import struct
import tempfile
import unittest
from learn_expert_profile import ROOT,validate_profile

class ProfileValidation(unittest.TestCase):
    def test_valid_and_invalid_profiles(self):
        original = (ROOT/'data/expert-profile.bin').read_bytes()
        with tempfile.TemporaryDirectory(dir=ROOT/'output/verification') as folder:
            path = Path(folder)/'candidate.bin';path.write_bytes(original)
            self.assertEqual(validate_profile(path)[0]['pairs'],24576)
            mutations = [b'',original[:-1],b'NOPE'+original[4:],
                original[:4]+struct.pack('<I',2)+original[8:],
                original[:24]+original[28:32]+original[28:],
                original[:-4]+struct.pack('<i',-1)]
            for data in mutations:
                with self.subTest(size=len(data)):
                    path.write_bytes(data)
                    with self.assertRaises(ValueError):validate_profile(path)

if __name__ == '__main__':unittest.main()
