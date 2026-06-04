#!/usr/bin/env python3
"""CLI interactif KPI. Utilise le même Python que ce fichier (lance avec ./venv/bin/python3)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.pipeline.pipeline import process_question


def main():
    print("Chat KPI (exit pour quitter)")
    while True:
        q = input("Question > ").strip()
        if q.lower() in ("exit", "quit", "q"):
            break
        print(process_question(q))


if __name__ == "__main__":
    main()
