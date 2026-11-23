const path = require('node:path');
const fs = require('node:fs');

async function main() {
    const [modules, model, ...images] = process.argv.slice(2);
    if (!fs.existsSync(model) || path.basename(model) !== 'eng.traineddata') {
        throw new Error('Local model required');
    }
    const { createWorker, PSM } = require(path.join(modules, 'tesseract.js'));
    const worker = await createWorker('eng', 1, {
        langPath: path.dirname(model), gzip: false, cacheMethod: 'none',
    });
    try {
        await worker.setParameters({ tessedit_pageseg_mode: PSM.SINGLE_LINE });
        if (!images.length) throw new Error('Image required');
        const readings = [];
        for (const image of images) {
            const { data } = await worker.recognize(image);
            readings.push({ text: data.text.trim(), confidence: data.confidence });
        }
        process.stdout.write(JSON.stringify(readings.length === 1 ? readings[0] : readings));
    } finally {
        await worker.terminate();
    }
}

main().catch(() => { process.exitCode = 1; });
