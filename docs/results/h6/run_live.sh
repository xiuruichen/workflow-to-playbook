#!/bin/bash
# H6: real recorder, real mouse. Sequential. Logs the exact window in which the mouse is taken over.
cd "C:/Users/chenf/OneDrive/Desktop/tacit knowledge"
for spec in "live_triage_test.py 40 1 triage" "live_dashboard_test.py 40 1 dashboard"; do
  set -- $spec
  echo "$(date '+%F %T') START $4 seed $3" >> docs/results/h6/windows.log
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/$1 $2 $3 > docs/results/h6/$4_seed$3.log 2>&1
  echo "$(date '+%F %T') END $4 seed $3 (exit $?)" >> docs/results/h6/windows.log
  d=$(grep -o "Full results: .*live_results.json" docs/results/h6/$4_seed$3.log | sed 's/Full results: //')
  [ -n "$d" ] && cp "$d" docs/results/h6/$4_seed$3_results.json
done
