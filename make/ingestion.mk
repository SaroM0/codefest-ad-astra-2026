# Etapa 1 — INGESTA.  Corpus crudo → CanonicalDocument[] validados y trazables.
#
# Variables comunes (PY, CORPUS, OUTPUT, WORKERS, colores) vienen del Makefile raíz.

LOG      := $(OUTPUT)/ingest.log
ING      := $(OUTPUT)/ingestion
DOCS     := $(ING)/documents
REPORTS  := $(ING)/reports
SUMMARY  := $(REPORTS)/summary.json
BIN      := scripts/ingestion

HELP_TARGETS += help-ingestion

.PHONY: help-ingestion ingest ingest-fast ingest-sample resume retry rescore failed \
        check verify audit gold report coverage quarantine warnings stats doc find test

help-ingestion:
	@printf "$(BOLD)Ingesta$(OFF)  $(DIM)corpus → CanonicalDocument[]$(OFF)\n"
	@printf "  make ingest           ingesta completa con OCR      $(DIM)(~60-75 min)$(OFF)\n"
	@printf "  make ingest-fast      ingesta sin OCR               $(DIM)(~5 min)$(OFF)\n"
	@printf "  make ingest-sample    sólo N documentos             $(DIM)(N=120 por defecto)$(OFF)\n"
	@printf "  make resume           relanza en segundo plano y deja el log en $(LOG)\n"
	@printf "  make retry            reprocesa SÓLO los documentos con contraste fallido\n"
	@printf "  make rescore          recalcula CALIDAD sin re-extraer  $(DIM)(minutos)$(OFF)\n"
	@printf "  $(DIM)variables: WORKERS=8  N=120$(OFF)\n"
	@printf "  $(DIM)· · ·$(OFF)\n"
	@printf "  make check            verify + gold + audit  $(DIM)(todo lo que decide si está bien)$(OFF)\n"
	@printf "  make verify           invariantes y reconciliación\n"
	@printf "  make gold             C6: los 15 fragmentos del gold set\n"
	@printf "  make audit            fidelidad de extracción PDF vs poppler\n"
	@printf "  make report           resumen operativo legible\n"
	@printf "  make coverage         matriz de cobertura de verificación\n"
	@printf "  make quarantine       qué no se pudo extraer y por qué\n"
	@printf "  make warnings         avisos agregados\n"
	@printf "  make failed           diagnostica los documentos con contraste fallido\n"
	@printf "  make stats            tamaño y recuento de los artefactos\n"
	@printf "  make test             humo rápido sobre el corpus real, sin escribir nada\n"
	@printf "  make doc ID=F3-ALERTAS-001    un documento en detalle\n"
	@printf "  make find Q=alertas          buscar por ruta o DOC_ID\n"

# ═══════════════════════════════════════════════════════════════════════════════
# Ejecución
# ═══════════════════════════════════════════════════════════════════════════════
ingest: check-env
	@mkdir -p $(OUTPUT)
	$(PY) -m adastra.ingestion.pipeline --corpus "$(CORPUS)" --output $(OUTPUT) --workers $(WORKERS)

ingest-fast: check-env
	@mkdir -p $(OUTPUT)
	$(PY) -m adastra.ingestion.pipeline --corpus "$(CORPUS)" --output $(OUTPUT) \
		--workers $(WORKERS) --no-ocr

N ?= 120
ingest-sample: check-env
	@mkdir -p $(OUTPUT)
	$(PY) -m adastra.ingestion.pipeline --corpus "$(CORPUS)" --output $(OUTPUT) \
		--workers $(WORKERS) --limit $(N) --no-ocr

# La ingesta completa con OCR dura ~1 h. `resume` la lanza desacoplada del terminal para
# que sobreviva a un cierre de sesión, que es lo que la tumbó la primera vez.
resume: check-env
	@mkdir -p $(OUTPUT)
	@nohup $(PY) -m adastra.ingestion.pipeline --corpus "$(CORPUS)" --output $(OUTPUT) \
		--workers $(WORKERS) > $(LOG) 2>&1 & \
	printf "$(GRN)✓ lanzado en segundo plano$(OFF) (PID $$!)\n  log: $(BOLD)tail -f $(LOG)$(OFF)\n"

# Reintento dirigido: reprocesa sólo los DOC_ID con algún contraste fallido, sobre los
# artefactos existentes. Mucho más barato que una corrida completa (~1 h) cuando lo que
# se ha tocado es la lógica de contraste y no la de extracción.
retry: $(SUMMARY)
	@$(PY) $(BIN)/failed_docs.py > $(OUTPUT)/failed.txt
	@printf "$(BOLD)reintentando %s documentos$(OFF)\n" "$$(wc -l < $(OUTPUT)/failed.txt)"
	$(PY) -m adastra.ingestion.pipeline --corpus "$(CORPUS)" --output $(OUTPUT) \
		--workers $(WORKERS) --only @$(OUTPUT)/failed.txt

# Recalcula señales, contrastes y confianza sobre los documentos YA extraídos. Es lo que
# hay que ejecutar cuando cambia la lógica de un contraste: un contraste espurio que
# PASABA también aportó peso al score, así que reprocesar sólo los fallidos deja al resto
# con una confianza calculada sobre evidencia ya inválida.
rescore: $(SUMMARY)
	$(PY) -m adastra.ingestion.pipeline --corpus "$(CORPUS)" --output $(OUTPUT) \
		--workers $(WORKERS) --rescore

failed: $(SUMMARY)
	@$(PY) $(BIN)/failed_docs.py --diagnose

# ═══════════════════════════════════════════════════════════════════════════════
# Revisión
# ═══════════════════════════════════════════════════════════════════════════════
$(SUMMARY):
	@printf "$(RED)No hay artefactos todavía.$(OFF) Ejecuta $(BOLD)make ingest$(OFF) (o make ingest-fast).\n"
	@exit 1

# El objetivo que responde «¿está bien la extracción?».
check: verify gold audit
	@printf "\n$(GRN)$(BOLD)✓ verificación completa superada$(OFF)\n"

verify: $(SUMMARY)
	@$(PY) $(BIN)/report.py summary

report: $(SUMMARY)
	@$(PY) $(BIN)/report.py summary

coverage: $(SUMMARY)
	@$(PY) $(BIN)/report.py coverage

quarantine: $(SUMMARY)
	@$(PY) $(BIN)/report.py quarantine

warnings: $(SUMMARY)
	@$(PY) $(BIN)/report.py warnings

# C6: los 15 fragmentos del gold set deben aparecer literalmente en su documento.
gold: $(SUMMARY)
	@$(PY) $(BIN)/check_gold.py --from-artifacts

# ¿Conserva el texto persistido lo que ve poppler? Falla si se pierde más del 1%.
audit: $(SUMMARY)
	@$(PY) $(BIN)/audit_extraction.py --json $(REPORTS)/extraction_audit.json

ID ?=
doc: $(SUMMARY)
	@test -n "$(ID)" || { printf "$(RED)uso: make doc ID=F3-ALERTAS-001$(OFF)\n"; exit 1; }
	@$(PY) $(BIN)/report.py doc $(ID)

Q ?=
find: $(SUMMARY)
	@test -n "$(Q)" || { printf "$(RED)uso: make find Q=alertas$(OFF)\n"; exit 1; }
	@$(PY) $(BIN)/report.py find "$(Q)"

stats:
	@printf "$(BOLD)Artefactos$(OFF)\n"
	@test -d $(DOCS) && printf "  documentos    %s archivos, %s\n" \
		"$$(ls $(DOCS)/*.json 2>/dev/null | wc -l)" "$$(du -sh $(DOCS) | cut -f1)" \
		|| printf "  $(DIM)sin documentos todavía$(OFF)\n"
	@test -f $(ING)/manifest.jsonl && printf "  manifest      %s líneas\n" \
		"$$(wc -l < $(ING)/manifest.jsonl)" || true
	@test -d $(DOCS) && printf "  bloques .jsonl %s documentos grandes\n" \
		"$$(ls $(DOCS)/*.blocks.jsonl 2>/dev/null | wc -l)" || true
	@test -d $(OUTPUT) && printf "  total         %s\n" "$$(du -sh $(OUTPUT) | cut -f1)" || true

# Humo rápido: registry + clasificación + join sobre el corpus real, sin escribir nada.
test: $(PY)
	@$(PY) -c "$$SMOKE_TEST"

export SMOKE_TEST
define SMOKE_TEST
from pathlib import Path
from adastra.ingestion import config
from adastra.ingestion.registry.index_loader import load_index, load_gold_set
from adastra.ingestion.registry.scanner import scan_corpus
from adastra.ingestion.registry.reconciler import reconcile, assert_reconciliation
from adastra.ingestion.classification.roles import classify, assert_classification
from adastra.ingestion.registry.catalog_join import join_catalogs, assert_join

R = Path(config.DEFAULT_CORPUS)
idx = load_index(R / config.MASTER_INDEX, config.INVENTORY_SHEET)
scanned = scan_corpus(R)
rec = reconcile(idx, scanned)
magic = {s.relative_path: s.magic for s in scanned}
for e in rec.entries:
    classify(e, magic.get(e.relative_path, b""))
cats = [e.relative_path for e in rec.entries if e.role == "metadata" and e.extension == ".json"]
disk = [e.relative_path for e in rec.entries if e.role == "retrievable"]
join = join_catalogs(R, cats, disk)
gold = load_gold_set(R / config.GOLD_SET_XLSX)

checks = [
    ("I2  reconciliacion 1826+13+9=1848", not assert_reconciliation(rec, strict=False)),
    ("     clasificacion y magic bytes  ", not assert_classification(rec.entries, strict=False)),
    ("     catalog join 220/219 (99,5%) ", not assert_join(join, strict=False)),
    ("     gold set: 15 pares           ", len(gold) == 15),
]
ok = True
for label, passed in checks:
    print(("  \033[32m/\033[0m " if passed else "  \033[31mX\033[0m ") + label)
    ok = ok and passed
print(("\033[32m OK\033[0m" if ok else "\033[31m FALLA\033[0m"))
raise SystemExit(0 if ok else 1)
endef
