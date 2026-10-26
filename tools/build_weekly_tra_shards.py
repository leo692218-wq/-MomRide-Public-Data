#!/usr/bin/env python3
"""Off-device verified 7-day indexed SQLite shards from an existing official V1 ZIP.

Phone never downloads XML or inserts raw timetable rows. Output is not published
until EVERY shard is verified and the final manifest is atomically written.
"""
import argparse
import datetime as dt
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile
from build_prebuilt_tra_sqlite import load_manifest, sha256

MAGIC = 'MOMRIDE_TRA_SHARDS_V3'
MAX_SHARD_ZIP = 8 * 1024 * 1024
MAX_SHARD_DB = 36 * 1024 * 1024

def generate(manifest_path, release_dir, output_dir):
    start, end, name, expected_bytes, expected_sha, total_trips, total_stops = load_manifest(manifest_path)
    source = Path(release_dir) / name
    if source.stat().st_size != expected_bytes or sha256(source) != expected_sha:
        raise ValueError('Original official V1 ZIP checksum mismatch')
    windows = []
    day = start
    while day <= end:
        last = min(day + dt.timedelta(days=6), end)
        windows.append((day,last))
        day = last + dt.timedelta(days=1)
    if not 1 <= len(windows) <= 11:
        raise ValueError('Invalid shard count')
    dest = Path(output_dir); dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='momride-offphone-') as td:
        base=Path(td)
        conns=[]; dbpaths=[]
        for i,(first,last) in enumerate(windows):
            p=base/f'chunk_{i:02d}.sqlite'
            db=sqlite3.connect(p)
            db.executescript('''
              PRAGMA journal_mode=DELETE;
              PRAGMA synchronous=NORMAL;
              CREATE TABLE train_trip(travel_date TEXT NOT NULL,train_no TEXT NOT NULL,
                train_type TEXT NOT NULL,PRIMARY KEY(travel_date,train_no));
              CREATE TABLE train_stop(travel_date TEXT NOT NULL,train_no TEXT NOT NULL,
                stop_seq INTEGER NOT NULL, station_id TEXT NOT NULL,
                station_name TEXT NOT NULL,arrival_time TEXT NOT NULL,
                departure_time TEXT NOT NULL,PRIMARY KEY(travel_date,train_no,stop_seq));
              CREATE TABLE feed_meta(meta_key TEXT PRIMARY KEY,meta_value TEXT NOT NULL);
            ''')
            dbpaths.append(p);conns.append(db)
        counts=[[0,0] for _ in windows]; by_day={}
        try:
            with zipfile.ZipFile(source) as z:
                if sorted(z.namelist()) != ['stops.tsv','trips.tsv']:
                    raise ValueError('Unknown official V1 layout')
                for member,fields,sql,index in [
                    ('trips.tsv',3,'INSERT INTO train_trip VALUES (?,?,?)',0),
                    ('stops.tsv',7,'INSERT INTO train_stop VALUES (?,?,?,?,?,?,?)',1)]:
                    buffers=[[] for _ in windows]
                    with z.open(member) as fh:
                        for raw in fh:
                            if len(raw)>1200: raise ValueError('Invalid source line size')
                            values=raw.decode('utf-8').rstrip('\r\n').split('\t')
                            if len(values)!=fields: raise ValueError('Malformed official source row')
                            service_day=dt.date.fromisoformat(values[0])
                            delta=(service_day-start).days
                            if delta<0 or service_day>end: raise ValueError('Out-of-range official date')
                            shard=delta//7
                            first,last=windows[shard]
                            if not first<=service_day<=last: raise ValueError('Noncontinuous shard date')
                            if not values[1] or (fields==7 and (not values[3] or not values[4] or
                                                        not values[2].isdigit() or int(values[2])<1)):
                                raise ValueError('Malformed official train/stop')
                            counts[shard][index]+=1
                            by_day.setdefault(values[0],[0,0])[index]+=1
                            if fields==7: values[2]=int(values[2])
                            buffers[shard].append(tuple(values))
                            if len(buffers[shard])>=4000:
                                conns[shard].executemany(sql,buffers[shard]);buffers[shard].clear()
                    for i,buf in enumerate(buffers):
                        if buf: conns[i].executemany(sql,buf)
            if sum(x[0] for x in counts)!=total_trips or sum(x[1] for x in counts)!=total_stops:
                raise ValueError('Official total count mismatch')
            if len(by_day)!=(end-start).days+1 or any(a<100 or b<200 for a,b in by_day.values()):
                raise ValueError('Missing/incomplete genuine service day')
            rows=[]
            for i,(first,last) in enumerate(windows):
                db=conns[i]
                for dayidx in range((last-first).days+1):
                    d=str(first+dt.timedelta(days=dayidx))
                    if db.execute('''SELECT 1 FROM train_stop a JOIN train_stop b
                        ON a.travel_date=b.travel_date AND a.train_no=b.train_no
                        AND b.stop_seq>a.stop_seq AND a.station_id<>b.station_id
                        WHERE a.travel_date=? AND a.departure_time<>'' AND b.arrival_time<>''
                        AND b.arrival_time>a.departure_time LIMIT 1''',(d,)).fetchone() is None:
                        raise ValueError('No boardable official same-train pair for '+d)
                db.executescript('''
                    CREATE INDEX idx_train_stop_lookup ON train_stop(travel_date,station_name,departure_time);
                    CREATE INDEX idx_train_stop_stationid ON train_stop(travel_date,station_id,departure_time);
                ''')
                for k,v in [('format',MAGIC),('start',str(first)),('end',str(last)),
                      ('trips',str(counts[i][0])),('stops',str(counts[i][1])),
                      ('source_sha256',expected_sha)]:
                    db.execute('INSERT INTO feed_meta VALUES (?,?)',(k,v))
                db.commit()
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                    raise ValueError('Shard database corruption')
                db.execute('ANALYZE');db.commit();db.execute('VACUUM');db.close()
                dbbytes=dbpaths[i].stat().st_size
                if dbbytes>MAX_SHARD_DB: raise ValueError(f'Shard exceeds {MAX_SHARD_DB} bytes')
                filename=f'tra-shard-{first:%Y%m%d}-{last:%Y%m%d}.zip'
                zip_path=base/filename
                with zipfile.ZipFile(zip_path,'w') as output:
                    zi=zipfile.ZipInfo('timetable.sqlite',date_time=(1980,1,1,0,0,0))
                    zi.compress_type=zipfile.ZIP_DEFLATED
                    zi._compresslevel=9
                    with output.open(zi,'w') as sink,dbpaths[i].open('rb') as inp:
                        shutil.copyfileobj(inp,sink,128*1024)
                zipbytes=zip_path.stat().st_size
                if zipbytes>MAX_SHARD_ZIP: raise ValueError('Shard ZIP too large')
                rows.append(('shard',str(first),str(last),filename,str(zipbytes),sha256(zip_path),
                             str(counts[i][0]),str(counts[i][1]),str(dbbytes),sha256(dbpaths[i])))
            # Only after all checks succeed: copy shard files, then publish index LAST.
            release=dest/'releases';release.mkdir(parents=True,exist_ok=True)
            for r in rows:
                shutil.copyfile(base/r[3],release/r[3])
            header='\t'.join((MAGIC,str(start),str(end),expected_sha,str(len(rows))))
            manifest='\n'.join([header]+['\t'.join(row) for row in rows])+'\n'
            tmp=dest/'latest-shards.tsv.new'
            tmp.write_text(manifest,encoding='utf-8')
            os.replace(tmp,dest/'latest-shards.tsv')
            return {'start':str(start),'end':str(end),'shards':len(rows),
                    'compressed_bytes':sum(int(x[4]) for x in rows),
                    'database_bytes':sum(int(x[8]) for x in rows),
                    'max_shard_zip':max(int(x[4]) for x in rows),
                    'max_shard_db':max(int(x[8]) for x in rows),'trips':total_trips,'stops':total_stops}
        finally:
            for db in conns:
                try:db.close()
                except sqlite3.Error:pass

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--release-dir',required=True)
    parser.add_argument('--output-dir',required=True)
    p=parser.parse_args()
    import json
    print(json.dumps(generate(p.manifest,p.release_dir,p.output_dir),ensure_ascii=False))