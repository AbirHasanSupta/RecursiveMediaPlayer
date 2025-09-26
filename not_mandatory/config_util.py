import os
import json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=4)
        f.flush()
        os.fsync(f.fileno())

