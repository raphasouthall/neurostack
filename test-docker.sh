#!/usr/bin/env bash
set -e

echo "=== OS ==="
cat /etc/os-release | head -3

echo "=== Python ==="
python3 --version

echo "=== FTS5 check ==="
python3 -c "import sqlite3; conn = sqlite3.connect(':memory:'); conn.execute('CREATE VIRTUAL TABLE t USING fts5(c)'); print('FTS5: OK')"

echo "=== Install deps ==="
apt-get update -qq && apt-get install -y -qq git pip > /dev/null 2>&1

echo "=== pip install (lite) ==="
cd /opt/neurostack
pip install --quiet -e . 2>&1 | tail -5

echo "=== CLI: status ==="
python3 -m neurostack.cli status

echo "=== CLI: init ==="
python3 -m neurostack.cli init /tmp/test-vault

echo "=== CLI: doctor ==="
python3 -m neurostack.cli doctor || true

echo "=== CLI: index ==="
python3 -m neurostack.cli --vault /tmp/test-vault index --skip-summary --skip-triples 2>&1 | head -20

echo "=== CLI: stats ==="
python3 -m neurostack.cli stats

echo "=== CLI: search ==="
python3 -m neurostack.cli search "test" 2>&1 | head -10

echo "=== Install size ==="
pip show neurostack 2>/dev/null | grep -i location
du -sh "$(python3 -c 'import neurostack; import os; print(os.path.dirname(neurostack.__file__))')" 2>/dev/null || true

echo "=== SMOKE TEST COMPLETE ==="
