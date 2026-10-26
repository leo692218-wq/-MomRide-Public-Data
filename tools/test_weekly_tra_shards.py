#!/usr/bin/env python3
"""Actual builder tests on synthetic input: NOT real trains and NEVER published."""
import datetime as dt
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import zipfile
from build_weekly_tra_shards import generate

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
with tempfile.TemporaryDirectory(prefix='tra-shard-tests-') as td:
    p=Path(td);src=p/'source';src.mkdir();out=p/'out'
    start=dt.date(2026,10,27);end=start+dt.timedelta(days=14)
    name=f'tra-{start:%Y%m%d}-{end:%Y%m%d}.zip'
    trips=[];stops=[]
    for d in range(15):
        today=start+dt.timedelta(days=d)
        for n in range(120):
            train=str(1000+n)
            trips.append(f'{today}\t{train}\t區間車\n')
            stops.append(f'{today}\t{train}\t1\t1000\t臺北\t\t08:00\n')
            stops.append(f'{today}\t{train}\t2\t3300\t臺中\t09:30\t09:31\n')
    with zipfile.ZipFile(src/name,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('trips.tsv',''.join(trips));z.writestr('stops.tsv',''.join(stops))
    mf=p/'latest.tsv'
    mf.write_text(f'MOMRIDE_TRA_V1\t{start}\t{end}\t{name}\t{(src/name).stat().st_size}\t{digest(src/name)}\t1800\t3600\n')
    # Old builder insists >=7days and this has 15 -> expect exactly 3 date shards.
    ret=generate(mf,src,out)
    assert ret['shards']==3 and ret['trips']==1800 and ret['stops']==3600
    items=(out/'latest-shards.tsv').read_text().strip().splitlines()
    assert len(items)==4 and items[0].split('\t')[0]=='MOMRIDE_TRA_SHARDS_V3'
    total=0
    for line in items[1:]:
        row=line.split('\t');assert len(row)==10
        shard=out/'releases'/row[3]
        assert len(shard.read_bytes())==int(row[4]) and digest(shard)==row[5]
        with zipfile.ZipFile(shard) as z:
            assert z.namelist()==['timetable.sqlite']
            dbp=p/'check.sqlite';dbp.write_bytes(z.read('timetable.sqlite'))
        assert dbp.stat().st_size==int(row[8]) and digest(dbp)==row[9]
        with sqlite3.connect(dbp) as db:
            assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            assert db.execute("SELECT meta_value FROM feed_meta WHERE meta_key='format'").fetchone()[0]=='MOMRIDE_TRA_SHARDS_V3'
            count=db.execute('SELECT count(*) FROM train_stop').fetchone()[0]
            assert count==int(row[7])
            total+=count
    assert total==3600
    print('PASS three verified shards, exact dates and real SQLite lookup schema (synthetic source only)')
    original=[(x.name,digest(x)) for x in sorted((out/'releases').glob('*.zip'))]
    again=generate(mf,src,out)
    assert original==[(x.name,digest(x)) for x in sorted((out/'releases').glob('*.zip'))]
    print('PASS deterministic SHA for every 7-day shard, no spurious phone refresh')
    bad=p/'tampered.tsv'
    bad.write_text(mf.read_text().replace('\t1800\t3600','\t1801\t3600'))
    try:generate(bad,src,p/'bad')
    except ValueError: pass
    else:raise AssertionError('tampered source count must fail')
    assert not (p/'bad'/'latest-shards.tsv').exists()
    print('PASS source counter mismatch does not release a partially valid manifest')
    print('TRA_SHARD_PUBLISHER_3_OF_3_PASS (synthetic only)')