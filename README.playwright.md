# Playwright + Edge setup

This branch adds a config refactor and a sample Playwright launcher to prefer Microsoft Edge.

Quick start:
1. Copy .env.example to .env and fill in your API_HASH and other sensitive values.
2. Install Playwright and browsers: pip install playwright && playwright install
3. Run the sample launcher for testing: python scripts/playwright_edge.py

Notes:
- Use HEADLESS_MODE=False for initial testing; many anti-bot protections are more permissive in a headed session.
- The launcher uses launch_persistent_context to preserve cookies and profiles in EDGE_USER_DATA_DIR.
- Remove legacy CDP/Camoufox settings and migrate browser flows to Playwright (this branch focuses on that).
