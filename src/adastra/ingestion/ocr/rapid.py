"""Motor OCR basado en RapidOCR (PaddleOCR portado a ONNX Runtime).

Se añade porque Tesseract requiere instalación de sistema (`sudo apt install`) y
RapidOCR se instala con pip y corre en CPU sin dependencias del sistema. Sin GPU, que es
el caso de esta máquina, no hay ventaja en Paddle nativo: ONNX en CPU rinde igual.

Verificado sobre `ALERTAS_informes013.pdf` (escaneo JPEG 300 dpi): recupera el español
legible incluidas las entidades que necesita el contraste C3 — código de alerta,
municipio y departamento.

El motor se elige por disponibilidad: RapidOCR si está instalado, si no Tesseract.
La interfaz es la misma, así que la comparación entre ambos se mide contra ground truth.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

# ONNX Runtime y OpenMP reservan TODOS los núcleos en cada proceso. Con el pipeline
# corriendo 8 workers eso da 8 x 14 = 112 hilos sobre 14 núcleos: medido, dispara el
# load average a 145 y el OCR se vuelve más lento que en un solo proceso.
#
# El paralelismo aquí ya está a nivel de documento (ProcessPoolExecutor), así que cada
# worker debe ser monohilo. Estas variables tienen que fijarse ANTES de importar
# onnxruntime, por eso están en el import del módulo y no en una función.
for _var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "ORT_NUM_THREADS",
):
    os.environ.setdefault(_var, "1")

from .engine import OCRResult, OCRUnavailable, _preprocess  # noqa: E402


@dataclass
class _Lazy:
    """RapidOCR carga ~15 MB de modelos ONNX: se instancia una vez por proceso."""

    engine: object | None = None
    failed: bool = False
    warnings: list[str] = field(default_factory=list)


_STATE = _Lazy()


def rapidocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except ImportError:
        return False


def _get_engine():
    if _STATE.engine is not None:
        return _STATE.engine
    if _STATE.failed:
        raise OCRUnavailable("rapidocr_init_failed")
    try:
        from rapidocr_onnxruntime import RapidOCR

        # Además de las variables de entorno: RapidOCR expone el número de hilos de cada
        # una de sus tres etapas (detección, clasificación, reconocimiento). Fijarlas a 1
        # es lo que de verdad evita la sobre-suscripción, porque ORT crea su pool por
        # sesión y no siempre respeta OMP_NUM_THREADS.
        try:
            _STATE.engine = RapidOCR(
                det_use_cuda=False,
                cls_use_cuda=False,
                rec_use_cuda=False,
                intra_op_num_threads=1,
                inter_op_num_threads=1,
            )
        except TypeError:
            # Versiones antiguas no aceptan esos kwargs: se cae al constructor simple,
            # que al menos hereda las variables de entorno fijadas arriba.
            _STATE.engine = RapidOCR()
        return _STATE.engine
    except Exception as exc:
        _STATE.failed = True
        raise OCRUnavailable(f"rapidocr_unavailable: {exc}") from exc


class RapidOCREngine:
    name = "rapidocr"

    def __init__(self, user_words: list[str] | None = None) -> None:
        # RapidOCR no acepta vocabulario de dominio como Tesseract (`--user-words`);
        # se conserva el parámetro para que la interfaz sea intercambiable y para poder
        # usarlo en una fase de post-corrección si hiciera falta.
        self._user_words = user_words or []

    def extract(
        self,
        image_bytes: bytes,
        lang: str = "es",
        preprocess: bool = True,
    ) -> OCRResult:
        engine = _get_engine()
        payload = _preprocess(image_bytes) if preprocess else image_bytes

        try:
            from PIL import Image
            import numpy as np

            img = Image.open(io.BytesIO(payload))
            if img.mode != "RGB":
                img = img.convert("RGB")
            result, _ = engine(np.array(img))
        except Exception as exc:
            return OCRResult(
                "", self.name, warnings=[f"rapidocr_failed:{type(exc).__name__}"]
            )

        if not result:
            return OCRResult("", self.name, warnings=["rapidocr_no_text"])

        # RapidOCR devuelve [bbox, texto, confianza] por línea detectada, en orden de
        # lectura. Se conservan los saltos de línea: la segmentación posterior los usa.
        lines = [r[1] for r in result if len(r) > 1 and r[1]]
        confidences = [float(r[2]) for r in result if len(r) > 2]
        return OCRResult(
            text="\n".join(lines),
            engine=self.name,
            confidence=(
                round(sum(confidences) / len(confidences), 4) if confidences else None
            ),
        )


def best_available_engine(user_words: list[str] | None = None):
    """Devuelve el motor OCR disponible, o None. La elección queda registrada."""
    if rapidocr_available():
        return RapidOCREngine(user_words)

    from .engine import TesseractOCR, tesseract_available

    if tesseract_available():
        return TesseractOCR(user_words)
    return None
