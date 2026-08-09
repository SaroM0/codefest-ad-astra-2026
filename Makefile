# Ad Astra — pipeline RAG sobre el CORPUS CODEFEST AD ASTRA 2026
#
#   make            lista los objetivos
#   make setup      prepara el entorno
#   make ingest     ejecuta la ingesta completa
#   make check      verifica que la extracción es correcta
#
# Este fichero sólo contiene lo COMÚN a las cuatro etapas. Los objetivos de cada etapa
# viven en `make/<etapa>.mk` — así cuatro personas pueden trabajar en paralelo sin
# pelearse por las mismas líneas.
#
# El `python3` del sistema es 3.14 y aún no hay wheels estables de PyMuPDF/openpyxl para
# esa versión: todo va contra el venv de 3.11 que crea `make setup`.

SHELL          := /bin/bash
.DEFAULT_GOAL  := help
.SHELLFLAGS    := -eu -o pipefail -c

PYTHON_VERSION := 3.11
VENV           := .venv
PY             := $(VENV)/bin/python
CORPUS         := CORPUS CODEFEST AD ASTRA 2026
OUTPUT         := artifacts
WORKERS        ?= 8

BOLD := \033[1m
DIM  := \033[2m
GRN  := \033[32m
YLW  := \033[33m
RED  := \033[31m
OFF  := \033[0m

# Cada etapa añade su objetivo de ayuda a esta lista.
HELP_TARGETS :=

include make/ingestion.mk
-include make/chunking.mk make/embeddings.mk make/retrieval.mk

.PHONY: help setup ocr check-env clean clean-artifacts clean-all

# ═══════════════════════════════════════════════════════════════════════════════
help: $(HELP_TARGETS)
	@printf "\n$(BOLD)Común$(OFF)\n"
	@printf "  make setup            crea el venv de Python $(PYTHON_VERSION) e instala dependencias\n"
	@printf "  make ocr              instala el motor OCR (RapidOCR, sin sudo)\n"
	@printf "  make check-env        comprueba que están poppler, el venv y el corpus\n"
	@printf "  make clean-artifacts  borra $(OUTPUT)/\n"
	@printf "  make clean-all        borra también el venv\n"

# ═══════════════════════════════════════════════════════════════════════════════
# Entorno
# ═══════════════════════════════════════════════════════════════════════════════
$(PY):
	@command -v uv >/dev/null || { printf "$(RED)uv no está instalado: https://docs.astral.sh/uv/$(OFF)\n"; exit 1; }
	uv venv --python $(PYTHON_VERSION) $(VENV)

# Las dependencias están declaradas en pyproject.toml, no aquí: instalar el paquete
# tiene que bastar para tener el entorno correcto.
setup: $(PY)
	uv pip install --python $(PY) -e .
	@printf "$(GRN)✓ entorno listo$(OFF)  ·  ejecuta $(BOLD)make ocr$(OFF) para habilitar OCR\n"

# RapidOCR (PaddleOCR sobre ONNX Runtime): sólo pip, sin permisos de administrador.
# Sin GPU no hay ventaja en Paddle nativo, así que es el motor por defecto.
ocr: $(PY)
	uv pip install --python $(PY) -e ".[ocr]"
	@$(PY) -c "from adastra.ingestion.ocr.rapid import best_available_engine as b; \
	           print('motor OCR:', type(b()).__name__)"

check-env:
	@printf "$(BOLD)Entorno$(OFF)\n"
	@test -x "$(PY)" && printf "  $(GRN)✓$(OFF) venv          $$($(PY) -V)\n" \
	                 || printf "  $(RED)✗$(OFF) venv          falta — ejecuta 'make setup'\n"
	@command -v pdftotext >/dev/null && printf "  $(GRN)✓$(OFF) poppler       $$(pdftotext -v 2>&1 | head -1)\n" \
	                                 || printf "  $(RED)✗$(OFF) poppler       falta — sudo apt install poppler-utils\n"
	@test -d "$(CORPUS)" && printf "  $(GRN)✓$(OFF) corpus        $$(find "$(CORPUS)" -type f | wc -l) archivos\n" \
	                     || printf "  $(RED)✗$(OFF) corpus        no se encuentra «$(CORPUS)»\n"
	@test -x "$(PY)" && $(PY) -c "from adastra.ingestion.ocr.rapid import best_available_engine as b; \
	    e=b(); print('  \033[32m✓\033[0m OCR           '+type(e).__name__) if e else \
	    print('  \033[33m!\033[0m OCR           no disponible — ejecuta make ocr')" 2>/dev/null || true
	@printf "  $(DIM)núcleos: $$(nproc)   RAM libre: $$(free -g | awk '/^Mem:/{print $$7}') GB$(OFF)\n"

# ═══════════════════════════════════════════════════════════════════════════════
clean: clean-artifacts
clean-artifacts:
	rm -rf $(OUTPUT)
	@printf "$(GRN)✓ artefactos borrados$(OFF)\n"

clean-all: clean-artifacts
	rm -rf $(VENV) src/*.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@printf "$(GRN)✓ entorno borrado$(OFF)\n"
