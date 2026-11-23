// Build an XLSX for the synthetic stock-list pilot only; do not infer customer types.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {Workbook, SpreadsheetFile, FileBlob} from '@oai/artifact-tool';

const [reviewPath, outputDir] = process.argv.slice(2);
const r = JSON.parse(await fs.readFile(reviewPath, 'utf8'));
assert.deepEqual(r.headers, ['품목코드','품목명','수량','보관구역']);
assert.equal(r.status, 'REQUIRES_HUMAN_REVIEW');
assert.equal(r.input_count, 24);
assert.deepEqual([r.accepted.length,r.duplicates.length,r.exceptions.length],[17,2,5]);
const workbook = Workbook.create();
const summary = workbook.worksheets.add('검수 요약');
const clean = workbook.worksheets.add('정리 결과');
const exceptions = workbook.worksheets.add('확인 필요');
const duplicates = workbook.worksheets.add('중복 기록');
const source = workbook.worksheets.add('원본 행 기록');
const font = 'Arial';
const names = Object.fromEntries(r.sources.map(s=>[s.source,s.name]));
const reason = {exact_duplicate:'완전 중복',conflicting_key:'동일 코드·다른 값',missing_key:'코드 누락'};
const data = e => [e.values[0] || null,e.values[1],Number(e.values[2]),e.values[3]];
const trace = e => [names[e.source],e.line_end];
const allRows = [...r.accepted.map(e=>({...e,reason:'accepted'})),...r.duplicates,...r.exceptions].sort((a,b)=>a.source-b.source||a.line_end-b.line_end);
assert.equal(new Set(allRows.map(e=>`${e.source}:${e.line_end}`)).size,24);

function table(sheet,headers,rows,widths,issue=false){
  sheet.showGridLines = false;
  const matrix = [headers,...rows];
  const range = sheet.getRangeByIndexes(0,0,matrix.length,headers.length);
  sheet.getRangeByIndexes(1,0,rows.length,1).setNumberFormat('@');
  range.values = matrix;
  range.format.font = {name:font,size:10,color:'#26374A'};
  range.format.rowHeight = 21;
  range.format.verticalAlignment='center';
  const header=sheet.getRangeByIndexes(0,0,1,headers.length);
  header.format={fill:'#253B55',font:{name:font,size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',rowHeight:28};
  widths.forEach((w,i)=>sheet.getRangeByIndexes(0,i,matrix.length,1).format.columnWidth=w);
  sheet.getRangeByIndexes(1,0,rows.length,1).setNumberFormat('@');
  sheet.getRangeByIndexes(1,2,rows.length,1).setNumberFormat('#,##0');
  if(issue) sheet.getRangeByIndexes(1,headers.length-1,rows.length,1).format.fill='#FFF0D5';
  sheet.freezePanes.freezeRows(1);
}
table(clean,[...r.headers,'원본 파일','원본 행'],r.accepted.map(e=>[...data(e),...trace(e)]),[15,25,12,15,22,12]);
table(exceptions,[...r.headers,'원본 파일','원본 행','확인 사유'],r.exceptions.map(e=>[...data(e),...trace(e),reason[e.reason]]),[15,25,12,15,22,12,28],true);
table(duplicates,[...r.headers,'원본 파일','원본 행','처리 사유'],r.duplicates.map(e=>[...data(e),...trace(e),reason[e.reason]]),[15,25,12,15,22,12,28]);
table(source,[...r.headers,'원본 파일','원본 행','분류'],allRows.map(e=>[...data(e),...trace(e),e.reason==='accepted'?'정리 결과':reason[e.reason]]),[15,25,12,15,22,12,28]);
summary.showGridLines=false;
summary.tabColor='#253B55';
summary.getRange('A2').values=[['엑셀 파일 병합 및 검수 샘플']];
summary.getRange('A2').format.font={name:font,size:15,bold:true,color:'#253B55'};
summary.getRange('A4').values=[['가상 비품 목록 · 원본 2개 · 식별 기준: 품목코드']];
summary.getRange('A4').format.font={name:font,size:10,italic:true,color:'#52677C'};
summary.getRange('A6:B11').values=[['처리 구분','행 수'],['원본 행',null],['정리 결과',null],['완전 중복',null],['확인 필요',null],['미분류 행',null]];
summary.getRange('B7:B11').formulas=[["=COUNTA('원본 행 기록'!E2:E25)"],["=COUNTA('정리 결과'!E2:E18)"],["=COUNTA('중복 기록'!E2:E3)"],["=COUNTA('확인 필요'!E2:E6)"],['=B7-SUM(B8:B10)']];
summary.getRange('A6:B6').format={fill:'#253B55',font:{name:font,size:10,bold:true,color:'#FFFFFF'},rowHeight:28};
summary.getRange('A7:B11').format.font={name:font,size:10,color:'#26374A'};
summary.getRange('A7:B11').format.rowHeight=23;
summary.getRange('A10:B10').format.fill='#FFF0D5';
summary.getRange('A1:A16').format.columnWidth=48;
summary.getRange('B1:B16').format.columnWidth=18;
summary.getRange('B7:B11').setNumberFormat('#,##0');
summary.getRange('A13').values=[['같은 코드에 다른 값이 있으면 두 행 모두 보류합니다.']];
summary.getRange('A14').values=[['코드 누락은 확인 필요 목록에 남깁니다.']];
summary.getRange('A15').values=[['가상 데이터로 만든 예시입니다. 실제 고객 작업이 아닙니다.']];
summary.getRange('A13:A15').format.font={name:font,size:10,color:'#52677C'};
workbook.recalculate();
assert.deepEqual(summary.getRange('B7:B11').values.flat(),[24,17,2,5,0]);
console.log((await workbook.inspect({kind:'table',range:'검수 요약!A6:B11',include:'values,formulas',tableMaxRows:8,tableMaxCols:2})).ndjson);
console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50}})).ndjson);
await fs.mkdir(outputDir,{recursive:true});
for(const [sheet,range] of [[summary,'A1:B16'],[clean,'A1:F18'],[exceptions,'A1:G6'],[duplicates,'A1:G3'],[source,'A1:G25']]){
  const blob=await workbook.render({sheetName:sheet.name,range,scale:1,format:'png'});
  await fs.writeFile(path.join(outputDir,`preview-${sheet.name}.png`),new Uint8Array(await blob.arrayBuffer()));
}
const filename=path.join(outputDir,'spreadsheet-cleanup-sample.xlsx');
await (await SpreadsheetFile.exportXlsx(workbook)).save(filename);
const reopened=await SpreadsheetFile.importXlsx(await FileBlob.load(filename));
assert.deepEqual(reopened.worksheets.getItem('검수 요약').getRange('B7:B11').values.flat(),[24,17,2,5,0]);
assert.equal(reopened.worksheets.getItem('정리 결과').getRange('A2').values[0][0],'0001');
for(const [name,rows] of [['정리 결과',r.accepted],['확인 필요',r.exceptions],['중복 기록',r.duplicates],['원본 행 기록',allRows]]){
  const sh=reopened.worksheets.getItem(name);
  const actual=sh.getRangeByIndexes(1,0,rows.length,6).values;
  assert.deepEqual(actual,rows.map(e=>[...data(e),...trace(e)]));
}
console.log('XLSX reopened: all 24 source rows, classifications, numeric fields, and leading-zero IDs verified.');
