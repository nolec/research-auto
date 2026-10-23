const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
(async () => {
  const revision = JSON.parse(fs.readFileSync(path.join(__dirname,'source-data.json'))).snapshot_revision;
  if(typeof revision!=='string' || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(revision)) throw Error('INPUT_CONTRACT_REQUIRED: snapshot_revision');
  const evidenceRelative = path.join('evidence',revision);
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  const results = [];
  try {
    for (const width of [1440,390]) {
      const page = await browser.newPage({viewport:{width,height:1000},deviceScaleFactor:1});
      await page.emulateMedia({reducedMotion:'reduce'});
      await page.goto('file://' + path.join(__dirname,'index.html'));
      const screenshot = path.join(evidenceRelative,`render-${width}.png`);
      await page.screenshot({path:path.join(__dirname,screenshot),fullPage:true});
      const check = await page.evaluate(() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,stages:document.querySelectorAll('[data-stage]').length,sources:document.querySelectorAll('[data-source]').length,observations:document.querySelector('[data-value="observations"]').textContent,secondary:document.querySelector('[data-value="secondary"]').textContent,requests:performance.getEntriesByType('resource').length,reason:document.querySelector('[data-diagnostic="reason"]').textContent,usage:document.querySelector('[data-diagnostic="usage"]').textContent,contractValid:document.querySelector('[data-diagnostic="contract-valid"]').textContent,abstained:document.querySelector('[data-diagnostic="abstained"]').textContent,positiveSanity:document.querySelector('[data-diagnostic="positive-sanity"]').textContent,accounting:document.querySelector('[data-diagnostic="accounting"]').textContent,rootCause:document.querySelector('[data-diagnostic="root-cause"]').textContent,improvement:document.querySelector('[data-diagnostic="improvement"]').textContent,ship:document.querySelector('[data-ship="status"]').textContent,quality:document.querySelector('[data-ship="quality"]').textContent}));
      if(check.ship!=='BLOCKED' || check.quality!=='품질 게이트: unconfigured · 검증 실행: NOT_RUN' || check.scrollWidth>width || check.stages!==7 || check.sources!==4 || check.observations!=='400 / 500' || check.secondary!=='0 / 20' || check.requests!==0 || check.reason!=='INCOMPLETE / CLI_OUTPUT_MISSING' || check.usage!=='36334 / 839' || check.contractValid!=='null' || check.abstained!=='null' || check.positiveSanity!=='null' || check.accounting!=='有効 0 · 기권 0 · 무효 0 · 운영 실패 1 · 미시도 39'.replace('有効','유효') || check.rootCause!=='UNKNOWN' || !check.improvement.includes('367 passed, 1 skipped') || !check.improvement.includes('terminal-probe-v2') || !check.improvement.includes('CLI_NONZERO_EXIT') || !check.improvement.includes('36 passed') || !check.improvement.includes('시도 1·실행 1') || !check.improvement.includes('구현 번들 MATCH') || !check.improvement.includes('NOT_RUN') || !check.improvement.includes('조사 종료') || !check.improvement.includes('사용자 제공') || !check.improvement.includes('수동 카드 1건') || !check.improvement.includes('보류 유지') || !check.improvement.includes('제품 검증 완료·카드 생산 실적 아님') || !check.improvement.includes('OMC 조사 종료 수용') || !check.improvement.includes('당시 직접적인 pending 무효 조건은 미확정') || !check.improvement.includes('소급 복구 없음') || !check.improvement.includes('제한된 로컬 검색 결과 수용') || !check.improvement.includes('전체 원문 감사 아님') || !check.improvement.includes('기존 HOLD 유지') || !check.improvement.includes('github:4996577382') || !check.improvement.includes('최종 보류 유지') || !check.improvement.includes('같은 작성자 해시') || !check.improvement.includes('github:5002866511') || !check.improvement.includes('closed 사유 미확인') || !check.improvement.includes('세 건의 수동 검토') || !check.improvement.includes('github:5003192389') || !check.improvement.includes('회귀 여부·반복 빈도·영향 규모 미확인') || !check.improvement.includes('네 건의 수동 검토') || !check.improvement.includes('github:5006282465') || !check.improvement.includes('.iloc traceback 사용자 호출 행 불일치 미해소') || !check.improvement.includes('5개 생산 목표 달성 아님') || !check.improvement.includes('github:5016862188') || !check.improvement.includes('수동 검토 6건은 제품 검증 완료·카드 생산 실적 아님') || !check.improvement.includes('github:5021233814') || !check.improvement.includes('구현 반영 여부 미확인') || !check.improvement.includes('수동 검토 7건은 제품 검증 완료·카드 생산 실적 아님') || !check.improvement.includes('github:5031774885') || !check.improvement.includes('중간 버전은 생략') || !check.improvement.includes('수동 검토 8건은 제품 검증 완료·카드 생산 실적 아님') || !check.improvement.includes('github:5034214812') || !check.improvement.includes('반영 여부·closed 사유 미확인') || !check.improvement.includes('수동 검토 9건은 제품 검증 완료·카드 생산 실적 아님') || !check.improvement.includes('github:5037425861') || !check.improvement.includes('파일 손상이 아니라 읽기 결과') || !check.improvement.includes('수동 검토 10건은 제품 검증 완료·카드 생산 실적 아님') || !check.improvement.includes('github:5038193296') || !check.improvement.includes('수치 불일치 미해소') || !check.improvement.includes('수동 검토 11건은 제품 검증 완료·카드 생산 실적 아님')) throw Error('SURFACE_VERIFICATION_FAILED');
      results.push({status:'PASS',viewport:width+'px',command_or_method:'node verify-render.cjs; installed Chrome; screenshot and DOM checks',evidence:{...check,screenshot}});
      await page.close();
    }
  } finally { await browser.close(); }
  const ev = path.join(__dirname,evidenceRelative);
  const initial = JSON.parse(fs.readFileSync(path.join(ev,'initial.json')));
  const b = fs.readFileSync(path.join(__dirname,initial.source.path));
  const c = fs.readFileSync(path.join(__dirname,initial.contract.path));
  const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
  if(hash(b)!==initial.source.sha256 || b.length!==initial.source.size_bytes || JSON.parse(b).milestones.length!==initial.source.row_count || hash(c)!==initial.contract.sha256 || c.length!==initial.contract.size_bytes) throw Error('SNAPSHOT_DRIFT');
  const reportPath = path.join(ev,'handoff.json');
  const report = JSON.parse(fs.readFileSync(reportPath));
  report.verification.desktop_render_verification = results[0];
  report.verification.mobile_render_verification = results[1];
  report.preview_status = 'RENDERED';
  report.acceptance_state = 'USER_ACCEPTANCE_PENDING';
  fs.writeFileSync(reportPath,JSON.stringify(report,null,2));
  console.log(JSON.stringify({render:results,acceptance_state:report.acceptance_state}));
})().catch(e => {console.error(e.message);process.exit(1);});
