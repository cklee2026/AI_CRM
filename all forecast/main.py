#!/usr/bin/env python
"""
Food Price Tracker - Main Entry Point
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.cli import cli

if __name__ == '__main__':
    cli()
