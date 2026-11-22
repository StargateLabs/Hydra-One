"""Wait for the owned dashboard to exit before restoring its exact launch command."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pid',type=int,required=True);parser.add_argument('--root',type=Path,required=True);parser.add_argument('command',nargs=argparse.REMAINDER);args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    from serve.update_restart import restart_command,clear_restart_pending
    restart_command(command,next((command[i+1] for i,v in enumerate(command[:-1]) if v=='--port'),8090))
    import psutil
    try:psutil.Process(args.pid).wait(timeout=45)
    except psutil.NoSuchProcess:pass
    except psutil.TimeoutExpired:raise RuntimeError('Original dashboard still running; duplicate start prevented')
    try:
        selected=json.loads((args.root/'data/dashboard-python-selection.json').read_text(encoding='utf-8')).get('active')
        if selected and Path(selected).is_file():command[0]=selected
    except (OSError,ValueError):pass
    log=args.root/'output/verification/automatic-restart.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('ab') as output:
        subprocess.Popen(command,cwd=args.root,stdin=subprocess.DEVNULL,stdout=output,stderr=output,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
    clear_restart_pending(args.root)
if __name__=='__main__':main()
