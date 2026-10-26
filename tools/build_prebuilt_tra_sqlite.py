#!/usr/bin/env python3
"""OFF-PHONE: convert a SHA-verified published TRA V1 TSV pack into ready-to-query SQLite.

No official timetable files or 1.2M-row inserts are processed on the user's phone.
Only independently audited actual V1 releases are allowed for real publishing.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

MAX_PACK = 24 * 1024 * 1024
MAX_DB = 160 * 1024 * 1024
RELEASE = re.compile(r'tra-\d{8}-\d{8}\.zip')
V1 = 'MOMRIDE_TRA_V1'
V2 = 'MOMRIDE_TRA_SQLITE_V2'


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for b in iter(lambda: stream.read(128 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def load_manifest(meta):
    parts = Path(meta).read_text('utf-8').strip().split('\t')
    if len(parts) != 8 or parts[0] != V1 or not RELEASE.fullmatch(parts[3]):
        raise ValueError('Invalid official-derived V1 manifest')
    start, end = dt.date.fromisoformat(parts[1]), dt.date.fromisoformat(parts[2])
    if (end - start).days not in range(6, 75) or parts[3] != f'tra-{start:%Y%m%d}-{end:%Y%m%d}.zip':
        raise ValueError('Invalid V1 service date range')
    size, trips, stops = int(parts[4]), int(parts[6]), int(parts[7])
    if not (0 < size <= 16 * 1024 * 1024 and 0 < trips <= 120000 and 1 < stops <= 2500000 and
            re.fullmatch(r'[0-9a-f]{64}', parts[5])):
        raise ValueError('Invalid V1 publication counts')
    return start, end, parts[3], size, parts[5], trips, stops


def write_from_v1(manifest_path, release_dir, output_dir):
    start, end, filename, size, digest, expected_trips, expected_stops = load_manifest(manifest_path)
    source = Path(release_dir) / filename
    if source.stat().st_size != size or sha256(source) != digest:
        raise ValueError('V1 ZIP bytes or SHA mismatch; refuse derived publication')
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='momride-prebuilt-') as tmp:
        db_path = Path(tmp) / 'timetable.sqlite'
        db = sqlite3.connect(db_path)
        db.executescript('''
            PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=NORMAL;
            CREATE TABLE train_trip(travel_date TEXT NOT NULL,train_no TEXT NOT NULL,train_type TEXT NOT NULL,
              PRIMARY KEY(travel_date,train_no));
            CREATE TABLE train_stop(travel_date TEXT NOT NULL,train_no TEXT NOT NULL,stop_seq INTEGER NOT NULL,
              station_id TEXT NOT NULL,station_name TEXT NOT NULL,arrival_time TEXT NOT NULL,
              departure_time TEXT NOT NULL,PRIMARY KEY(travel_date,train_no,stop_seq));
            CREATE TABLE feed_meta(meta_key TEXT PRIMARY KEY,meta_value TEXT NOT NULL);
        ''')
        trip_count = stop_count = 0
        dates = {}
        with zipfile.ZipFile(source) as z:
            if sorted(z.namelist()) != ['stops.tsv', 'trips.tsv']:
                raise ValueError('Unrecognized V1 archive structure')
            for filename, n in (('trips.tsv', 3), ('stops.tsv', 7)):
                with z.open(filename) as stream:
                    batch = []
                    for raw in stream:
                        if len(raw) > 1200:
                            raise ValueError('Oversized V1 line')
                        fields = raw.decode('utf-8').rstrip('\r\n').split('\t')
                        if len(fields) != n:
                            raise ValueError('Invalid V1 row')
                        day = dt.date.fromisoformat(fields[0])
                        if not start <= day <= end:
                            raise ValueError('Service day outside signed V1 manifest')
                        if n == 3:
                            if not (fields[1] and fields[2]):
                                raise ValueError('Empty train ID/type')
                            trip_count += 1
                            dates.setdefault(fields[0], [0, 0])[0] += 1
                            batch.append(tuple(fields))
                        else:
                            if not (fields[1] and fields[3] and fields[4] and fields[2].isdigit() and
                                    int(fields[2]) > 0):
                                raise ValueError('Malformed station evidence')
                            stop_count += 1
                            dates.setdefault(fields[0], [0, 0])[1] += 1
                            batch.append((fields[0],fields[1],int(fields[2]),*fields[3:]))
                        if len(batch) >= 10000:
                            if n == 3:
                                db.executemany('INSERT INTO train_trip VALUES(?,?,?)',batch)
                            else:
                                db.executemany('INSERT INTO train_stop VALUES(?,?,?,?,?,?,?)',batch)
                            batch.clear()
                    if batch:
                        db.executemany('INSERT INTO train_trip VALUES(?,?,?)' if n==3 else
                          'INSERT INTO train_stop VALUES(?,?,?,?,?,?,?)', batch)
        if trip_count != expected_trips or stop_count != expected_stops:
            raise ValueError('Publisher trips/stops count mismatch')
        if len(dates) != (end - start).days + 1 or any(v[0]<100 or v[1]<200 for v in dates.values()):
            raise ValueError('Missing/partial official service day')
        for day in sorted(dates):
            known = db.execute('''SELECT 1 FROM train_stop a JOIN train_stop b
                    ON a.travel_date=b.travel_date AND a.train_no=b.train_no
                    AND b.stop_seq>a.stop_seq AND a.station_id<>b.station_id
                    WHERE a.travel_date=? AND a.departure_time<>'' AND b.arrival_time<>''
                    AND b.arrival_time>a.departure_time LIMIT 1''', (day,)).fetchone()
            if not known:
                raise ValueError('No boardable same-train pair on '+day)
        db.executescript('''
            CREATE INDEX idx_train_stop_lookup ON train_stop(travel_date,station_name,departure_time);
            CREATE INDEX idx_train_stop_stationid ON train_stop(travel_date,station_id,departure_time);
        ''')
        for k,v in [('format',V2),('start',str(start)),('end',str(end)),
                    ('trips',str(trip_count)),('stops',str(stop_count)),('source_sha256',digest)]:
            db.execute('INSERT INTO feed_meta VALUES(?,?)',(k,v))
        db.commit()
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Prebuilt SQLite physical integrity failure')
        db.close()
        if db_path.stat().st_size > MAX_DB:
            raise ValueError('Prebuilt SQLite too large for mobile')
        dest_name = f'tra-sqlite-{start:%Y%m%d}-{end:%Y%m%d}.zip'
        archive = target / dest_name
        with zipfile.ZipFile(archive,'w') as z:
            item = zipfile.ZipInfo('timetable.sqlite', date_time=(1980,1,1,0,0,0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item._compresslevel = 9
            with z.open(item,'w') as out, db_path.open('rb') as inp:
                shutil.copyfileobj(inp,out,128*1024)
        if archive.stat().st_size > MAX_PACK:
            archive.unlink()
            raise ValueError('Prebuilt ZIP beyond phone 24 MiB limit')
        fields=[V2,str(start),str(end),dest_name,str(archive.stat().st_size),sha256(archive),
                str(trip_count),str(stop_count),str(db_path.stat().st_size),sha256(db_path)]
        (target / 'latest-sqlite.tsv').write_text('\t'.join(fields)+'\n',encoding='utf-8')
        return {'zip':str(archive),'bytes':archive.stat().st_size,'trips':trip_count,'stops':stop_count,
                'sqlite_bytes':int(fields[-2]),'sha256':fields[5],'db_sha256':fields[-1]}

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',required=True)
    p.add_argument('--release-dir',required=True)
    p.add_argument('--output-dir',required=True)
    a=p.parse_args()
    print(json.dumps(write_from_v1(a.manifest,a.release_dir,a.output_dir),ensure_ascii=False))