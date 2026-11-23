import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const out = process.argv[2];
const { source, records } = JSON.parse(await fs.readFile(path.join(out,'sample-data.json'),'utf8'));
const wb=Workbook.create(), data=wb.worksheets.add('Extracted data'), qa=wb.worksheets.add('Source review');
const years=[1940,1935,1920], items=[...new Set(records.map(r=>r.item))];
const navy='#24455F', ink='#142538';
function base(sheet,range){sheet.showGridLines=false;sheet.getRange(range).format.font={name:'Arial',size:10,color:ink};sheet.getRange(range).format.verticalAlignment='center';}
function header(sheet,range){sheet.getRange(range).format={fill:navy,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',rowHeight:24};}
function title(sheet,cell,text){sheet.getRange(cell).values=[[text]];sheet.getRange(cell).format.font={name:'Arial',size:14,bold:true,color:navy};}
base(data,'A1:D15');data.tabColor=navy;title(data,'A2','Idaho livestock values');
data.getRange('A3').values=[['Public-data sample · Selected rows · USD']];data.getRange('A3').format.font={name:'Arial',size:10,italic:true,color:'#567080'};
data.getRange('A5:D13').values=[['Item',...years],...items.map(item=>[item,...years.map(y=>records.find(r=>r.item===item&&r.year===y).final)])];
header(data,'A5:D5');data.getRange('A6:A13').format.columnWidth=33;data.getRange('B6:D13').format.columnWidth=18;data.getRange('B6:D13').setNumberFormat('#,##0');data.getRange('A6:D13').format.rowHeight=22;
for(let i=6;i<=13;i+=2)data.getRange(`A${i}:D${i}`).format.fill='#F0F4F7';
data.getRange('A15').values=[['Source review tab identifies the original page and source location for every value.']];data.getRange('A15:D15').merge();data.getRange('A15:D15').format.wrapText=true;data.getRange('A15:D15').format.rowHeight=30;

base(qa,'A1:I30');title(qa,'A2','Source review');qa.getRange('A3:I3').merge();qa.getRange('A3').values=[[`Source: ${source}`]];qa.getRange('A3:I3').format.wrapText=true;qa.getRange('A3:I3').format.rowHeight=30;
qa.getRange('A4:I4').merge();qa.getRange('A4').values=[['Historical human-reviewed demo; page 4, State Table 18. R/C refer to selected scope, not absolute table indices.']];qa.getRange('A4:I4').format.wrapText=true;qa.getRange('A4:I4').format.rowHeight=28;
const headers=['Item','Year','Page','Scope cell','Initial read','Final value','Reader triage','Human outcome','Source crop (context px)'];
const details=records.map(r=>[r.item,r.year,r.page,`R${r.row}C${r.column}`,r.initial,r.final,r.queue?'Review requested':'Readers agreed',r.changed?'Corrected':'Matched',r.box.join(', ')]);
qa.getRange('A6:I30').values=[headers,...details];header(qa,'A6:I6');qa.freezePanes.freezeRows(6);
for(const [col,width] of Object.entries({A:30,B:10,C:9,D:13,E:16,F:16,G:21,H:17,I:30}))qa.getRange(`${col}6:${col}30`).format.columnWidth=width;
qa.getRange('E7:F30').setNumberFormat('#,##0');qa.getRange('A7:I30').format.rowHeight=21;
records.forEach((r,i)=>{const n=i+7;if(i%2===0)qa.getRange(`A${n}:I${n}`).format.fill='#F0F4F7';if(r.queue)qa.getRange(`G${n}`).format.fill='#FFF0D8';if(r.changed){qa.getRange(`E${n}:F${n}`).format.fill='#FFF0D8';qa.getRange(`H${n}`).format.font={name:'Arial',size:10,bold:true,color:'#98490C'};}});
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'Extracted data!A5:D13',include:'values,formulas',tableMaxRows:9,tableMaxCols:4})).ndjson);
console.log((await wb.inspect({kind:'table',range:'Source review!A6:I30',include:'values,formulas',tableMaxRows:25,tableMaxCols:9,maxChars:4000})).ndjson);
for(const [sheetName,range,name] of [['Extracted data','A1:D15','data-preview.png'],['Source review','A1:I13','qa-preview.png']]){
  const image=await wb.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(path.join(out,name),new Uint8Array(await image.arrayBuffer()));
}
const file=await SpreadsheetFile.exportXlsx(wb);await file.save(path.join(out,'scanned-table-demo.xlsx'));
