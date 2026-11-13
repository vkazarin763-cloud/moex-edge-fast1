name: Finam Executor

on:
  workflow_dispatch:

jobs:
  execute:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install deps
        run: pip install pandas requests
      - name: Run Finam Executor
        env:
          FINAM_API_SECRET: ${{ secrets.FINAM_API_SECRET }}
          FINAM_ACCOUNT_ID: ${{ secrets.FINAM_ACCOUNT_ID }}
        run: python finam_executor.py
