"""Orquestador de la ingesta.

    load index → scan → reconcile → classify → CATALOG JOIN → route → extract
    → segment → normalize → script/language → quality (intrínseca + CONTRASTES)
    → gates → validate → persist → manifest → reports

Las dos etapas en mayúsculas son las que la v1 del plan no tenía: sin el catalog join los
760 PDFs quedan sin procedencia web, y sin los contrastes la "calidad" es un float que
nadie ha comprobado.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from adastra.core.jsonl import load_jsonl
from adastra.core.models import (
    CanonicalDocument,
    ContentBlock,
    CorpusEntry,
    DocumentQuality,
    ManifestEntry,
    SourceMetadata,
)
from adastra.core.models.quality import CrossCheck

from . import config
from .classification.roles import assert_classification, classify
from .language.detector import detect
from .normalization.metadata import normalize_date
from .parsers.base import ParseResult
from .persistence.cache import DocumentCache
from .persistence.writer import ArtifactWriter
from .quality import crosschecks as cc
from .quality.confidence import SignalCalibrator, build_confidence, summarize_scores
from .quality.signals import compute_signals
from .quality.validators import validate_corpus, validate_document
from .registry.catalog_join import CatalogRef, assert_join, join_catalogs
from .registry.index_loader import IndexRecord, load_gold_set, load_index
from .registry.reconciler import assert_reconciliation, reconcile
from .registry.scanner import scan_corpus


# =====================================================================================
# Trabajo por documento (se ejecuta en procesos hijos)
# =====================================================================================
def _parse_one(args: tuple) -> dict:
    """Parsea un archivo. Devuelve un dict serializable (cruza frontera de proceso)."""
    corpus_root, relative_path, doc_id, observatory_code, extension, enable_ocr = args
    path = Path(corpus_root) / relative_path
    started = time.perf_counter()

    try:
        result = _dispatch(path, doc_id, observatory_code, extension, enable_ocr)
        status, reason = "success", ""
    except Exception as exc:  # I7: el fallo se registra, no se traga
        return {
            "doc_id": doc_id,
            "status": "failure",
            "status_reason": f"{type(exc).__name__}: {exc}"[:300],
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }

    return {
        "doc_id": doc_id,
        "status": status,
        "status_reason": reason,
        "blocks": [b.model_dump() for b in result.blocks],
        "metadata": result.metadata,
        "metadata_warnings": result.metadata_warnings,
        "warnings": result.warnings,
        "pages_total": result.pages_total,
        "pages_native": result.pages_native,
        "pages_ocr": result.pages_ocr,
        "pages_quarantined": result.pages_quarantined,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def _dispatch(
    path: Path, doc_id: str, observatory_code: str, extension: str, enable_ocr: bool
) -> ParseResult:
    """Format router."""
    if extension == ".pdf":
        from .parsers.pdf.parser import parse_pdf

        return parse_pdf(
            path, doc_id, config.PIPELINE_VERSION, enable_ocr=enable_ocr
        )

    if extension == ".json":
        from .parsers.json.parser import parse_json

        return parse_json(path, doc_id, config.PIPELINE_VERSION, observatory_code)

    if extension in (".csv", ".tsv"):
        if "amazonunderworld" in path.name.lower():
            from .parsers.tabular.amazon_underworld import parse_amazon_underworld

            return parse_amazon_underworld(path, doc_id, config.PIPELINE_VERSION)
        from .parsers.tabular.csv_parser import parse_csv

        return parse_csv(path, doc_id, config.PIPELINE_VERSION)

    if extension == ".xlsx":
        from .parsers.tabular.xlsx_parser import parse_xlsx

        return parse_xlsx(path, doc_id, config.PIPELINE_VERSION)

    if extension == ".txt":
        from .parsers.text import parse_text

        return parse_text(path, doc_id, config.PIPELINE_VERSION)

    if extension in (".jpg", ".jpeg", ".png", ".avif"):
        from .parsers.image import parse_image

        return parse_image(path, doc_id, config.PIPELINE_VERSION)

    if extension == ".pbf":
        from .parsers.pbf import PBFParser

        return PBFParser().parse(path, doc_id, config.PIPELINE_VERSION)

    raise ValueError(f"unsupported_extension:{extension}")


# =====================================================================================
# Pipeline
# =====================================================================================
class Pipeline:
    def __init__(
        self,
        corpus_root: Path,
        output_root: Path,
        workers: int = config.DEFAULT_WORKERS,
        *,
        enable_ocr: bool = True,
        strict: bool = False,
        limit: int | None = None,
        only: set[str] | None = None,
    ) -> None:
        self.corpus = corpus_root
        self.workers = max(1, workers)
        self.enable_ocr = enable_ocr
        self.strict = strict
        self.limit = limit
        self.only = only
        self.writer = ArtifactWriter(output_root)
        self.cache = DocumentCache(self.writer.cache, enabled=False)

        self.entries: list[CorpusEntry] = []
        self.index: dict[str, IndexRecord] = {}
        self.catalog: dict[str, CatalogRef] = {}
        self.gold: list[dict] = []
        self.problems: dict[str, list[str]] = {}
        self._generic_titles: frozenset[str] = frozenset()

    # -- etapas 1-3 --------------------------------------------------------------
    def build_registry(self) -> None:
        records = load_index(self.corpus / config.MASTER_INDEX, config.INVENTORY_SHEET)
        self.index = {r.relative_path: r for r in records}
        scanned = scan_corpus(self.corpus)

        rec = reconcile(records, scanned)
        self.problems["reconciliation"] = assert_reconciliation(rec, strict=self.strict)
        self.entries = rec.entries
        self.writer.write_report("reconciliation.json", rec.as_dict())

        magic = {s.relative_path: s.magic for s in scanned}
        for entry in self.entries:
            classify(entry, magic.get(entry.relative_path, b""))
        self.problems["classification"] = assert_classification(
            self.entries, strict=self.strict
        )

        # Anti-leakage (I10): el gold set y las preguntas se leen a un directorio
        # SEPARADO, fuera de ingestion/documents.
        self._generic_titles = _generic_titles(records)
        self.gold = load_gold_set(self.corpus / config.GOLD_SET_XLSX)
        self.writer.write_evaluation(
            "gold_set.json",
            {"pairs": self.gold, "note": "sólo para verificación; nunca se indexa"},
        )

    def join_catalogs(self) -> None:
        catalogs = [
            e.relative_path
            for e in self.entries
            if e.role == "metadata" and e.extension == ".json"
        ]
        disk = [e.relative_path for e in self.entries if e.role == "retrievable"]
        result = join_catalogs(self.corpus, catalogs, disk)
        self.catalog = result.by_path
        self.problems["catalog_join"] = assert_join(result, strict=self.strict)

        self.writer.write_report(
            "catalog_join.json",
            {
                "total_refs": result.total_refs,
                "resolved": result.resolved,
                "resolution_rate": round(
                    result.resolved / max(result.total_refs, 1), 4
                ),
                "per_catalog": result.per_catalog,
                "failed_downloads": len(result.failed_downloads),
                "documents_with_provenance": len(result.by_path),
            },
        )
        with self.writer.open_jsonl("reports/unresolved_catalog_refs.jsonl") as f:
            for ref in result.unresolved:
                self.writer.write_line(
                    f, {"catalog": ref.catalog, "url": ref.url, "candidate": ref.candidate}
                )
        with self.writer.open_jsonl("reports/failed_downloads.jsonl") as f:
            for item in result.failed_downloads:
                self.writer.write_line(f, item)

    # -- etapas 4-8 --------------------------------------------------------------
    def run(self) -> dict:
        started = time.perf_counter()
        self.build_registry()
        self.join_catalogs()

        targets = [
            e
            for e in self.entries
            if e.role == "retrievable" and e.status == "pending"
        ]
        # Reintento dirigido: se reprocesan sólo los DOC_ID pedidos. El resto conserva
        # su documento anterior, así que `--only` NO debe usarse con --output limpio si
        # se quiere un corpus completo.
        if self.only:
            targets = [e for e in targets if e.doc_id in self.only]
        if self.limit:
            targets = targets[: self.limit]

        print(f"[registry]  {len(self.entries)} archivos, {len(targets)} a procesar")
        print(f"[catalog]   {len(self.catalog)} documentos con procedencia recuperada")

        jobs = [
            (
                str(self.corpus),
                e.relative_path,
                e.doc_id,
                e.observatory_code or "",
                e.extension,
                self.enable_ocr,
            )
            for e in targets
        ]
        by_id = {e.doc_id: e for e in targets}

        parsed: dict[str, dict] = {}
        done = 0
        with ProcessPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(_parse_one, job): job[2] for job in jobs}
            for future in as_completed(futures):
                payload = future.result()
                parsed[payload["doc_id"]] = payload
                done += 1
                if done % 100 == 0 or done == len(jobs):
                    print(f"[parse]     {done}/{len(jobs)}", flush=True)


        return self._finalize(parsed, by_id, started)

    # -- re-scoring: recalcula calidad SIN volver a extraer -----------------------
    def rescore(self) -> dict:
        """Recalcula señales, contrastes y confianza sobre los documentos ya persistidos.

        Existe porque cambiar la lógica de un contraste invalida el `confidence` de TODOS
        los documentos que lo usaban, no sólo de los que suspendían: un contraste espurio
        que pasaba también aportó peso al score. Reprocesar únicamente los fallidos deja
        el resto con una confianza calculada sobre evidencia que ya no es válida.

        Es lo que el plan pedía y el cache por etapas anticipaba: un cambio de la capa de
        calidad debe RE-EVALUAR, nunca re-extraer ni re-OCRizar. Minutos en vez de horas.
        """
        started = time.perf_counter()
        self.build_registry()
        self.join_catalogs()

        parsed: dict[str, dict] = {}
        by_id: dict[str, CorpusEntry] = {}
        missing: list[CorpusEntry] = []

        for entry in self.entries:
            if entry.role != "retrievable" or entry.status != "pending" or not entry.doc_id:
                continue
            payload = self._payload_from_disk(entry.doc_id)
            if payload is None:
                missing.append(entry)
                continue
            parsed[entry.doc_id] = payload
            by_id[entry.doc_id] = entry

        print(f"[rescore]   {len(parsed)} documentos releídos de disco")

        # Lo que no está persistido (documentos que fueron a cuarentena) sí hay que
        # volver a extraerlo: no hay bloques de los que partir.
        if missing:
            print(f"[rescore]   {len(missing)} sin artefacto → se re-extraen")
            jobs = [
                (str(self.corpus), e.relative_path, e.doc_id, e.observatory_code or "",
                 e.extension, self.enable_ocr)
                for e in missing
            ]
            with ProcessPoolExecutor(max_workers=self.workers) as pool:
                for future in as_completed([pool.submit(_parse_one, j) for j in jobs]):
                    payload = future.result()
                    parsed[payload["doc_id"]] = payload
            by_id.update({e.doc_id: e for e in missing if e.doc_id})

        return self._finalize(parsed, by_id, started)

    def _payload_from_disk(self, doc_id: str) -> dict | None:
        """Reconstruye el payload de `_parse_one` a partir del documento persistido."""
        path = self.writer.documents / f"{doc_id}.json"
        if not path.exists():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))

        if ref := doc.get("blocks_ref"):
            blocks = load_jsonl(self.writer.documents / ref)
        else:
            blocks = doc.get("blocks") or []

        # Los campos DERIVADOS por la capa de calidad se descartan para que se
        # recalculen; conservarlos arrastraría el resultado que se quiere corregir.
        metadata = {
            k: v for k, v in (doc.get("metadata") or {}).items()
            if k not in ("matched_alert_code",)
        }
        # `language`/`script` los pone el parser de PDF en metadata y el resto no; se
        # recuperan de `source`, que es donde acabaron persistidos.
        source = doc.get("source") or {}
        metadata.setdefault("language", source.get("language"))
        metadata.setdefault("language_confidence", source.get("language_confidence"))
        metadata.setdefault("script", source.get("dominant_script"))
        metadata.setdefault("script_distribution", source.get("script") or {})

        quality = doc.get("quality") or {}
        return {
            "doc_id": doc_id,
            "status": "success",
            "status_reason": "",
            "blocks": blocks,
            "metadata": metadata,
            "metadata_warnings": doc.get("metadata_warnings") or [],
            "warnings": quality.get("warnings") or [],
            "pages_total": quality.get("pages_total"),
            "pages_native": quality.get("pages_native", 0),
            "pages_ocr": quality.get("pages_ocr", 0),
            "pages_quarantined": quality.get("pages_quarantined", 0),
            "duration_ms": 0,
        }

    # -- etapas 9-15 -------------------------------------------------------------
    def _finalize(
        self, parsed: dict[str, dict], by_id: dict[str, CorpusEntry], started: float
    ) -> dict:
        # Pasada 1: señales, para poder calibrar por percentil dentro de cada grupo
        # (observatorio × escritura). Sin esta pasada previa no hay población contra la
        # que comparar y toda "calibración" sería una constante inventada.
        calibrator = SignalCalibrator()
        prepared: dict[str, dict] = {}

        for doc_id, payload in parsed.items():
            if payload["status"] != "success":
                continue
            entry = by_id[doc_id]
            blocks = [ContentBlock(**b) for b in payload["blocks"]]
            text = "\n\n".join(b.text for b in blocks if b.text)

            meta = payload["metadata"] or {}
            language = meta.get("language")
            script = meta.get("script")
            script_dist = meta.get("script_distribution") or {}
            if language is None:
                language, lang_conf, script_dist, script = detect(text[:200_000])
            else:
                lang_conf = meta.get("language_confidence")

            signals = compute_signals(text, language, script)
            calibrator.observe(entry.observatory or "?", script, signals)
            prepared[doc_id] = {
                "entry": entry,
                "blocks": blocks,
                "text": text,
                "signals": signals,
                "language": language,
                "language_confidence": lang_conf,
                "script": script,
                "script_distribution": script_dist,
                "payload": payload,
            }

        # Pasada 2: contrastes, confianza, validación y escritura.
        gold_by_doc = self._match_gold(prepared)
        alerts_by_code = self._collect_alert_metadata(prepared)

        manifest_handle = self.writer.open_jsonl("manifest.jsonl")
        quarantine_handle = self.writer.open_jsonl("quarantine/quarantine.jsonl")
        warnings_handle = self.writer.open_jsonl("reports/warnings.jsonl")
        failures_handle = self.writer.open_jsonl("reports/failures.jsonl")

        stats = _Stats()
        written = 0

        try:
            for doc_id, payload in parsed.items():
                entry = by_id[doc_id]
                if payload["status"] == "failure":
                    entry.status = "failure"
                    entry.status_reason = payload["status_reason"]
                    self.writer.write_line(
                        failures_handle,
                        {
                            "doc_id": doc_id,
                            "path": entry.relative_path,
                            "reason": payload["status_reason"],
                        },
                    )
                    stats.failures += 1
                    continue

                item = prepared[doc_id]
                doc, blocks = self._build_document(
                    item, gold_by_doc, alerts_by_code, calibrator
                )

                issues = validate_document(doc, blocks)
                if issues:
                    self.writer.write_line(
                        warnings_handle,
                        {"doc_id": doc_id, "invariant_violations": issues},
                    )

                if doc.quality.usable:
                    entry.status = "success"
                    self.writer.write_document(doc, blocks)
                    written += 1
                else:
                    entry.status = "quarantined"
                    entry.status_reason = ";".join(
                        doc.quality.confidence.flags[:3]
                    ) or "low_extraction_confidence"
                    self.writer.write_line(
                        quarantine_handle,
                        {
                            "doc_id": doc_id,
                            "path": entry.relative_path,
                            "reason": entry.status_reason,
                            "confidence": doc.quality.confidence.score,
                            "basis": doc.quality.confidence.basis,
                            "recommended_action": _recommended_action(doc),
                        },
                    )
                    stats.quarantined += 1

                for warning in payload["warnings"]:
                    self.writer.write_line(
                        warnings_handle, {"doc_id": doc_id, "warning": warning}
                    )
                    stats.warnings[warning.split(":")[0]] += 1

                stats.record(entry, doc, payload)
                self.writer.write_line(
                    manifest_handle, _manifest_entry(entry, doc, payload)
                )

            # Los archivos que nunca entraron al parseo también dejan traza (I1, I7).
            for entry in self.entries:
                if entry.doc_id in parsed:
                    continue
                self.writer.write_line(manifest_handle, _skip_manifest(entry))
        finally:
            for handle in (
                manifest_handle,
                quarantine_handle,
                warnings_handle,
                failures_handle,
            ):
                handle.close()

        self.problems["corpus"] = validate_corpus(
            self.entries, written, config.EXPECTED_TOTAL_FILES
        )

        summary = self._summary(stats, written, calibrator, started)
        self.writer.write_report("summary.json", summary)
        self.writer.write_report(
            "quality_coverage.json", stats.coverage_report()
        )
        with self.writer.open_jsonl("registry.jsonl") as f:
            for entry in self.entries:
                self.writer.write_line(f, entry)

        return summary

    # -- construcción del documento canónico -------------------------------------
    def _build_document(
        self,
        item: dict,
        gold_by_doc: dict[str, list[dict]],
        alerts_by_code: dict[str, dict],
        calibrator: SignalCalibrator,
    ) -> tuple[CanonicalDocument, list[ContentBlock]]:
        entry: CorpusEntry = item["entry"]
        payload = item["payload"]
        blocks: list[ContentBlock] = item["blocks"]
        text: str = item["text"]

        record = self.index.get(entry.relative_path)
        ref = self.catalog.get(entry.relative_path)

        published, date_conf, date_warn = normalize_date(ref.date if ref else None)
        metadata_warnings = list(payload["metadata_warnings"])
        if date_warn:
            metadata_warnings.append(date_warn)

        # La fecha propia del documento manda sobre la del catálogo: `alerta_meta`
        # aporta la única fecha ISO ya normalizada del corpus, y los artículos web traen
        # la suya. Sin esta promoción, `source.published_date` quedaría vacía en 363
        # alertas y ~500 artículos, y el filtrado temporal — que es el motivo de existir
        # de este campo — sería inservible.
        own_date = (payload["metadata"] or {}).get("date")
        own_conf = (payload["metadata"] or {}).get("date_confidence")
        if own_date and (published is None or own_conf == "exact"):
            published, date_conf = own_date, (own_conf or "exact")

        source = SourceMetadata(
            phenomenon=entry.phenomenon or "",
            observatory=entry.observatory or "",
            observatory_code=entry.observatory_code or "",
            relative_path=entry.relative_path,
            original_format=(entry.detected_format or entry.extension.lstrip(".")),
            source_url=ref.url if ref else None,
            original_filename=(
                ref.url.rsplit("/", 1)[-1] if ref and "/" in ref.url else None
            ),
            published_date=published,
            date_confidence=date_conf,
            original_title=ref.title if ref else None,
            catalog_source=ref.catalog if ref else None,
            script=item["script_distribution"],
            dominant_script=item["script"],
            language=item["language"],
            language_confidence=item["language_confidence"],
        )

        # --- CONTRASTES ---------------------------------------------------------
        checks: list[CrossCheck] = []

        # C2 — el título esperado aparece en el documento.
        #
        # El nombre de archivo sólo sirve como título de respaldo si de verdad parece un
        # título. En las Alertas es un código (`ALERTAS_001-17-91689`) y en otras fuentes
        # un hash: contrastarlo contra el texto falla siempre y hunde la confianza de 363
        # documentos perfectamente extraídos. Un contraste que no puede pasar no es un
        # contraste, es ruido.
        #
        # C2 tampoco se aplica a documentos tabulares: un dataset no lleva su título
        # dentro del contenido, así que contrastarlo es un error de categoría — falla
        # siempre y castiga a CSV y XLSX perfectamente parseados.
        expected_title = (ref.title if ref else None) or (
            _title_from_filename(record.filename) if record else None
        )
        if entry.extension in (".csv", ".tsv", ".xlsx"):
            expected_title = None
        elif expected_title and re.sub(r"\s+\d+$", "", expected_title) in self._generic_titles:
            expected_title = None

        if check := cc.check_title_match(expected_title, text):
            checks.append(check)

        # C3 — entidades de `alerta_meta` en el texto del PDF escaneado.
        #
        # Se aplica SÓLO a los PDFs, nunca al JSON del que salen los metadatos: comprobar
        # si `alerta_meta` aparece dentro del texto del propio JSON es circular —los
        # metadatos SON la fuente— y además falla legítimamente, porque el código de
        # alerta vive en `alerta_meta` y no en `body_paragraphs`. Aplicarlo al JSON
        # mandaba a cuarentena 181 alertas perfectamente extraídas.
        #
        # El contraste tiene valor precisamente porque el PDF es una fuente INDEPENDIENTE
        # del JSON: si el código y los municipios del JSON aparecen en el texto del
        # escaneo, el OCR funcionó.
        doc_metadata = dict(payload["metadata"] or {})
        if entry.observatory_code == "ALERTAS" and entry.extension == ".pdf":
            matched = _match_alert_pdf(text, alerts_by_code)
            if matched:
                checks.append(cc.check_alert_entities(matched, text))
                doc_metadata["matched_alert_code"] = matched.get("alert_code")
            elif text.strip():
                checks.append(
                    CrossCheck(
                        type="entity_crosscheck",
                        passed=False,
                        score=0.0,
                        detail={"reason": "no_alert_code_found_in_scanned_text"},
                    )
                )

        # C6 — el fragmento del gold set aparece literalmente.
        for pair in gold_by_doc.get(entry.relative_path, []):
            checks.append(cc.check_gold_fragment(pair["fragment"], text))

        confidence = build_confidence(
            item["signals"],
            checks,
            observatory=entry.observatory or "?",
            script=item["script"],
            calibrator=calibrator,
            extra_flags=_flags_from_warnings(payload["warnings"]),
        )

        quality = DocumentQuality(
            confidence=confidence,
            usable=_is_usable(confidence, payload, len(text)),
            pages_total=payload["pages_total"],
            pages_native=payload["pages_native"],
            pages_ocr=payload["pages_ocr"],
            pages_quarantined=payload["pages_quarantined"],
            characters=len(text),
            warnings=payload["warnings"],
        )

        doc = CanonicalDocument(
            doc_id=entry.doc_id or "",
            pipeline_version=config.PIPELINE_VERSION,
            source=source,
            block_count=len(blocks),
            metadata=doc_metadata,
            metadata_warnings=metadata_warnings,
            quality=quality,
            indexing_hint=entry.indexing_hint,
        )
        return doc, blocks

    # -- helpers ------------------------------------------------------------------
    def _match_gold(self, prepared: dict) -> dict[str, list[dict]]:
        """Resuelve las citas del gold set a rutas reales usando la regla de renombrado.

        El gold set cita nombres del servidor (`daio_study2529_guarding...pdf`) y el
        corpus almacena `DAIO_study2529-guarding-...pdf`.
        """
        from .registry.catalog_join import nombre_estandarizado

        by_name: dict[str, str] = {}
        for item in prepared.values():
            entry = item["entry"]
            by_name.setdefault(entry.filename.lower(), entry.relative_path)

        out: dict[str, list[dict]] = defaultdict(list)
        unresolved: list[dict] = []
        for pair in self.gold:
            doc_name = pair.get("document") or ""
            if not doc_name:
                continue
            resolved = by_name.get(doc_name.lower())
            if not resolved:
                for code in config.OBSERVATORY_CODES:
                    candidate = nombre_estandarizado(f"http://x/{doc_name}", code)
                    if hit := by_name.get(candidate.lower()):
                        resolved = hit
                        break
            if resolved:
                out[resolved].append(pair)
            else:
                unresolved.append(pair)

        self.writer.write_evaluation(
            "gold_resolution.json",
            {
                "resolved": sum(len(v) for v in out.values()),
                "unresolved": len(unresolved),
                "unresolved_documents": [p["document"] for p in unresolved],
            },
        )
        return out

    @staticmethod
    def _collect_alert_metadata(prepared: dict) -> dict[str, dict]:
        alerts: dict[str, dict] = {}
        for item in prepared.values():
            meta = item["payload"]["metadata"] or {}
            if code := meta.get("alert_code"):
                alerts[str(code)] = meta
        return alerts

    def _summary(
        self,
        stats: "_Stats",
        written: int,
        calibrator: SignalCalibrator,
        started: float,
    ) -> dict:
        by_status = Counter(e.status for e in self.entries if e.in_index)
        return {
            "pipeline_version": config.PIPELINE_VERSION,
            "duration_s": round(time.perf_counter() - started, 1),
            "corpus": {
                "files_on_disk": len(self.entries),
                "in_master_index": sum(1 for e in self.entries if e.in_index),
                "extras_explained": sum(
                    1 for e in self.entries if not e.in_index and e.role != "noise"
                ),
                "noise": sum(1 for e in self.entries if e.role == "noise"),
            },
            "roles": dict(Counter(e.role for e in self.entries)),
            "status": dict(by_status),
            "status_sum": sum(by_status.values()),
            "documents_written": written,
            "formats": dict(stats.formats),
            "pdf": stats.pdf_report(),
            "languages": dict(stats.languages.most_common()),
            "scripts": dict(stats.scripts.most_common()),
            "schemas": dict(stats.schemas.most_common()),
            "quality": {
                "confidence": summarize_scores(stats.scores),
                "coverage": stats.coverage_report(),
                "calibration_groups": len(calibrator.group_sizes()),
            },
            "warnings": dict(stats.warnings.most_common(20)),
            "invariant_problems": {k: v for k, v in self.problems.items() if v},
            "ocr_available": stats.ocr_pages > 0,
        }


# =====================================================================================
# Utilidades
# =====================================================================================
def _is_usable(confidence, payload: dict, characters: int) -> bool:
    """Gate final. Cuarentena = "no confío en esta extracción", no exclusión permanente."""
    if characters == 0:
        # Un documento sin texto sólo es aceptable si lo declara explícitamente.
        return any(
            w.startswith(("empty_list", "pbf_disabled", "information_graphic"))
            for w in payload["warnings"]
        )
    if confidence.basis == "unverified":
        return False
    return confidence.score >= 0.35


def _recommended_action(doc: CanonicalDocument) -> str:
    if doc.quality.pages_quarantined:
        return "ocr"
    if doc.quality.characters == 0:
        return "review"
    return "review"


def _flags_from_warnings(warnings: list[str]) -> list[str]:
    flags = []
    for w in warnings:
        head = w.split(":")[0]
        if head in (
            "ocr_needed_but_unavailable",
            "nul_bytes_cleaned",
            "possible_placeholder__body_too_short",
            "abstract_only__full_text_not_in_corpus",
            "short_document__summary_not_full_report",
            "information_graphic__requires_manual_transcription__ocr_would_lose_",
        ):
            flags.append(head)
    return flags


# Tokens que delatan un nombre de archivo en vez de un título de documento.
_FILENAME_NOISE = frozenset({
    "final", "compressed", "web", "web1", "web2", "web3", "web4", "layout",
    "draft", "copy", "rev", "rev1", "rev2", "rev3", "v1", "v2", "v3",
    "update", "updated", "print", "digital", "hr", "lr", "full", "report1",
})

# El código de alerta precedido de su contexto. El OCR maltrata "N°" de muchas formas
# ("N9", "No", "Nro", "N °"), así que el marcador se deja laxo pero la ANCLA es la
# expresión "alerta temprana" o un indicador de número inmediatamente antes del código.
_ALERT_CODE_CONTEXT = re.compile(
    r"(?:alerta[s]?\s+temprana[s]?|\bA\.?\s?T\.?\b)"
    r"[^\n]{0,60}?"
    r"(?<![\d-])(?P<num>\d{1,3})\s?[-–—]\s?(?P<year>\d{2})(?![\d-])",
    re.IGNORECASE,
)

# Sin contexto, pero exigiendo guion sin espacios: descarta la dirección "16 - 21".
_ALERT_CODE_TIGHT = re.compile(
    r"(?:N[o°ºr.]{0,3}\s?)(?<![\d-])(?P<num>\d{1,3})[-–—](?P<year>\d{2})(?![\d-])",
    re.IGNORECASE,
)


def _pad_code(number: str, year: str) -> str:
    """El OCR pierde el cero inicial: `13-18` es en realidad `013-18`."""
    return f"{int(number):03d}-{year}"


def _title_from_filename(filename: str) -> str | None:
    """Convierte un nombre de archivo en título esperado, o None si no lo parece.

    `DAIO_study2529-guarding-the-alliances-eastern-front.pdf` sí es un título.
    `ALERTAS_001-17-91689.json` es un identificador: devolver None evita un contraste
    que no puede pasar.
    """
    stem = filename.rsplit(".", 1)[0]
    # Se quita el prefijo del observatorio, que nunca aparece en el texto del documento.
    stem = re.sub(r"^[A-Z0-9]{3,12}[_-]", "", stem)
    words = [w for w in re.split(r"[-_\s]+", stem) if w]
    if not words:
        return None

    # Marca de fábrica de un nombre de archivo, no de un título: prefijo de fecha
    # compacta (`032321`, `190626`), sufijos de versión y de proceso.
    if re.match(r"^\d{5,8}$", words[0]):
        return None
    if any(w.lower() in _FILENAME_NOISE for w in words):
        return None
    # Apellidos concatenados por el scraper: `harrisonjohnsonyoung`,
    # `defenseagainstdarkartsinspace`. Ninguna palabra real tiene 16+ letras seguidas.
    if any(len(w) >= 16 and w.isalpha() for w in words):
        return None

    real = [w for w in words if len(w) >= 4 and not w.isdigit() and any(c.isalpha() for c in w)]
    if len(real) < 3:
        return None

    return " ".join(words)


def _generic_titles(records, threshold: int = 3) -> frozenset[str]:
    """Títulos derivados que comparten demasiados documentos: no son títulos.

    El scraper de CSET puso el título genérico de la página ("Center for Security and
    Emerging Technology") a los 47 archivos sin título propio — de ahí salen las
    colisiones de basename del análisis. En vez de codificar el caso, se detecta la
    propiedad que lo define: un título que se repite en 3 o más documentos no identifica
    a ninguno, así que contrastarlo es ruido.
    """
    counts: Counter[str] = Counter()
    for record in records:
        if title := _title_from_filename(record.filename):
            # Se ignora el sufijo numérico que el scraper añade para desambiguar.
            counts[re.sub(r"\s+\d+$", "", title)] += 1
    return frozenset(t for t, n in counts.items() if n >= threshold)


def _match_alert_pdf(text: str, alerts: dict[str, dict]) -> dict | None:
    """Empareja un PDF de alerta con su JSON buscando el código en el texto.

    Los PDFs se llaman `ALERTAS_informesNNN.pdf` y los JSON
    `ALERTAS_{codigo}-{detail_id}.json`: NO hay pareo por nombre. El código sólo aparece
    dentro del escaneo, así que este emparejamiento sólo funciona después del OCR — y
    por eso mismo es la métrica de calidad del OCR.
    """
    if not text.strip():
        return None

    head = text[:20000]
    candidates: list[str] = []

    # 1) Código CON CONTEXTO. Imprescindible: un patrón suelto `\d{1,3}\s*-\s*\d{2}`
    #    casa con la dirección del membrete de la Defensoría ("Carrera 9 no. 16 - 21"),
    #    que aparece en todos sus documentos. Esa relajación llegó a asignar el código
    #    `016-21` a 24 documentos distintos — imposible, cada alerta es única.
    for match in _ALERT_CODE_CONTEXT.finditer(head):
        candidates.append(_pad_code(match.group("num"), match.group("year")))

    # 2) Sin contexto pero SIN espacios alrededor del guion: `013-18` sí, `16 - 21` no.
    if not candidates:
        for match in _ALERT_CODE_TIGHT.finditer(head):
            candidates.append(_pad_code(match.group("num"), match.group("year")))

    # 3) Validación por segunda entidad: el municipio de la alerta candidata tiene que
    #    aparecer también en el texto. Así el emparejador se autovalida y no emite un
    #    `matched_alert_code` incorrecto, que sería peor que no emitir ninguno.
    from .quality.crosschecks import _norm

    normalized = _norm(head)
    fallback: dict | None = None
    for code in candidates:
        alert = alerts.get(code)
        if alert is None:
            continue
        municipalities = alert.get("municipalities") or []
        if not municipalities:
            fallback = fallback or alert
            continue
        if any(_norm(m.get("municipality") or "") in normalized for m in municipalities):
            return alert
        fallback = fallback or alert

    return fallback


def _manifest_entry(
    entry: CorpusEntry, doc: CanonicalDocument, payload: dict
) -> ManifestEntry:
    return ManifestEntry(
        doc_id=entry.doc_id,
        relative_path=entry.relative_path,
        role=entry.role,
        input_format=entry.extension.lstrip("."),
        detected_format=entry.detected_format,
        status=entry.status,
        status_reason=entry.status_reason,
        pages=doc.quality.pages_total,
        native_pages=doc.quality.pages_native,
        ocr_pages=doc.quality.pages_ocr,
        blocks=doc.block_count,
        characters=doc.quality.characters,
        language=doc.source.language,
        dominant_script=doc.source.dominant_script,
        extraction_confidence=doc.quality.confidence.score,
        confidence_basis=doc.quality.confidence.basis,
        warnings=payload["warnings"][:10],
        duration_ms=payload["duration_ms"],
    )


def _skip_manifest(entry: CorpusEntry) -> ManifestEntry:
    return ManifestEntry(
        doc_id=entry.doc_id,
        relative_path=entry.relative_path,
        role=entry.role,
        input_format=entry.extension.lstrip("."),
        detected_format=entry.detected_format,
        status=entry.status,
        status_reason=entry.status_reason or entry.role_reason,
    )


class _Stats:
    def __init__(self) -> None:
        self.formats: Counter[str] = Counter()
        self.languages: Counter[str] = Counter()
        self.scripts: Counter[str] = Counter()
        self.schemas: Counter[str] = Counter()
        self.warnings: Counter[str] = Counter()
        self.basis: Counter[str] = Counter()
        self.scores: list[float] = []
        self.pages_total = 0
        self.pages_native = 0
        self.ocr_pages = 0
        self.pages_needing_ocr = 0
        self.layout_pages = 0
        self.reading_order_pages = 0
        self.tabular_pages = 0
        self.tagged_docs = 0
        self.failures = 0
        self.quarantined = 0

    def record(self, entry: CorpusEntry, doc: CanonicalDocument, payload: dict) -> None:
        self.formats[entry.detected_format or "?"] += 1
        if doc.source.language:
            self.languages[doc.source.language] += 1
        if doc.source.dominant_script:
            self.scripts[doc.source.dominant_script] += 1
        meta = payload["metadata"] or {}
        self.schemas[meta.get("schema", "?")] += 1
        self.basis[doc.quality.confidence.basis] += 1
        self.scores.append(doc.quality.confidence.score)

        if doc.quality.pages_total:
            self.pages_total += doc.quality.pages_total
            self.pages_native += doc.quality.pages_native
            self.ocr_pages += doc.quality.pages_ocr
            self.pages_needing_ocr += doc.quality.pages_quarantined
            self.layout_pages += meta.get("pages_layout_mode", 0)
            self.reading_order_pages += meta.get("pages_reading_order_mode", 0)
            self.tabular_pages += meta.get("pages_tabular", 0)
            if meta.get("is_tagged"):
                self.tagged_docs += 1

    def pdf_report(self) -> dict:
        return {
            "pages_total": self.pages_total,
            "pages_native": self.pages_native,
            "pages_ocr_applied": self.ocr_pages,
            "pages_flagged_for_ocr_not_applied": self.pages_needing_ocr,
            "pages_reading_order_mode": self.reading_order_pages,
            "pages_layout_mode": self.layout_pages,
            "pages_tabular": self.tabular_pages,
            "tagged_documents": self.tagged_docs,
        }

    def coverage_report(self) -> dict:
        """Matriz de cobertura de verificación. La última cifra es la más honesta."""
        strong = self.basis["entity_crosscheck"] + self.basis["gold_fragment"]
        weak = (
            self.basis["ocr_agreement"]
            + self.basis["title_match"]
            + self.basis["mirror_match"]
        )
        return {
            "verified_strong_crosscheck": strong,
            "verified_weak_crosscheck": weak,
            "intrinsic_signals_only": self.basis["intrinsic_only"],
            "unverified": self.basis["unverified"],
            "by_basis": dict(self.basis),
        }


# =====================================================================================
# CLI
# =====================================================================================
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingesta CORPUS CODEFEST AD ASTRA 2026")
    parser.add_argument("--corpus", type=Path, default=config.DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--workers", type=int, default=config.DEFAULT_WORKERS)
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument(
        "--strict", action="store_true", help="las invariantes fallan en vez de avisar"
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="recalcula calidad sobre los documentos ya extraídos, sin re-extraer",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="reprocesa sólo estos DOC_ID (lista separada por comas, o @archivo)",
    )
    args = parser.parse_args(argv)

    if not args.corpus.exists():
        print(f"Corpus no encontrado: {args.corpus}", file=sys.stderr)
        return 2

    only: set[str] | None = None
    if args.only:
        if args.only.startswith("@"):
            only = {
                line.strip()
                for line in Path(args.only[1:]).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            }
        else:
            only = {x.strip() for x in args.only.split(",") if x.strip()}
        print(f"[only]      reintento dirigido sobre {len(only)} documentos")

    pipeline = Pipeline(
        args.corpus,
        args.output,
        workers=args.workers,
        enable_ocr=not args.no_ocr,
        strict=args.strict,
        limit=args.limit,
        only=only,
    )
    summary = pipeline.rescore() if args.rescore else pipeline.run()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 1 if summary["invariant_problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
