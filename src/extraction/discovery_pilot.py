"""Build exploratory evidence cards from attributed AI annotations of saved documents.

Not the calibrated producer. Semantic grouping is supplied by the annotator;
no automatic source eligibility, evidence promotion, or independent audit.
"""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from src.research_console import runs


def build(spec, paths):
    if spec['mode'] != 'CHATGPT_ASSISTED_EXPLORATION_NOT_PROVIDER_CALIBRATION':
        raise ValueError('Unsupported annotation provenance')
    as_of = datetime.fromisoformat(spec['as_of'])
    documents = {}
    source_runs = {}
    for source, run_id in spec['runs'].items():
        path = paths[run_id]
        raw = path.read_bytes()
        data = json.loads(raw)
        if data['source'] != source or data['run_id'] != run_id or len(data['items']) < 10:
            raise ValueError('Wrong frozen source run')
        source_runs[source] = {'id': run_id, 'sha256': hashlib.sha256(raw).hexdigest()}
        for doc in data['items'][:10]:
            if doc['document_id'] in documents:
                raise ValueError('Duplicate selected document')
            documents[doc['document_id']] = doc
    if len(documents) != 40 or len(spec['runs']) != 4:
        raise ValueError('Expected 40 documents across four sources')
    annotations = spec['annotations']
    if len(annotations) != len(documents) or {a[0] for a in annotations} != set(documents):
        raise ValueError('Each selected document must be classified exactly once')
    groups = defaultdict(list)
    abstentions = []
    for doc_id, kind, key, problem, quote, signal in annotations:
        doc = documents[doc_id]
        base = {'document_id': doc_id, 'source': doc['source'], 'url': doc['source_url'], 'published_at': doc['published_at']}
        if kind == 'abstain':
            if any(v is not None for v in (key, problem, quote)) or signal != 'none':
                raise ValueError('Abstention cannot supply evidence')
            abstentions.append(base)
            continue
        if kind not in ('problem', 'procurement') or signal not in ('none','resource_loss','workflow_blocked','solicitation') or (kind == 'procurement') != (signal == 'solicitation'):
            raise ValueError('Invalid signal')
        if not all(isinstance(s,str) and s for s in (quote,key,problem)):
            raise ValueError('Missing annotation')
        start = doc['text'].find(quote)
        if start < 0 or start >= 1800:
            raise ValueError(f'Quote not in inspected excerpt: {doc_id}')
        if start + len(quote) > 1800:
            raise ValueError(f'Quote extends beyond inspected excerpt: {doc_id}')
        published = datetime.fromisoformat(doc['published_at'].replace('Z','+00:00'))
        groups[key].append({**base, 'kind':kind,'problem':problem,'quote':quote,'start':start,'end':start+len(quote),'signal':signal,'author_hash':doc.get('author_hash'),'community':doc.get('community'),'recent':as_of-timedelta(days=90)<=published<as_of})
    cards = []
    for key, evidence in groups.items():
        if len({(e['problem'],e['kind']) for e in evidence}) != 1:
            raise ValueError('Inconsistent group')
        counts = Counter(e['signal'] for e in evidence)
        # A procurement requirement is a buying signal, not a payment or proof of pain.
        cards.append({'key':key,'problem':evidence[0]['problem'],'kind':evidence[0]['kind'], 'observations':len(evidence),'distinct_author_hashes':len({(e['source'],e['author_hash']) for e in evidence if e['author_hash']}),'independent_groups':'UNKNOWN','recent_cases':sum(e['recent'] for e in evidence),'solicitations':counts['solicitation'],'workflow_blocked':counts['workflow_blocked'],'resource_loss':counts['resource_loss'],'actual_payment':'UNKNOWN','evidence_status':'INSUFFICIENT_EVIDENCE','actionability':'UNKNOWN','decision':'HOLD','growth':'UNKNOWN','counter_evidence':'NOT_ASSESSED','official_review_value':None,'evidence':evidence})
    # Prioritize observable procurement, then concrete disruption; not PRD rank.
    cards.sort(key=lambda c:(-c['solicitations'],-c['workflow_blocked'],-c['resource_loss'],-c['observations'],c['key']))
    return {'mode':spec['mode'],'as_of':spec['as_of'],'source_runs':source_runs,'scope':'First 10 stored docs per source; first 1800 characters reviewed; no current market search','documents':len(documents),'abstained':abstentions,'candidates':cards,'top_review_queue': [c['key'] for c in cards[:20]],'verified_opportunities':0,'official_top20':None}


def render(result):
    lines = ['# Research-Auto — 40-document exploratory review queue','',f"Date: {result['as_of']}", '',result['scope'],'','Semantic groups were proposed by ChatGPT in this session. Not an independent evaluation, automated model run, official TOP 20 or verified opportunity. All candidates are HOLD. A solicitation is not a payment.','',f"Documents: {result['documents']} | Abstained: {len(result['abstained'])} | Candidate groups: {len(result['candidates'])}",'','## Review queue (up to 20)','']
    for i,c in enumerate(result['candidates'][:20],1):
        lines += [f"### {i}. {c['problem']} ({c['key']})",f"- Observations {c['observations']}; recent {c['recent_cases']}; solicitations {c['solicitations']}; reported disruption {c['workflow_blocked']+c['resource_loss']}; decision HOLD.",'- Independent evidence, payment, customer fit and counter-evidence are unverified.','']
        for e in c['evidence']:
            lines.append(f"- [{e['document_id']}]({e['url']}) — {e['quote']}")
        lines.append('')
    lines += ['## Remaining groups',''] + [f"- {c['problem']} ({c['key']})" for c in result['candidates'][20:]]
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('annotations',type=Path); parser.add_argument('output_dir',type=Path)
    args=parser.parse_args()
    result=build(json.loads(args.annotations.read_text()), {p.parent.name:p for p in runs()})
    args.output_dir.mkdir(parents=True,exist_ok=False)
    (args.output_dir/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (args.output_dir/'review.md').write_text(render(result))
    print(f"{result['documents']} docs, {len(result['abstained'])} abstentions, {len(result['candidates'])} candidate groups, 0 verified opportunities")


if __name__=='__main__': main()
