"""Create a gallery image and PDF portfolio sample from archived public data."""
import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/scanned-pdf-sales-sample'
SOURCE=ROOT/'artifacts/scanned-pdf-experiment/assisted-independent-intake-20261122/candidate-images/I01-context.png'
NAVY='#15354D'; INK='#183247'; MUTED='#52677A'; LINE='#DBE4EC'; PALE='#EFF4F8'; AMBER='#FFF0D8'


def build():
    payload=json.loads((OUT/'sample-data.json').read_text()); records=payload['records']; source=Image.open(SOURCE).convert('RGB')
    changed=next(r for r in records if r['changed']); assert len(records)==24 and sum(r['changed'] for r in records)==1
    def crop(r):return Image.open(io.BytesIO(base64.b64decode(r['crop'].split(',',1)[1]))).convert('RGB')
    # Image is composed of real source data, not a generated facsimile.
    im=Image.new('RGB',(1000,750),'#F4F7FA');d=ImageDraw.Draw(im)
    def font(size,bold=False):return ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial'+(' Bold' if bold else '')+'.ttf',size)
    def txt(x,y,t,size=22,bold=False,color=INK):d.text((x,y),t,font=font(size,bold),fill=color)
    txt(54,48,'SCAN TO EXCEL',19,True,MUTED);txt(54,84,'From scanned tables',47,True);txt(54,140,'to checked numbers.',47,True)
    for x in (54,512):d.rounded_rectangle((x,238,x+434,595),radius=16,fill='white',outline=LINE,width=2)
    txt(76,260,'Original scan',24,True);txt(534,260,'Structured output',24,True)
    # Crop with row labels and two numeric columns; no outside logos.
    example=source.crop((80,390,1360,565)); example.thumbnail((390,170));im.paste(example,(76,318))
    d.line((76,310,466,310),fill=LINE,width=2)
    d.rounded_rectangle((534,312,924,365),radius=5,fill=NAVY);txt(547,327,'Item',19,True,'white');txt(803,327,'1940',19,True,'white')
    for i,r in enumerate([r for r in records if r['year']==1940][:4]):
        y=365+i*46
        if i%2==0:d.rectangle((534,y,924,y+46),fill=PALE)
        txt(547,y+12,r['item'],17);value=f'{r["final"]:,}';w=d.textlength(value,font=font(19));txt(910-w,y+11,value,19,True)
    txt(76,543,'Source crop',17,False,MUTED);txt(534,543,'Editable numeric cells',17,False,MUTED)
    d.line((54,632,946,632),fill=LINE,width=2);txt(54,656,'Source locations  •  Review flags  •  Corrections',25,True);txt(54,694,'Public-data demonstration',17,False,MUTED)
    im.save(OUT/'catalog-cover.png')
    # Compact, faithful two-page PDF, readable at normal print scale.
    pdf=canvas.Canvas(str(OUT/'catalog-work-sample.pdf'),pagesize=(612,792));pdf.setTitle('Scanned numerical table - public-data demonstration')
    def t(x,y,s,size=10,bold=False,color=INK):pdf.setFont('Helvetica-Bold' if bold else 'Helvetica',size);pdf.setFillColor(colors.HexColor(color));pdf.drawString(x,y,s)
    def right(x,y,s,size=10,bold=False):pdf.setFont('Helvetica-Bold' if bold else 'Helvetica',size);pdf.setFillColor(colors.HexColor(INK));pdf.drawRightString(x,y,s)
    def rect(x,y,w,h,fill):pdf.setFillColor(colors.HexColor(fill)); proof=pdf.rect(x,y,w,h,stroke=0,fill=1)
    def header(title,sub,n):
        t(40,750,'PUBLIC-DATA DEMONSTRATION',10,True,MUTED);t(40,716,title,27,True);t(40,694,sub,10,False,MUTED);pdf.setStrokeColor(colors.HexColor(LINE));pdf.line(40,678,572,678);t(40,26,'Selected table scope only. Not a customer project or accuracy guarantee.',9,False,MUTED);right(572,26,str(n),9)
    header('Scanned table to Excel','Idaho livestock values | selected columns, USD | source PDF page 4',1)
    t(40,650,'Original table',14,True); source.thumbnail((1040,420));pdf.drawImage(ImageReader(source),40,460,width=532,height=189,preserveAspectRatio=True,anchor='c')
    t(40,435,'Structured data',14,True);rect(40,403,532,24,NAVY)
    for x,label in [(50,'Item'),(300,'1940'),(403,'1935'),(506,'1920')]:t(x,411,label,10,True,'#FFFFFF')
    items=list(dict.fromkeys(r['item'] for r in records)); years=(1940,1935,1920)
    for i,item in enumerate(items):
        y=379-i*25
        if i%2==0:rect(40,y-6,532,25,PALE)
        t(50,y+2,item,10)
        for x,year in zip((360,463,562),years):right(x,y+2,f'{next(r["final"] for r in records if r["item"]==item and r["year"]==year):,}',10)
    t(40,161,'Source: U.S. Census Bureau, 1940 Agriculture, Vol. II, Idaho, State Table 18.',9,False,MUTED)
    t(40,143,'Values are archived human-reviewed readings from a prior research pilot.',9,False,MUTED)
    t(40,115,'24 selected cells   |   13 initial review flags   |   1 changed value',12,True)
    pdf.showPage()
    header('Source-linked quality review','Illustration of a flagged number and the final reviewed value',2)
    t(40,650,'Example correction',14,True);t(40,624,'Sheep and lambs | 1920 | PDF page 4 | scope R5C3',11,False,MUTED)
    rect(40,463,532,142,PALE);t(55,581,'Original numeric crop',10,True,MUTED);pdf.drawImage(ImageReader(crop(changed)),58,495,width=496,height=65,preserveAspectRatio=True,anchor='c')
    rect(40,365,258,76,PALE);rect(314,365,258,76,AMBER);t(54,414,'Initial read',10,False,MUTED);t(328,414,'Archived reviewed value',10,True,MUTED);t(54,382,f'{changed["initial"]:,}',23,True);t(328,382,f'{changed["final"]:,}',23,True)
    t(40,323,'What the deliverable records',14,True)
    for i,(label,detail) in enumerate([('Source location','PDF page, selected row and column, original crop.'),('Reader triage','Conflicting or low-confidence readings flagged for review.'),('Reviewed result','Final value and whether it differs from the initial read.'),('Unresolved figures','Flagged explicitly rather than guessed.')]):
        y=291-i*48;t(40,y,label,11,True);t(40,y-17,detail,10,False,MUTED)
    t(40,78,'Customer work requires human checking of every selected cell.',10,True);t(40,62,'Sample is a repackaging of archived research; not an independent benchmark.',9,False,MUTED)
    pdf.showPage();pdf.save()
    assert (OUT/'catalog-work-sample.pdf').stat().st_size<2_000_000
    assert (OUT/'catalog-cover.png').stat().st_size<10_000_000


if __name__=='__main__':build()
