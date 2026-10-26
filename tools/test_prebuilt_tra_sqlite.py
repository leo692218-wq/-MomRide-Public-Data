#!/usr/bin/env python3
"""Strictly synthetic publisher unit test; never publish fixtures as official timetables."""
import datetime as dt
import hashlib
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from build_prebuilt_tra_sqlite import write_from_v1

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
with tempfile.TemporaryDirectory() as td:
    root=Path(td);source=root/'source';source.mkdir();out=root/'published'
    start=dt.date(2026,10,27);end=start+dt.timedelta(days=6)
    name=f'tra-{start:%Y%m%d}-{end:%Y%m%d}.zip'
    trips=[];stops=[]
    for d in range(7):
        day=str(start+dt.timedelta(days=d))
        for n in range(100):
            no=str(n+1000)
            trips.append(f'{day}\t{no}\t區間車\n')
            stops.append(f'{day}\t{no}\t1\t1000\t臺北\t\t08:00\n')
            stops.append(f'{day}\t{no}\t2\t3300\t臺中\t09:30\t09:31\n')
    with zipfile.ZipFile(source/name,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('trips.tsv',''.join(trips));z.writestr('stops.tsv',''.join(stops))
    mf=root/'latest.tsv'
    mf.write_text(f'MOMRIDE_TRA_V1\t{start}\t{end}\t{name}\t{(source/name).stat().st_size}\t{sha(source/name)}\t700\t1400\n')
    result=write_from_v1(mf,source,out)
    assert Path(result['zip']).parent == out/'releases', 'must publish at URL used by Android'
    with zipfile.ZipFile(result['zip']) as z:
        assert z.namelist()==['timetable.sqlite']
        db_path=root/'from_package.sqlite';db_path.write_bytes(z.read('timetable.sqlite'))
    assert db_path.stat().st_size==result['sqlite_bytes']
    assert sha(db_path)==result['db_sha256']
    con=sqlite3.connect(db_path)
    assert con.execute('SELECT count(*) FROM train_trip').fetchone()[0]==700
    assert con.execute('SELECT count(*) FROM train_stop').fetchone()[0]==1400
    assert con.execute("SELECT meta_value FROM feed_meta WHERE meta_key='format'").fetchone()[0]=='MOMRIDE_TRA_SQLITE_V2'
    assert con.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    assert con.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('idx_train_stop_lookup','idx_train_stop_stationid')").fetchone()[0]==2
    con.close()
    print('PASS off-phone builder creates pre-indexed SQLite with 700 trips, 1400 stops, provenance and exact checksums')
    r2=write_from_v1(mf,source,out)
    assert result['sha256']==r2['sha256']
    print('PASS deterministic ZIP checksum on repeat build, no unnecessary re-download')
    bad=root/'tampered.tsv';bad.write_text(mf.read_text().replace('\t700\t1400','\t701\t1400'))
    try:write_from_v1(bad,source,out)
    except ValueError:print('PASS forged trip count refused')
    else:raise AssertionError('must reject fake trip count')
    with (source/name).open('ab') as f:f.write(b'corrupt')
    try:write_from_v1(mf,source,out)
    except ValueError:print('PASS corrupt original public V1 ZIP rejected by SHA/bytes')
    else:raise AssertionError('must reject corrupt archive')
    print('PREBUILT_TRA_SQLITE_PUBLISHER_4_OF_4_PASS (synthetic-only)')