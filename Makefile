PYTHON ?= python3
REPORT := src/display_report_card.py

.PHONY: test report-samples report-samples-advanced

test:
	$(PYTHON) -m py_compile src/display_report_card.py tests/test_display_report_card.py
	$(PYTHON) -m unittest discover -s tests

report-samples:
	mkdir -p out
	$(PYTHON) $(REPORT) --input test-data/12-3-nq1v1 --output out/12-3-report-card.png
	$(PYTHON) $(REPORT) --input test-data/15-6-0od --output out/15-6-report-card.png

report-samples-advanced:
	mkdir -p out
	$(PYTHON) $(REPORT) --input test-data/15-6-0od --output out/15-6-report-card-advanced.png --render advanced
