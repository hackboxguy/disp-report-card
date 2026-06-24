PYTHON ?= python3
REPORT := src/display_report_card.py
PYTHON_CACHE_DIRS := src/__pycache__ tests/__pycache__
OUT ?= out/compare-report-card.png
LABEL_ARGS := $(if $(BASE_LABEL),--base-label "$(BASE_LABEL)") $(if $(RUN_LABEL),--run-label "$(RUN_LABEL)")
COMPARE_PANELS := $(strip $(or $(PANELS),$(PANEL)))
PANEL_ARGS := $(if $(COMPARE_PANELS),--panels "$(COMPARE_PANELS)")

# Install layout (override PREFIX/DESTDIR for staged or relocated installs)
PREFIX ?= /usr/local
DESTDIR ?=
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib/disp-report-card

.PHONY: test report-samples report-samples-advanced compare clean distclean install uninstall

test:
	$(PYTHON) -m py_compile src/display_report_card.py tests/test_display_report_card.py
	$(PYTHON) -m unittest discover -s tests

report-samples:
	mkdir -p out
	$(PYTHON) $(REPORT) --input test-data/12-3-nq1v1 --output out/12-3-report-card.png
	$(PYTHON) $(REPORT) --input test-data/15-6-0od --output out/15-6-report-card.png

test-data/%: FORCE
	mkdir -p out
	$(PYTHON) $(REPORT) --input $@ --output out/$*-report-card.png

report-samples-advanced:
	mkdir -p out
	$(PYTHON) $(REPORT) --input test-data/15-6-0od --output out/15-6-report-card-advanced.png --render advanced

compare:
	mkdir -p out
	$(PYTHON) $(REPORT) --base-input $(BASE) --input $(RUN) --output $(OUT) $(LABEL_ARGS) $(PANEL_ARGS)

install:
	install -d "$(DESTDIR)$(LIBDIR)"
	install -m 0644 $(REPORT) "$(DESTDIR)$(LIBDIR)/display_report_card.py"
	install -d "$(DESTDIR)$(BINDIR)"
	printf '#!/bin/sh\nexec %s "%s/display_report_card.py" "$$@"\n' "$(PYTHON)" "$(LIBDIR)" > "$(DESTDIR)$(BINDIR)/display-report-card"
	chmod 0755 "$(DESTDIR)$(BINDIR)/display-report-card"

uninstall:
	rm -f "$(DESTDIR)$(BINDIR)/display-report-card"
	rm -rf "$(DESTDIR)$(LIBDIR)"

clean:
	rm -rf out build dist *.egg-info src/*.egg-info $(PYTHON_CACHE_DIRS)
	find . -name '*.pyc' -delete

distclean: clean
	rm -rf .venv

FORCE:
