#!/usr/bin/env bash
# ==============================================================================
# Quick Start Script for Kids Activity & Safety Monitoring System
# ==============================================================================

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

python3 run.py "$@"
