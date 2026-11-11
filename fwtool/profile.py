import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _int(v):
    return int(v, 0) if isinstance(v, str) else v


def load(name_or_path="uc5300p"):
    p = name_or_path if os.path.exists(name_or_path) else os.path.join(HERE, "profiles", name_or_path + ".json")
    with open(p) as fh:
        prof = json.load(fh)
    prof["_dir"] = os.path.dirname(os.path.abspath(p))
    return prof


def num(prof, *keys):
    v = prof
    for k in keys:
        v = v[k]
    return _int(v)


def charmap_path(prof):
    return os.path.join(HERE, "data", prof["charmap"])
