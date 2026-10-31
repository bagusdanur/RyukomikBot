"""Private, expiring RAW export preparation; one bounded join at a time."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import shutil
import time
import zipfile
from PIL import Image
from fastapi import HTTPException
from .raw_join import prepare_inputs

CACHE = Path(os.getenv('RAW_EXPORT_CACHE', 'data/raw-download-cache')).resolve()
TTL = 1800
LOCK = asyncio.Lock()
TASKS = set()
IMAGE_SUFFIXES = {'.png','.jpg','.jpeg','.webp','.avif'}

def write_state(root, state):
    temp = root/'state.new'
    temp.write_text(json.dumps(state))
    temp.replace(root/'state.json')

def cleanup():
    CACHE.mkdir(parents=True, exist_ok=True)
    for root in CACHE.iterdir():
        if not root.is_dir() or root.is_symlink() or not re.fullmatch(r'[a-f0-9]{32}', root.name):
            continue
        state_path=root/'state.json'
        if state_path.exists() and time.time()-json.loads(state_path.read_text()).get('created_at',state_path.stat().st_mtime) > TTL:
            shutil.rmtree(root)

def read_state(token, owner):
    if not re.fullmatch(r'[a-f0-9]{32}', str(token)):
        raise HTTPException(404, 'Paket RAW tidak ditemukan.')
    root=CACHE/token
    try:
        state=json.loads((root/'state.json').read_text())
    except (OSError, ValueError):
        raise HTTPException(404, 'Paket RAW tidak ditemukan atau sudah kedaluwarsa.')
    if state['owner'] != str(owner) or time.time()-state['created_at'] > TTL:
        raise HTTPException(404, 'Paket RAW tidak ditemukan atau sudah kedaluwarsa.')
    if state['state'] in {'QUEUED','DOWNLOADING','JOINING'} and state.get('process_id') != os.getpid():
        state['state']='FAILED'
        state['error']='Persiapan terhenti karena server direstart. Siapkan ulang paket RAW.'
        write_state(root,state)
    return root,state

def public_state(state):
    return {k:v for k,v in state.items() if k not in {'owner','created_at','payload','process_id'}}

def describe(paths):
    pages=[]
    for index,p in enumerate(paths,1):
        with Image.open(p) as im:
            im.verify()
        with Image.open(p) as im:
            pages.append({'page':index,'width':im.width,'height':im.height})
    return {'count':len(pages),'pages':pages,'min_height':min(p['height'] for p in pages),
            'max_height':max(p['height'] for p in pages)}

def archive(paths, destination):
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_STORED) as z:
        for index,p in enumerate(paths,1):
            z.write(p,f'{index:03d}{p.suffix.lower()}')

def join_package(paths, root, original):
    # Reserve disk for OCR and cap wide-page memory rather than resize the raw.
    estimate=sum(p['width']*p['height']*4 for p in original['pages'])
    if shutil.disk_usage(CACHE).free < 1024**3 + estimate:
        raise ValueError('Ruang disk belum cukup untuk gabungan RAW. Pilih Original atau coba lagi nanti.')
    meminfo=Path('/proc/meminfo')
    if meminfo.exists():
        available=int(re.search(r'MemAvailable:\s+(\d+)',meminfo.read_text()).group(1))*1024
        if available < 1200*1024**2:
            raise ValueError('RAM sedang dipakai proses lain. Original tetap tersedia; coba Gabungan lagi nanti.')
    cap=min(15000,24_000_000//max(p['width'] for p in original['pages']))
    if cap < 1000:
        raise ValueError('Raw terlalu lebar untuk gabungan WebP; gunakan Original.')
    # The join runs in a child process: its canvas + lossless WebP encoder can
    # need several hundred MB, and an in-process spike used to restart uvicorn
    # (PM2 max_memory_restart) which surfaced as nginx 502 to the dashboard.
    paths_json=root/'join-paths.json'
    paths_json.write_text(json.dumps([str(p) for p in paths]))
    project=Path(__file__).resolve().parents[1]
    command=[sys.executable,'-m','backend.join_worker','--paths-json',str(paths_json),
             '--directory',str(root/'joined'),'--max-height',str(cap)]
    try:
        completed=subprocess.run(command,cwd=str(project),capture_output=True,text=True,timeout=1800)
    except subprocess.TimeoutExpired as error:
        raise ValueError('Penggabungan RAW terlalu lama. Pilih Original atau coba lagi.') from error
    if completed.returncode != 0:
        detail=(completed.stderr or completed.stdout or '').strip().splitlines()
        raise ValueError('Gagal menggabungkan RAW: '+(detail[-1][:200] if detail else f'exit {completed.returncode}'))
    result=sorted((root/'joined').glob('joined-*.webp'))
    if not result:
        raise ValueError('Penggabungan RAW tidak menghasilkan halaman.')
    summary=describe(result)
    manifest=json.loads((root/'joined/manifest.json').read_text())
    summary['height_limit']=cap
    summary['source_boundary_cuts']=sum(p['cut']=='NO_SAFE_GUTTER_SOURCE_BOUNDARY' for p in manifest['pages'])
    summary['unsafe_cuts']=sum(p['cut']=='NO_SAFE_GUTTER' for p in manifest['pages'])
    archive(result,root/'joined.zip')
    summary['bytes']=(root/'joined.zip').stat().st_size
    return summary

async def build(root, state, downloader):
    async with LOCK:
        try:
            state['state']='DOWNLOADING';write_state(root,state)
            if shutil.disk_usage(CACHE).free < 1536*1024**2:
                raise ValueError('Ruang disk belum cukup untuk menyiapkan RAW.')
            p=state['payload']
            folder=await asyncio.wait_for(downloader.download_chapter(p['manga_id'],p['chapter_id'],str(root/'source')),300)
            if not folder:
                raise ValueError('Source tidak mengembalikan gambar chapter.')
            if root.resolve() not in Path(folder).resolve().parents:
                raise ValueError('Folder hasil downloader berada di luar paket RAW.')
            paths=sorted(p for p in Path(folder).rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
            if not paths:
                raise ValueError('Tidak ditemukan gambar RAW yang didukung (PNG, JPG, WebP, AVIF).')
            if len(paths)>300:
                raise ValueError(f'Jumlah gambar RAW {len(paths)} melebihi maksimum 300.')
            state['original']=await asyncio.to_thread(describe,paths)
            await asyncio.to_thread(archive,paths,root/'original.zip')
            state['original']['bytes']=(root/'original.zip').stat().st_size
            if str(p.get('mode') or '').lower()=='original':
                # API memakai file asli: tidak perlu join WebP sama sekali.
                state['state']='READY'
                shutil.rmtree(root/'source',ignore_errors=True)
                write_state(root,state)
                return
            state['state']='JOINING';write_state(root,state)
            state['joined']=await asyncio.to_thread(join_package,paths,root,state['original'])
            state['state']='READY'
            # ZIPs contain the same data; do not retain duplicate raster caches.
            shutil.copy2(root/'joined/manifest.json',root/'join-manifest.json')
            shutil.rmtree(root/'joined')
            shutil.rmtree(root/'source')
        except Exception as exc:
            state['state']='FAILED';state['error']=str(exc)[:500]
        write_state(root,state)

def start(payload, owner, downloader):
    cleanup()
    for root in CACHE.iterdir():
        if root.is_dir() and (root/'state.json').exists():
            if json.loads((root/'state.json').read_text()).get('owner') != str(owner):
                continue
            try:
                _,state=read_state(root.name,owner)
            except HTTPException:
                continue
            if state['owner']==str(owner) and state['payload']==payload and state['state']!='FAILED' and time.time()-state['created_at']<TTL:
                return public_state(state)
    if len(TASKS)>=2:
        raise HTTPException(429,'Dua paket RAW sedang disiapkan. Tunggu salah satunya selesai.')
    token=secrets.token_hex(16);root=CACHE/token;root.mkdir()
    state={'token':token,'owner':str(owner),'created_at':time.time(),'process_id':os.getpid(),'payload':payload,'state':'QUEUED','height_limit':15000}
    write_state(root,state)
    task=asyncio.create_task(build(root,state,downloader));TASKS.add(task);task.add_done_callback(TASKS.discard)
    return public_state(state)

def download_path(token, owner, mode):
    if mode not in {'original','joined'}:
        raise HTTPException(400,'Pilihan RAW harus Original atau Gabungan WebP.')
    root,state=read_state(token,owner)
    path=root/f'{mode}.zip'
    if mode not in state or not path.exists():
        raise HTTPException(409,'Paket RAW masih disiapkan. Tunggu sampai ukuran halaman muncul.')
    return path,state

def filename(state, mode):
    payload=state['payload']
    def safe(value):return re.sub(r'[^a-zA-Z0-9._-]+','-',str(value)).strip('-.')[:80] or 'raw'
    return f"{safe(payload['source'])}-{safe(payload['manga_id'])}-{safe(payload['chapter_id'])}-{mode}.zip"

if __name__ == '__main__':
    cleanup()
