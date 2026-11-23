"""Create full table-context packets for an already-adjudicated development set."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from scripts.scanned_pdf_image_input_review import BASE, SPECS
from src.scanned_pdf_experiment.holdout_review import sha


def build(packet):
    manifest=json.loads((packet/'reviewer/manifest.json').read_text())
    out=packet/'context-reread-v1';out.mkdir(exist_ok=False)
    maps={s['id']:s for s in manifest['scopes']}; records=[]
    font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',24)
    for sid,page,scope,columns,centers,headers,overview in SPECS:
        s=maps[sid]; original=packet/'reviewer'/f'{sid}-page-{page}.png'
        if sha(original)!=s['render_sha256']:raise ValueError('Source render changed')
        im=Image.open(original).convert('RGB');preview=Image.open(BASE/'image-input-preview'/f'{sid}-page-{page}.png');sx,sy=im.width/preview.width,im.height/preview.height
        # Preserve all row labels, column headers, intervening rows and numbers.
        # Include extra margin at the bottom; markers never cover original pixels.
        left,top,right,bottom=overview;box=(round(left*sx),round(top*sy),round(right*sx),min(im.height,round((bottom+20)*sy)))
        crop=im.crop(box); canvas=Image.new('RGB',(crop.width+80,crop.height+50),'white');canvas.paste(crop,(80,50));d=ImageDraw.Draw(canvas)
        for i,y in enumerate(centers):
            py=round(y*sy)-box[1]+50
            d.text((4,py-13),f'R{i+1}',font=font,fill='#164e86');d.line((43,py,76,py),fill='#164e86',width=2)
        for j,(l,r) in enumerate(columns):
            x=round((l+r)*sx/2)-box[0]+80;d.text((x-13,5),f'C{j+1}',font=font,fill='#164e86')
        path=out/f'{sid}-context.png';canvas.save(path)
        records.append({'id':sid,'image':path.name,'image_sha256':sha(path),'source_render_sha256':sha(original),'row_indices':list(range(8)),'column_indices':list(range(3))})
    (out/'packet-index.json').write_text(json.dumps({'status':'RETROSPECTIVE_DEVELOPMENT_CONTEXT','records':records},indent=2))


if __name__=='__main__':build(BASE/'image-input-review-v2')
