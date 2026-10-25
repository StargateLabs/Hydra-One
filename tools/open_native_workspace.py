"""Open the existing LocalAI dashboard inside its managed Windows workspace."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serve.native_workspace import NativeWorkspace
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8090);parser.add_argument('--kind',choices=('dashboard','claude','antigravity'),default='dashboard')
    args=parser.parse_args()
    if not 1<=args.port<65536:raise ValueError('Invalid LocalAI port')
    NativeWorkspace(Path(__file__).resolve().parents[1],f'http://127.0.0.1:{args.port}').open(args.kind)
