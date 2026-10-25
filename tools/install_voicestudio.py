"""Install the pinned original Electron release after two SHA256 checks.

Existing desktop installations are preserved. --install is required to run
the installer. This does not launch the app or fetch speech models.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serve.voicestudio import desktop_executable

VERSION='0.5.6'
ASSET='VoiceStudio-Electron-0.5.6-win-x64.exe'
BASE='https://github.com/debpalash/VoiceStudio/releases/download/v0.5.6/'
ASSET_SHA256='3d7ac1d6b54e7854ca7fff4dda838e402d1c5d31acc9656b1838432e29a97624'
SUMS_SHA256='cfa285ae25a86d325702b1930080aabfec805125cff6feb1ec362fb9df39888d'


def expected_checksum(text,asset):
    entries=re.findall(r'^([A-Fa-f0-9]{64})\s+'+re.escape(asset)+r'$',text,re.MULTILINE)
    if len(entries)!=1:raise ValueError('Missing, duplicate or invalid official checksum entry.')
    return entries[0].lower()


def sha256(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def download(path,url,expected):
    if path.is_file() and sha256(path)==expected:return
    partial=path.with_suffix(path.suffix+'.partial')
    with urllib.request.urlopen(url,timeout=60) as response,partial.open('wb') as target:
        while block:=response.read(1024*1024):target.write(block)
    if sha256(partial)!=expected:raise ValueError('Official release digest mismatch; installation refused.')
    partial.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true')
    args=parser.parse_args()
    if os.name!='nt':raise RuntimeError('This pinned installer is for Windows x64.')
    existing=desktop_executable()
    if existing:
        print(json.dumps({'installed':True,'existing_preserved':True,'executable':str(existing)}));return
    folder=ROOT/'tmp'/'voicestudio-install';folder.mkdir(parents=True,exist_ok=True)
    sums=folder/'SHA256SUMS.txt';package=folder/ASSET
    download(sums,BASE+'SHA256SUMS.txt',SUMS_SHA256)
    expected=expected_checksum(sums.read_text(encoding='utf-8'),ASSET)
    if expected!=ASSET_SHA256:raise ValueError('Release checksum differs from pinned GitHub asset digest.')
    download(package,BASE+ASSET,expected)
    result={'version':VERSION,'asset':ASSET,'sha256':sha256(package),'checksum_verified':True,'installed':False}
    if args.install:
        setup=subprocess.run([str(package),'/S'],check=False,timeout=300)
        if setup.returncode not in (0,3010):raise RuntimeError('VoiceStudio installer exit '+str(setup.returncode))
        executable=desktop_executable()
        if executable is None:raise RuntimeError('Installer exited successfully but desktop executable was not detected.')
        result.update(installed=True,installer_exit=setup.returncode,executable=str(executable))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
