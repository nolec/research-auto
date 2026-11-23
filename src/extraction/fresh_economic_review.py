"""Freeze fresh excerpts and generate a prediction-free local reviewer UI."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlparse

from src.extraction.codex_cli_diagnostic import _private_create
from src.source_spike.fresh_ted_economic_intake import historical

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'artifacts/extraction/calibration/audit-local'
OUT=BASE/'fresh-economic-review-v2-20261123'
INPUTS=(BASE/'fresh-economic-intake-v3-20261123.json',BASE/'fresh-economic-stackexchange-intake-20261123/result.json',
        BASE/'fresh-economic-steam-webapi-v2-20261123/result.json',BASE/'fresh-economic-ted-intake-20261123/result.json')
EXPECTED={'github':7,'stackexchange':7,'steam':10,'ted':10}
DOMAINS={'github':'github.com','stackexchange':'superuser.com','steam':'steamcommunity.com','ted':'ted.europa.eu'}
DIMENSIONS=(('procurement_intent','구매·조달 요청','구매자가 공급자 또는 제품·서비스를 명시적으로 요청했나요?'),
 ('budget_or_willingness_to_pay','예산·지불 의사','금액·예산 또는 돈을 지불하려는 의도가 명시됐나요?'),
 ('contract_awarded','계약 체결','낙찰자 선정 또는 계약 체결이 명시됐나요? 입찰 공고만으로는 아니에요.'),
 ('actual_payment','실제 결제','완료된 결제 또는 실제 지출이 명시됐나요? 예산·낙찰·구매 배지만으로는 아니에요.'),
 ('economic_loss','경제적 손실','구체적인 비용·금전 손실이 명시됐나요?'),
 ('labor_burden','업무 시간 부담','업무나 필요한 작업 때문에 의미 있는 시간이 소요됐나요? 여가 시간은 제외해요.'))


def build_snapshot(paths, expected, old_ids, old_texts):
    records=[]; input_hashes={}; ids=set(old_ids); excerpts=set(); counts=Counter()
    for path in paths:
        raw=path.read_bytes(); obj=json.loads(raw)
        if not obj['status'].endswith('GOLD_PENDING'): raise ValueError('intake not ready')
        input_hashes[str(path)]=sha256(raw).hexdigest()
        for row in obj['records']:
            source=row['source']; excerpt=row['excerpt']; url=urlparse(row['source_url']); doc_id=row['document_id']
            digest=sha256(excerpt.encode()).hexdigest()
            if (source not in DOMAINS or url.scheme!='https' or url.netloc!=DOMAINS[source] or not doc_id.startswith(source+':')
                or doc_id in ids or digest in excerpts or digest!=row['excerpt_sha256'] or not 0<len(excerpt.split())<=25
                or not '2026-08-25'<=row['published_at'][:10]<='2026-11-22' or any(excerpt in old for old in old_texts)):
                raise ValueError('snapshot membership or excerpt invalid')
            ids.add(doc_id); excerpts.add(digest); counts[source]+=1
            value={k:row[k] for k in ('source','document_id','source_url','published_at','title','excerpt','excerpt_sha256')}
            value['date_precision']=row.get('date_precision','second')
            if source=='stackexchange': value['content_license']=row['content_license']
            observed=row.get('observed_fields',{})
            if source=='ted':
                value['form_type']=row['form_type']
                value['evidence_fields']={k:observed.get(k,[]) for k in ('winner_selection_status','contract_conclusion_date')}
            if source=='steam':
                value['context_only']={k:observed[k] for k in ('steam_purchase','received_for_free','refunded','voted_up') if type(observed.get(k)) is bool}
            records.append(value)
    if counts!=expected: raise ValueError('source count mismatch')
    # Fixed deterministic order independent of labels or model predictions.
    records.sort(key=lambda r:sha256(('economic-review-v2:'+r['document_id']).encode()).hexdigest())
    return {'status':'FROZEN_EXCERPT_CORPUS_GOLD_PENDING','counts':dict(counts),'input_hashes':input_hashes,
            'taxonomy_sha256':sha256((ROOT/'docs/economic-signal-taxonomy-v2.md').read_bytes()).hexdigest(),
            'scope':'fresh excerpt diagnostic; not representative; independent gold pending','records':records}


def render(snapshot, snapshot_hash):
    template=(ROOT/'docs/fresh-economic-review-template.html').read_text()
    payload=json.dumps({'records':snapshot['records'],'hash':snapshot_hash,'dimensions':DIMENSIONS},ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return template.replace('/*__PAYLOAD__*/ null',payload,1)


def main():
    old=historical(); snapshot=build_snapshot(INPUTS,EXPECTED,old[0],old[2])
    OUT.mkdir(mode=0o700,exist_ok=False)
    _private_create(OUT/'snapshot.json',snapshot)
    digest=sha256((OUT/'snapshot.json').read_bytes()).hexdigest()
    html=render(snapshot,digest)
    with (OUT/'review.html').open('x',encoding='utf-8') as stream: stream.write(html)
    print(json.dumps({'status':snapshot['status'],'count':len(snapshot['records']),'snapshot_sha256':digest,'review':str(OUT/'review.html')}))


if __name__=='__main__': main()
