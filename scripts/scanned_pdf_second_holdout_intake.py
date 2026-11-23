"""Register newly downloaded sources; never execute recognition or extract text values."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess

from src.scanned_pdf_experiment.holdout_intake import digest

ROOT=Path(__file__).resolve().parents[1]
POPPLER=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/poppler/bin'
AG='https://www2.census.gov/library/publications/decennial/1940/agriculture/'
POP='https://www2.census.gov/library/publications/decennial/1950/population-volume-2/'
FILES=[(AG,f'1940-census-agriculture-vol-1-{state}.pdf') for state in ('rhode-island','utah','vermont','washington')]+[(POP,f) for f in ('02466750v2p40ch1.pdf','06586136v2p33ch1.pdf','11027772v2p43ch1.pdf','21983999v2p1ch1.pdf')]


def main():
    parent=ROOT/'artifacts/scanned-pdf-experiment'; out=parent/'prospective-holdout-20261122'; out.mkdir(exist_ok=False)
    source=out/'source';source.mkdir()
    seen={digest(p) for folder in (parent/'public-pilot-20261122/source',parent/'public-holdout-20261122/source') for p in folder.glob('*.pdf')}
    def inspect(item):
        n,(url,name)=item; src=Path.home()/'Downloads'/name; dst=source/name
        shutil.copyfile(src,dst); h=digest(dst)
        if h!=digest(src):raise ValueError('Copy mismatch')
        text=subprocess.check_output([str(POPPLER/'pdftotext'),str(dst),'-'],text=True)
        pages=text.split('\f')[:-1]; zero=[i+1 for i,t in enumerate(pages) if not t.strip()]
        return {'id':f'N{n:02}','source_url':url+name,'file':name,'sha256':h,'new_bytes':h not in seen,'page_count':len(pages),'zero_text_pages':zero,'eligible_table_pages':[],'status':'NO_IMAGE_ONLY_TABLE_IDENTIFIED'}
    with ThreadPoolExecutor(max_workers=4) as pool: records=list(pool.map(inspect,enumerate(FILES,1)))
    if len({r['sha256'] for r in records})!=len(records) or not all(r['new_bytes'] for r in records):raise ValueError('Previously seen or duplicate file')
    result={'status':'INTAKE_INCOMPLETE','new_sources':len(records),'total_pages':sum(r['page_count'] for r in records),'scan_only_table_pages':0,'candidate_inference':'NOT_RUN','human_truth':'PENDING','business':'HOLD','records':records,'note':'All nonempty table pages sampled had embedded text; zero-text pages were limited to cover/front matter. No text values saved or used as truth.'}
    (out/'intake.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))


if __name__=='__main__':main()
