#!/usr/bin/env python3
"""Convert verified daily TRA government XML to one tiny phone-readable TRA pack.

Runs on an EXTERNAL builder, never on the phone. No fake or substituted trains.
Example:
  python tools/build_compact_tra_feed.py --input-dir ./official_xml --output-dir ./data/tra
Only a publisher with authentic YYYYMMDD.xml may deploy the generated files.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

MAX_DAYS = 75
MAX_XML_BYTES = 80 * 1024 * 1024
MAX_PACK_BYTES = 16 * 1024 * 1024
MAX_TRIPS = 120000
MAX_STOPS = 2500000
CLEAN = re.compile(r"[\t\r\n]")
CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def tag(element):
    return element.tag.split('}')[-1].split(':')[-1].lower()


def child(node, name):
    return next((e for e in node if tag(e) == name.lower()), None)


def ctext(node, name):
    e = child(node, name)
    return ''.join(e.itertext()).strip() if e is not None else ''


def name_zh(node, name):
    e = child(node, name)
    if e is None:
        return ''
    return ctext(e, 'Zh_tw') or ''.join(e.itertext()).strip()


def safe(raw):
    return CLEAN.sub(' ', str(raw or '')).strip()[:80]


def clock(raw):
    match = CLOCK.match(str(raw).strip())
    if not match:
        return ''
    hour, minute, second = (int(match[1]), int(match[2]), int(match[3] or 0))
    if not (0 <= hour <= 47 and 0 <= minute <= 59 and 0 <= second <= 59):
        return ''
    return f'{hour:02d}:{minute:02d}'


def train_type(raw):
    v = safe(raw)
    if '3000' in v: return '自強3000'
    for label in ('太魯閣', '普悠瑪', '莒光', '區間快', '區間', '復興', '自強', '普快'):
        if label in v:
            return {'區間': '區間車', '莒光': '莒光號', '復興': '復興號', '自強': '自強號'}.get(label, label)
    if v in ('1101', '1102'): return '太魯閣'
    if v == '1107': return '普悠瑪'
    if v in ('110G','110H','110K','110M'): return '自強3000'
    if v == '1132': return '區間快'
    if v in ('1130','1131','1154'): return '區間車'
    if v.startswith('111'): return '莒光號'
    if v.startswith('112'): return '復興號'
    if v.startswith('110'): return '自強號'
    return v or '臺鐵'


def read_day(path):
    if path.stat().st_size > MAX_XML_BYTES:
        raise ValueError(f'official XML too large: {path.name}')
    # External entities are not resolved by ElementTree; explicit DTD refusal.
    with path.open('rb') as fh:
        prefix = fh.read(8192).upper()
    if b'<!DOCTYPE' in prefix or b'<!ENTITY' in prefix:
        raise ValueError('unexpected DTD/ENTITY')
    root = ET.parse(path).getroot()
    trips = {}
    for node in root.iter():
        # Native TRA TrainInfo/TimeInfo attribute format.
        if tag(node) == 'traininfo' and node.attrib.get('Train'):
            no = safe(node.attrib.get('Train'))
            times = []
            for stop in node.iter():
                if tag(stop) != 'timeinfo': continue
                code = safe(stop.attrib.get('Station'))
                try: seq = int(stop.attrib.get('Order', '0'))
                except ValueError: continue
                if code and seq > 0:
                    name = safe(stop.attrib.get('StationName') or stop.attrib.get('StationNameZh') or code)
                    times.append((seq, code, name, clock(stop.attrib.get('ARRTime','')),
                                  clock(stop.attrib.get('DEPTime') or stop.attrib.get('DEPTTime') or '')))
            if no and times:
                trips[no] = (train_type(node.attrib.get('CarClass','')), times)
        # Element style (TrainNo and individual StopTime children).
        info = child(node, 'TrainInfo') or child(node, 'DailyTrainInfo')
        if info is None: continue
        no = safe(ctext(info,'TrainNo'))
        if not no: continue
        stop_times = [x for x in node.iter() if tag(x) in ('stoptime','railstoptime')]
        if not stop_times: continue
        times = []
        for stop in stop_times:
            code = safe(ctext(stop,'StationID'))
            try: seq = int(ctext(stop,'StopSequence'))
            except ValueError: continue
            if code and seq > 0:
                times.append((seq, code, safe(name_zh(stop,'StationName') or code),
                              clock(ctext(stop,'ArrivalTime')),clock(ctext(stop,'DepartureTime'))))
        if times:
            clazz = next((ctext(info,k) or name_zh(info,k) for k in (
                'TrainTypeName','TrainClassificationName','TrainTypeName_Zh_tw',
                'TrainClassificationName_Zh_tw','TrainType','CarClass','TrainClassificationID')
                if ctext(info,k) or name_zh(info,k)), '')
            trips[no] = (train_type(clazz), times)
    result = {}
    for no, (clazz, stops) in trips.items():
        unique = sorted(dict((s[0],s) for s in stops).values())
        if not any(a[1]!=b[1] and a[4] and b[3] and b[3]>a[4]
                   for i,a in enumerate(unique) for b in unique[i+1:]):
            continue
        result[no] = (clazz, unique)
    return result


def build(source_dir, dest_dir, minimum=100):
    files = sorted(Path(source_dir).glob('????????.xml'))
    if not (7 <= len(files) <= MAX_DAYS):
        raise ValueError('need 7–75 authoritative consecutive dated XML files')
    dates = [dt.datetime.strptime(x.stem,'%Y%m%d').date() for x in files]
    if any(d != dates[0]+dt.timedelta(days=i) for i,d in enumerate(dates)):
        raise ValueError('missing or repeated daily XML')
    dest = Path(dest_dir); releases=dest/'releases'; releases.mkdir(parents=True, exist_ok=True)
    counts=[]; source_hashes=[]
    with tempfile.TemporaryDirectory() as tmp:
        trip_file=Path(tmp)/'trips.tsv'; stop_file=Path(tmp)/'stops.tsv'
        with trip_file.open('w',encoding='utf-8',newline='\n') as ft, \
             stop_file.open('w',encoding='utf-8',newline='\n') as fs:
            for day, f in zip(dates, files):
                trips=read_day(f)
                stopcount=sum(len(x[1]) for x in trips.values())
                if len(trips)<minimum or stopcount<minimum*2:
                    raise ValueError(f'incomplete official service day {day}: {len(trips)} trains')
                for no, (clazz, stops) in sorted(trips.items()):
                    ft.write('\t'.join((str(day),no,clazz))+'\n')
                    for seq,code,name,arr,dep in stops:
                        fs.write('\t'.join((str(day),no,str(seq),code,name,arr,dep))+'\n')
                counts.append((len(trips),stopcount))
                source_hashes.append({'date':str(day),'file':f.name,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),
                                      'trips':len(trips),'stops':stopcount})
        nt=sum(x[0] for x in counts); ns=sum(x[1] for x in counts)
        if nt>MAX_TRIPS or ns>MAX_STOPS:
            raise ValueError('record limits exceeded')
        name=f"tra-{dates[0]:%Y%m%d}-{dates[-1]:%Y%m%d}.zip"
        archive=releases/name
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            z.write(trip_file,'trips.tsv'); z.write(stop_file,'stops.tsv')
    size=archive.stat().st_size
    if size>MAX_PACK_BYTES:
        archive.unlink()
        raise ValueError('compact pack exceeds phone 16 MiB limit; must split on publisher')
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (dest/'latest.tsv').write_text('\t'.join(('MOMRIDE_TRA_V1',str(dates[0]),str(dates[-1]),name,
                                            str(size),digest,str(nt),str(ns)))+'\n',encoding='utf-8')
    (dest/'source-provenance.json').write_text(json.dumps({'format':'MOMRIDE_TRA_V1',
          'origin':'Taiwan Railways official daily XML', 'source_files':source_hashes,
          'pack_sha256':digest,'pack_bytes':size},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {'pack':str(archive),'start':str(dates[0]),'end':str(dates[-1]),'trips':nt,'stops':ns,
            'pack_bytes':size,'sha256':digest}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir',required=True)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--min-trains-per-day',type=int,default=100,help='publisher integrity gate (100 by default)')
    a=p.parse_args()
    print(json.dumps(build(a.input_dir,a.output_dir,a.min_trains_per_day),ensure_ascii=False))