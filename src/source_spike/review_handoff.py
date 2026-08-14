from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Mapping, Sequence


def build_offline_review_html(
    packet: Sequence[Mapping[str, object]], *, title: str, review_role: str = "secondary"
) -> str:
    if review_role not in {"primary", "secondary"}:
        raise ValueError("review role must be primary or secondary")
    if not packet:
        raise ValueError("review packet must not be empty")
    allowed = (
        "assignment_id", "source", "title", "normalized_text", "published_at",
        "created_at", "canonical_url",
    )
    clean = []
    for item in packet:
        if not isinstance(item, Mapping) or not isinstance(item.get("assignment_id"), str):
            raise ValueError("review packet item is malformed")
        clean.append({key: item.get(key) for key in allowed if key in item})
    packet_json = json.dumps(clean, ensure_ascii=False).replace("</", "<\\/")
    safe_title = html.escape(title)
    secondary = review_role == "secondary"
    independence_control = (
        '<label>독립 검토 확인<span class="choice"><input id="independent" type="checkbox"> '
        'Primary 판정을 보지 않고 독립적으로 검토했습니다.</span></label>'
        if secondary else
        '<div><strong>Primary 검토</strong><p class="hint">다른 사람의 판정을 보지 말고 원문만 기준으로 판단하세요.</p></div>'
    )
    output_name = f"{review_role}-submission.jsonl"
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title>
<style>
:root{{--bg:#f5f5f2;--card:#fff;--ink:#20221f;--muted:#686d65;--line:#d9ddd5;--accent:#245c45;--bad:#9c2f2f}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}
main{{max-width:900px;margin:auto;padding:32px 18px 80px}} h1{{font-size:28px;margin:0 0 8px}} .lead{{color:var(--muted);margin-bottom:24px}}
.panel,.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin:14px 0}}
.guide{{background:#edf4ef}} .guide h2{{margin-top:0}} .guide dt{{font-weight:750;margin-top:10px}} .guide dd{{margin-left:0;color:#41463f}}
.examples{{padding-left:20px}} .progress{{position:sticky;top:0;z-index:2;background:#173e30;color:#fff;padding:10px 16px;border-radius:0 0 10px 10px}}
.meta{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} label{{display:block;font-weight:650}} input[type=text],textarea,select{{width:100%;padding:10px;border:1px solid var(--line);border-radius:7px;background:#fff}}
textarea{{min-height:86px}} .text{{white-space:pre-wrap;background:#f7f8f5;padding:14px;border-radius:8px;max-height:300px;overflow:auto}}
.question{{border-top:1px solid var(--line);padding-top:14px;margin-top:14px}} .question strong{{display:block}} .hint{{color:var(--muted);font-size:13px;font-weight:400}}
.choice{{display:flex;gap:12px;align-items:center;margin-top:7px;font-weight:400}} .choice label{{font-weight:500}}
.money{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}} a{{color:var(--accent)}} button{{border:0;border-radius:8px;padding:12px 18px;font-weight:700;cursor:pointer}}
#download{{background:var(--accent);color:white}} #status{{margin-left:12px;font-weight:650}} .error{{color:var(--bad)}} .hidden{{display:none}} .saved{{color:#d8eadf;font-size:13px}}
@media(max-width:650px){{.meta,.labels,.money{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>{safe_title}</h1>
<p class="lead">사업성을 평가하는 일이 아닙니다. 글에 아래 신호가 실제로 적혀 있는지만 확인하면 됩니다.</p>
<div class="progress"><span id="progress">완료 0 / {len(clean)}</span> · <span class="saved">입력은 이 브라우저에 자동 저장됩니다.</span></div>
<section class="panel guide"><h2>판정 기준</h2><dl>
<dt>문제 신호</dt><dd>구체적인 사람이 겪는 불편·실패·필요와 그 상황 또는 결과가 적혀 있으면 예.</dd>
<dt>돈 신호</dt><dd>구매·구독·예산·금전 손실 또는 의미 있는 시간 소모가 글에 직접 적혀 있으면 예. 추측하지 마세요.</dd>
<dt>증거로 사용 가능</dt><dd>이 글의 한두 문장만 인용해도 누가 무엇을 겪는지 설명할 수 있으면 예.</dd>
<dt>잡음</dt><dd>광고·홍보·뉴스 요약·복붙·링크뿐인 글 또는 무관한 내용이면 예.</dd></dl>
<h3>돈 신호 예시</h3><ul class="examples"><li>“수동으로 처리한다” → 아니요</li><li>“이 문제로 며칠을 소비했다” → 예, 시간 비용</li><li>“월 30만 원 서비스를 사용 중이다” → 예, 구독</li><li>“새 워크스테이션 구매를 고려한다” → 예, 지불 의사</li></ul></section>
<section class="panel meta"><label>Reviewer ID<input id="reviewer" type="text" placeholder="예: reviewer-secondary-01"></label>
{independence_control}</section>
<div id="items"></div>
<section class="panel"><button id="download">검증 후 JSONL 다운로드</button><span id="status"></span></section>
</main><script>
const packet={packet_json};
const moneyTypes=['purchase','subscription','outsourcing','labor_cost','loss','willingness_to_pay','price_complaint','replacement_search'];
const yn=(name)=>`<span class="choice"><label><input required type="radio" name="${{name}}" value="true"> 예</label><label><input required type="radio" name="${{name}}" value="false"> 아니요</label></span>`;
const escapeHtml=(s)=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
document.getElementById('items').innerHTML=packet.map((x,i)=>`<article class="card" data-index="${{i}}"><h2>${{i+1}}. ${{escapeHtml(x.title)}}</h2>
<p><a href="${{escapeHtml(x.canonical_url)}}" target="_blank" rel="noreferrer">원문 URL 열기</a> <label class="choice"><input class="external" type="checkbox"> URL/외부 맥락을 확인함</label></p>
<div class="text">${{escapeHtml(x.normalized_text)}}</div>
<div class="question"><strong>1. 실제 사람이 겪는 구체적인 문제와 상황 또는 결과가 적혀 있나요?</strong>${{yn('p'+i)}}</div>
<div class="question"><strong>2. 비용·구매·손실·예산·며칠의 시간 소모가 글에 직접 적혀 있나요?</strong><span class="hint">수작업이나 불편만으로 돈 신호를 추측하지 마세요.</span>${{yn('m'+i)}}</div>
<div class="money hidden"><label>어떤 돈 신호인가요?<select class="moneyType"><option value="">선택하세요</option><option value="purchase">제품·서비스 구매</option><option value="subscription">유료 구독</option><option value="outsourcing">외주·대행 비용</option><option value="labor_cost">며칠 등 의미 있는 시간 비용</option><option value="loss">매출·재고·벌금 등 금전 손실</option><option value="willingness_to_pay">구매·예산 투입 의사</option><option value="price_complaint">구체적인 가격 불만</option><option value="replacement_search">유료 대안·교체품 탐색</option></select></label>
<label>이 돈 신호가 게시물 본문에 직접 적혀 있나요?${{yn('s'+i)}}</label></div>
<div class="question"><strong>3. 한두 문장만 인용해도 누가 무엇을 겪는지 설명할 수 있나요?</strong>${{yn('e'+i)}}</div>
<div class="question"><strong>4. 광고·홍보·뉴스 요약·복붙·링크뿐인 글 또는 무관한 내용인가요?</strong>${{yn('n'+i)}}</div>
<label class="question">5. 결정적인 원문 근거를 짧게 설명해 주세요. (20자 이상)<textarea class="reason" placeholder="예: 배포본에서만 로그인이 실패하고 해결을 위해 며칠을 썼다고 직접 적혀 있다."></textarea></label></article>`).join('');
const radio=(card,name)=>{{const x=card.querySelector(`input[name="${{name}}"]:checked`);return x?x.value==='true':null}};
const reviewRole={json.dumps(review_role)};
const storageKey='research-auto-'+reviewRole+'-'+packet.map(x=>x.assignment_id).join('-');
const cards=()=>[...document.querySelectorAll('.card')];
const complete=(c,i)=>['p','m','e','n'].every(k=>radio(c,k+i)!==null)&&c.querySelector('.reason').value.trim().length>=20&&(radio(c,'m'+i)===false||(radio(c,'s'+i)!==null&&c.querySelector('.moneyType').value));
const update=()=>{{let done=0;cards().forEach((c,i)=>{{const m=radio(c,'m'+i),box=c.querySelector('.money');box.classList.toggle('hidden',m!==true);if(m===false){{c.querySelector('.moneyType').value='';c.querySelectorAll(`input[name="s${{i}}"]`).forEach(x=>x.checked=x.value==='false')}}if(complete(c,i))done++}});document.getElementById('progress').textContent=`완료 ${{done}} / ${{packet.length}}`;save()}};
const independence=()=>reviewRole==='secondary'?document.getElementById('independent').checked:true;
const save=()=>{{const value={{reviewer:document.getElementById('reviewer').value,independent:independence(),cards:cards().map((c,i)=>({{p:radio(c,'p'+i),m:radio(c,'m'+i),e:radio(c,'e'+i),n:radio(c,'n'+i),s:radio(c,'s'+i),moneyType:c.querySelector('.moneyType').value,external:c.querySelector('.external').checked,reason:c.querySelector('.reason').value}}))}};localStorage.setItem(storageKey,JSON.stringify(value))}};
const restore=()=>{{try{{const v=JSON.parse(localStorage.getItem(storageKey));if(!v)return;document.getElementById('reviewer').value=v.reviewer||'';if(reviewRole==='secondary')document.getElementById('independent').checked=!!v.independent;cards().forEach((c,i)=>{{const x=v.cards?.[i]||{{}};for(const k of ['p','m','e','n','s'])if(x[k]!==null&&x[k]!==undefined){{const el=c.querySelector(`input[name="${{k}}${{i}}"]`+`[value="${{x[k]}}"]`);if(el)el.checked=true}}c.querySelector('.moneyType').value=x.moneyType||'';c.querySelector('.external').checked=!!x.external;c.querySelector('.reason').value=x.reason||''}})}}catch(_e){{}}}};
document.querySelector('main').addEventListener('input',update);document.querySelector('main').addEventListener('change',update);restore();update();
document.getElementById('download').onclick=()=>{{
 const reviewer=document.getElementById('reviewer').value.trim(), independent=independence();
 const errors=[]; if(!reviewer)errors.push('Reviewer ID를 입력하세요.'); if(reviewRole==='secondary'&&reviewer==='noseunglae-primary')errors.push('Primary와 다른 Reviewer ID가 필요합니다.'); if(reviewRole==='secondary'&&!independent)errors.push('독립 검토 확인이 필요합니다.');
 const now=new Date().toISOString(); const rows=packet.map((x,i)=>{{const c=document.querySelector(`[data-index="${{i}}"]`);const p=radio(c,'p'+i),m=radio(c,'m'+i),e=radio(c,'e'+i),n=radio(c,'n'+i),s=radio(c,'s'+i),t=c.querySelector('.moneyType').value||null,reason=c.querySelector('.reason').value.trim();
  if([p,m,e,n].includes(null))errors.push(`${{i+1}}번의 네 가지 질문에 모두 답하세요.`); if(reason.length<20)errors.push(`${{i+1}}번 판정 이유를 20자 이상 입력하세요.`); if(m&&(!t||s===null))errors.push(`${{i+1}}번 돈 신호의 유형과 본문 직접 관찰 여부를 선택하세요.`);
  return {{assignment_id:x.assignment_id,reviewer_id:reviewer,reviewer_independence_asserted:independent,problem_signal:p,money_signal:m,money_signal_type:m?t:null,structural_money_signal:m?s:false,usable_evidence:e,noise:n,external_context_used:c.querySelector('.external').checked,label_reason:reason,labeled_at:now}};}});
 const status=document.getElementById('status'); if(errors.length){{status.className='error';status.textContent=errors[0];return}}
 const blob=new Blob([rows.map(x=>JSON.stringify(x)).join('\\n')+'\\n'],{{type:'application/x-ndjson'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download={json.dumps(output_name)};a.click();URL.revokeObjectURL(a.href);status.className='';status.textContent='다운로드 완료';
}};
</script></body></html>"""


def write_offline_review(
    packet_path: Path, destination: Path, *, title: str, review_role: str = "secondary"
) -> None:
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if not isinstance(packet, list):
        raise ValueError("review packet must be a JSON array")
    rendered = build_offline_review_html(packet, title=title, review_role=review_role)
    if destination.is_file() and destination.read_text(encoding="utf-8") == rendered:
        return
    destination.write_text(rendered, encoding="utf-8")
