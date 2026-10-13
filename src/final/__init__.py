"""SR9 final integrated client deliverable composition layer (SP22).

Pure-data composition modules. Reads from existing engine modules
(src/reporting.py, src/sra/sra_reporting.py, src/integrated/integrated_reporting.py)
and produces the structured data the final notebook renders.

Modules:
  cross_validator     - Reconciles three engine runs (cost, schedule, integrated)
  composer            - Single nested-dict entry point for notebook rendering
  disclaimer_text     - SR9-scoped methodology constants
  executive_summary   - Top-N drivers, headline range, diversification summary
  word_generator      - Word doc executive summary via document-skills:docx
  final_reporting     - Pure-data accessor functions for notebook consumption

Pass B (notebook + driver + diagnostic) consumes these modules.
"""
