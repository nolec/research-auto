// Disposable synthetic fixtures for the conversion experiment, never customer data.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [runtimeNodeModules, out] = process.argv.slice(2);
const require = createRequire(path.join(runtimeNodeModules, '_resolver.cjs'));
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
await fs.mkdir(out, { recursive: true });
const specs = [
  { name: '01-monthly', title: 'Monthly production', values: [80, 110, 95, 140], type: 'bar', pos: ['A10', 'D24'] },
  { name: '02-weekly', title: 'Weekly operations', values: [12, 21, 18, 29], type: 'line', pos: ['D4', 'I17'] },
  { name: '03-detail', title: 'Detailed inventory', values: [31, 48, 22, 55], type: 'bar', pos: ['A10', 'D24'], detail: true },
];
for (const spec of specs) {
  const w = Workbook.create();
  const s = w.worksheets.add('Report');
  s.showGridLines = false;
  s.getRange('A1:I25').format.font = { name: 'Arial', size: 11, color: '#24384A' };
  s.getRange('A1:I25').format.rowHeight = 20;
  s.getRange('A:A').format.columnWidth = 22;
  s.getRange('B:I').format.columnWidth = 15;
  s.getRange('A2').values = [[spec.title]];
  s.getRange('A2').format.font = { name: 'Arial', size: 15, bold: true, color: '#24384A' };
  s.getRange('A4:B8').values = [['Period','Units'], ...spec.values.map((v,i)=>[`P${i+1}`,v])];
  s.getRange('A4:B4').format.fill = '#24384A';
  s.getRange('A4:B4').format.font = { name: 'Arial', color: '#FFFFFF', bold: true, size: 11 };
  s.getRange('A9').values = [['Total']];
  s.getRange('B9').formulas = [['=SUM(B5:B8)']];
  const chart = s.charts.add(spec.type, s.getRange('A4:B8'));
  chart.title = 'Units by period';
  chart.titleTextStyle.typeface = 'Arial';
  chart.hasLegend = false;
  chart.xAxis = { axisType: 'textAxis', textStyle: { typeface: 'Arial' } };
  chart.yAxis = { numberFormatCode: '0', numberFormatSourceLinked: false, textStyle: { typeface: 'Arial' } };
  chart.series.items[0].fill = '#287C9A';
  if (spec.type === 'line') chart.series.items[0].line = {fill:'#287C9A',style:'solid',width:2};
  chart.setPosition(...spec.pos);
  if (spec.detail) {
    const d = w.worksheets.add('Detail');
    d.showGridLines = false;
    d.getRange('A1:C61').format.font = {name:'Arial',size:11,color:'#24384A'};
    d.getRange('A1:C61').format.rowHeight = 20;
    d.getRange('A:C').format.columnWidth = 20;
    d.getRange('A1:C61').values = [['Item','Quantity','Section'],...Array.from({length:60},(_,i)=>[`ITEM-${String(i+1).padStart(3,'0')}`,i+10,`Zone ${i%3+1}`])];
    d.getRange('A1:C1').format.fill = '#24384A';
    d.getRange('A1:C1').format.font = {name:'Arial',size:11,color:'#FFFFFF',bold:true};
  }
  w.recalculate();
  assert.equal(s.getRange('B9').values[0][0], spec.values.reduce((a,b)=>a+b));
  assert.equal(s.charts.items.length,1);
  assert.match(chart.series.items[0].formula,/B\$?5.*B\$?8/);
  await (await SpreadsheetFile.exportXlsx(w)).save(path.join(out,`${spec.name}.xlsx`));
}
