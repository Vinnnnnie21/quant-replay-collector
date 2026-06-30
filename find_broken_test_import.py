#!/usr/bin/env python3
"""
Phase 4 - Instrument: Find which test file causes the crash
"""
import sys
from pathlib import Path
import importlib.util

# Setup paths
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "quant_collector_app"))

# Set Qt platform before any imports
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

test_dir = repo_root / "tests"
test_files = sorted(test_dir.glob("test_*.py"))

print(f"Found {len(test_files)} test files")
print("=" * 80)

failed_imports = []
for i, test_file in enumerate(test_files, 1):
    module_name = test_file.stem
    print(f"[{i}/{len(test_files)}] Importing {module_name}...", end=" ")

    try:
        spec = importlib.util.spec_from_file_location(module_name, test_file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            print("✓ OK")
    except Exception as e:
        print(f"✗ FAILED")
        print(f"  Error: {type(e).__name__}: {e}")
        failed_imports.append((test_file.name, e))
        print()

print("=" * 80)
if failed_imports:
    print(f"\n{len(failed_imports)} test file(s) failed to import:")
    for filename, error in failed_imports:
        print(f"  - {filename}: {type(error).__name__}: {error}")
    sys.exit(1)
else:
    print("\n✓ All test files imported successfully!")
    sys.exit(0)
