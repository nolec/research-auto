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
      const check = await page.evaluate(() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,stages:document.querySelectorAll('[data-stage]').length,sources:document.querySelectorAll('[data-source]').length,observations:document.querySelector('[data-value="observations"]').textContent,secondary:document.querySelector('[data-value="secondary"]').textContent,requests:performance.getEntriesByType('resource').length,reason:document.querySelector('[data-diagnostic="reason"]').textContent,usage:document.querySelector('[data-diagnostic="usage"]').textContent,contractValid:document.querySelector('[data-diagnostic="contract-valid"]').textContent,abstained:document.querySelector('[data-diagnostic="abstained"]').textContent,positiveSanity:document.querySelector('[data-diagnostic="positive-sanity"]').textContent}));
      if(check.scrollWidth>width || check.stages!==7 || check.sources!==4 || check.observations!=='400 / 500' || check.secondary!=='0 / 20' || check.requests!==0 || check.reason!=='PREFLIGHT_BLOCKED / CLI_SEMANTIC_SANITY_FAIL' || check.usage!=='17106 / 191' || check.contractValid!=='true' || check.abstained!=='true' || check.positiveSanity!=='false') throw Error('SURFACE_VERIFICATION_FAILED');
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
