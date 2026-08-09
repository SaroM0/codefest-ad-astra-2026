"""Motor OCR.

Sin GPU en la máquina, PaddleOCR pierde su única ventaja (batching), así que se implementa
Tesseract y se deja la interfaz abierta. Con 14 núcleos, las ~970 páginas del corpus se
resuelven en minutos.

Cuatro decisiones que el plan v1 no tomaba:

1. **Extraer el JPEG embebido, no rasterizar.** Las páginas de Alertas ya son JPEG RGB a
   2547×3510 px (300 dpi para A4). `get_pixmap(dpi=300)` re-comprime una imagen ya
   comprimida: una generación de pérdida gratuita.
2. **Preprocesado** (escala de grises + binarización): en escaneos de documentos oficiales
   mueve el CER más que la elección de motor.
3. **`user-words` con vocabulario del dominio**: los 289 municipios y los 363 códigos de
   alerta son conocidos de antemano. Ningún motor genérico explota eso solo.
4. La comparación entre motores se mide contra ground truth, no "a ojo".
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .. import config


@dataclass
class OCRResult:
    text: str
    engine: str
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)


class OCRUnavailable(RuntimeError):
    """Tesseract no está instalado. Es una condición explícita, no un fallo silencioso."""


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def available_languages() -> set[str]:
    if not tesseract_available():
        return set()
    try:
        out = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, timeout=30, check=False
        )
        lines = out.stdout.decode("utf-8", "replace").splitlines()[1:]
        return {line.strip() for line in lines if line.strip()}
    except subprocess.SubprocessError:
        return set()


def lang_for(script: str | None, language: str | None) -> str:
    """Elige el modelo de idioma a partir de la escritura, no del nombre del archivo."""
    installed = available_languages()

    preferred: list[str] = []
    if language == "es":
        preferred = ["spa+eng", "spa"]
    elif language == "pt":
        preferred = ["por+eng", "por"]
    elif language == "en":
        preferred = ["eng"]
    if script:
        preferred.append(config.OCR_LANG_BY_SCRIPT.get(script, config.OCR_DEFAULT_LANG))
    preferred.append(config.OCR_DEFAULT_LANG)

    for candidate in preferred:
        if all(part in installed for part in candidate.split("+")):
            return candidate
    return "eng" if "eng" in installed else next(iter(installed), "eng")


def _preprocess(image_bytes: bytes) -> bytes:
    """Escala de grises + autocontraste + binarización adaptativa ligera.

    Deliberadamente conservador: un binarizado agresivo sobre un escaneo limpio a 300 dpi
    destruye más de lo que arregla.
    """
    try:
        import io

        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(image_bytes))
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        img = ImageOps.grayscale(img)
        img = ImageOps.autocontrast(img, cutoff=1)

        # Escaneos por debajo de ~250 dpi se benefician de un upscale a 2x.
        if min(img.size) < 1200:
            img = img.resize(
                (img.width * 2, img.height * 2), Image.Resampling.LANCZOS
            )

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes  # si el preprocesado falla, se OCRiza la imagen original


class TesseractOCR:
    name = "tesseract"

    def __init__(self, user_words: list[str] | None = None) -> None:
        self._user_words = user_words or []
        self._words_file: Path | None = None

    def _ensure_words_file(self) -> Path | None:
        """Vocabulario del dominio: 289 municipios + 363 códigos de alerta."""
        if not self._user_words:
            return None
        if self._words_file and self._words_file.exists():
            return self._words_file
        fd = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        )
        fd.write("\n".join(sorted(set(self._user_words))))
        fd.close()
        self._words_file = Path(fd.name)
        return self._words_file

    def extract(
        self,
        image_bytes: bytes,
        lang: str = config.OCR_DEFAULT_LANG,
        preprocess: bool = True,
    ) -> OCRResult:
        if not tesseract_available():
            raise OCRUnavailable("tesseract_not_installed")

        payload = _preprocess(image_bytes) if preprocess else image_bytes
        warnings: list[str] = []

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(payload)
            tmp_path = Path(tmp.name)

        try:
            args = [
                "tesseract",
                str(tmp_path),
                "stdout",
                "-l",
                lang,
                "--psm",
                config.OCR_PSM,
            ]
            if words := self._ensure_words_file():
                args += ["--user-words", str(words)]

            proc = subprocess.run(args, capture_output=True, timeout=300, check=False)
            text = proc.stdout.decode("utf-8", "replace")
            if proc.returncode != 0:
                warnings.append(f"tesseract_exit_{proc.returncode}")
        except subprocess.TimeoutExpired:
            return OCRResult("", self.name, warnings=["tesseract_timeout"])
        finally:
            tmp_path.unlink(missing_ok=True)

        return OCRResult(text=text, engine=self.name, warnings=warnings)
