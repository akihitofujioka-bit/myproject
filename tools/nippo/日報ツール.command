#!/bin/zsh
# ダブルクリックで日報ツールのボタン画面を開く（Finder から起動できるように .command にしてある）
cd "$(dirname "$0")"
exec /usr/bin/python3 nippo.py
