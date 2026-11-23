"""Bounded offline single-cell OCR adapter for the agreement policy."""

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from .numeric_reread import Reading, SourceCrop


class LocalCellReader:
    def __init__(self, model: Path, node_modules: Path, node: str = "node"):
        self.model = model.resolve(strict=True)
        self.modules = node_modules.resolve(strict=True)
        self.node = node
        if self.model.name != "eng.traineddata" or not self.model.is_file():
            raise ValueError("A local uncompressed eng.traineddata file is required")
        if not (self.modules / "tesseract.js").is_dir():
            raise ValueError("Local tesseract.js module required")

    def __call__(self, crop: SourceCrop) -> Reading:
        runner = Path(__file__).with_name("local_ocr.cjs")
        with TemporaryDirectory(prefix="research-auto-reread-") as temp:
            path = Path(temp) / "crop.png"
            path.write_bytes(crop.png)
            try:
                process = subprocess.run(
                    [self.node, str(runner), str(self.modules), str(self.model), str(path)],
                    capture_output=True, text=True, timeout=60,
                )
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError("Local OCR timed out") from exc
            if process.returncode:
                raise RuntimeError("Local OCR failed")
            try:
                data = json.loads(process.stdout)
                if not isinstance(data["text"], str):
                    raise ValueError("OCR text must be a string")
                return Reading(data["text"], float(data["confidence"]), crop.digest)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid local OCR result") from exc
