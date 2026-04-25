"""Pytest configuration: add src/ to sys.path so generate_image, fetch_games, etc. can be imported."""
import sys
import os

# Project root is one level up from this file
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Change CWD to project root so config.yaml / data/*.json paths resolve
os.chdir(PROJECT_ROOT)
