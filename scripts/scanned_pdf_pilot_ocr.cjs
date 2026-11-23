const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');

async function main() {
    const [model, ...rest] = process.argv.slice(2);
    const mode = rest[0]?.startsWith('--') ? rest[0] : null;
    const images = mode ? rest.slice(1) : rest;
    if (mode && !['--single-line', '--raw-line'].includes(mode)) throw new Error(`Unknown OCR mode: ${mode}`);
    const modules = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES || path.join(
        os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'
    );
    if (!model || !fs.existsSync(model) || !images.length) throw new Error('Missing model or images');
    const { createWorker, PSM } = require(path.join(modules, 'tesseract.js'));
    const worker = await createWorker('eng', 1, {
        langPath: path.dirname(path.resolve(model)), gzip: false, cacheMethod: 'none',
    });
    try {
        const segmentation = mode === '--raw-line' ? PSM.RAW_LINE : mode === '--single-line' ? PSM.SINGLE_LINE : PSM.SPARSE_TEXT;
        await worker.setParameters({ tessedit_pageseg_mode: segmentation });
        for (const image of images) {
            const { data } = await worker.recognize(path.resolve(image), {}, { tsv: true });
            process.stdout.write(JSON.stringify({ image, text: data.text, tsv: data.tsv, confidence: data.confidence }) + '\n');
        }
    } finally {
        await worker.terminate();
    }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
