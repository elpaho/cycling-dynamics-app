"""
Jednostavan lokalni config fajl (JSON) za pamcenje defaultnih vrijednosti
(email primatelj, posiljateljev SMTP nalog) izmedju pokretanja aplikacije.
NIJE za git - dodaj u .gitignore jer sadrzi App Password.
"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_config.json")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: dict):
    try:
        existing = load_config()
        existing.update(data)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        print(f"[config] Could not save config: {e}")
