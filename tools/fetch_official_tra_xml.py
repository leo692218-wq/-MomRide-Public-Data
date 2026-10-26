#!/usr/bin/env python3
"""OFF-PHONE official TRA downloader for compact-feed publisher.

Downloads authentic daily XML onto an external build machine, then runs
build_compact_tra_feed.py. Never place original government XML in the APK.
A failed/incomplete official response never changes existing published data.
"""
import argparse
import datetime as dt
import json
import re
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
from build_compact_tra_feed import build, MAX_XML_BYTES

INDEX='https://ods.railway.gov.tw/tra-ods-web/ods/download/dataResource/railway_schedule/XML/list'
PATTERN=re.compile(r'''<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>\s*(\d{8}\.xml)\s*</a>''',re.I|re.S)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('official endpoint redirected; abort rather than follow unaudited source')

OPENER=urllib.request.build_opener(NoRedirect)

def official_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='ods.railway.gov.tw' or parsed.port is not None:
        return False
    if parsed.username or parsed.password or parsed.fragment:
        return False
    if not parsed.path.startswith('/tra-ods-web/ods/download/'):
        return False
    unescaped=urllib.parse.unquote(parsed.path)
    return ('..' not in unescaped.split('/') and '\\' not in unescaped and
            unescaped==parsed.path and '/./' not in parsed.path)

def get(url, maximum):
    if not official_url(url): raise ValueError('non-government URL rejected')
    request=urllib.request.Request(url,headers={'User-Agent':'MomRide compact timetable publisher/1.0'})
    with OPENER.open(request,timeout=35) as response:
        if response.status!=200: raise ValueError('unexpected government response '+str(response.status))
        content=response.read(maximum+1)
    if len(content)>maximum: raise ValueError('official document too large')
    return content

def run(output_dir, days=60, now=None):
    if days not in range(7,76): raise ValueError('days must be 7..75')
    today=now or dt.datetime.now(ZoneInfo('Asia/Taipei')).date()
    html=get(INDEX,2*1024*1024).decode('utf-8-sig',errors='replace')
    wanted={today+dt.timedelta(days=i) for i in range(days)}
    sources={}
    for href,label in PATTERN.findall(html):
        try: date=dt.datetime.strptime(label[:-4],'%Y%m%d').date()
        except ValueError: continue
        if date not in wanted: continue
        url=urllib.parse.urljoin(INDEX,href)
        if not official_url(url): continue
        # If official index offers distinct sources for same day, never pick arbitrarily.
        sources.setdefault(date,set()).add(url)
    if set(sources)!=wanted or any(len(x)!=1 for x in sources.values()):
        missing=sorted(str(x) for x in wanted-set(sources))
        collisions=sorted(str(x) for x,v in sources.items() if len(v)!=1)
        raise ValueError(f'incomplete/ambiguous official days: missing={missing[:8]}, conflicts={collisions[:8]}')
    with tempfile.TemporaryDirectory(prefix='momride-publisher-') as temp:
        source=Path(temp)/'xml'; source.mkdir()
        for date in sorted(wanted):
            (source/f'{date:%Y%m%d}.xml').write_bytes(get(next(iter(sources[date])),MAX_XML_BYTES))
        # Build in staging; only move to public-data repository after all files pass.
        staged=Path(temp)/'output'
        result=build(source,staged)
        dest=Path(output_dir); (dest/'releases').mkdir(parents=True,exist_ok=True)
        artifact=Path(result['pack']); final=dest/'releases'/artifact.name
        # Write immutable release first, publish latest pointer LAST.
        import shutil
        shutil.copy2(artifact,final)
        shutil.copy2(staged/'source-provenance.json',dest/'source-provenance.json')
        shutil.copy2(staged/'latest.tsv',dest/'latest.tsv')
        result['pack']=str(final)
        return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--days',type=int,default=60)
    args=p.parse_args()
    print(json.dumps(run(args.output_dir,args.days),ensure_ascii=False))