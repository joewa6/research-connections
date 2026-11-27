#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
RESEARCH_CONDA_BIN="${CONDA_EXE:-}"
if [ -z "$RESEARCH_CONDA_BIN" ]; then
    for candidate in /opt/miniconda3/bin/conda "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda"; do
        if [ -x "$candidate" ]; then
            RESEARCH_CONDA_BIN="$candidate"
            break
        fi
    done
fi
if [ -z "$RESEARCH_CONDA_BIN" ] || [ ! -x "$RESEARCH_CONDA_BIN" ]; then
    echo "Conda was not found. See README.md for startup instructions."
    exit 1
fi
exec "$RESEARCH_CONDA_BIN" run --no-capture-output -n "${RESEARCH_CONDA_ENV:-base}" python playground/server.py --open-browser
