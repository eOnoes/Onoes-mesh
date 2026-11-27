"""Pure static/content checks for a staged local-worker candidate; never executes it."""
import ast
import json

def _fail(n, why):
    return "{}: {}".format(n, why)

def _json_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, dict) and isinstance(b, dict):
        return len(a) == len(b) and all(k in a and _json_equal(a[k], b[k]) for k in b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b

def _unique_json(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value

def _invalid_constant(_):
    raise ValueError('Non-JSON constant')

def evaluate_checks(checks, originals, outputs):
    if not isinstance(checks, list):
        return {"passed": False, "failures": ["1: malformed check list"]}
    failures = []
    for i, check in enumerate(checks, 1):
        if not isinstance(check, dict) or not isinstance(check.get("path"), str):
            failures.append(_fail(i, "malformed check"))
            continue
        data = outputs.get(check["path"])
        if not isinstance(data, (bytes, bytearray)):
            failures.append(_fail(i, "missing or unreadable candidate"))
            continue
        t = check.get("type")
        if t == "text_contains":
            frags = check.get("fragments")
            if (not isinstance(frags, list) or not frags
                    or any(not isinstance(f, str) or not f for f in frags)):
                failures.append(_fail(i, "invalid fragments field"))
                continue
            try:
                text = bytes(data).decode("utf-8")
            except UnicodeDecodeError:
                failures.append(_fail(i, "candidate is not valid UTF-8 text"))
                continue
            if any(f not in text for f in frags):
                failures.append(_fail(i, "required literal fragment missing"))
        elif t == "json_fields":
            fields = check.get("fields")
            if (not isinstance(fields, dict) or not fields
                    or any(not isinstance(k, str) for k in fields)):
                failures.append(_fail(i, "invalid fields field"))
                continue
            try:
                obj = json.loads(bytes(data).decode("utf-8"), object_pairs_hook=_unique_json, parse_constant=_invalid_constant)
            except (UnicodeDecodeError, ValueError):
                failures.append(_fail(i, "candidate is not valid JSON"))
                continue
            if not isinstance(obj, dict):
                failures.append(_fail(i, "candidate JSON is not an object"))
                continue
            for key, want in fields.items():
                if key not in obj or not _json_equal(obj[key], want):
                    failures.append(_fail(i, "JSON field mismatch"))
                    break
        elif t == "preserve_suffix":
            marker = check.get("marker")
            if not isinstance(marker, str) or not marker:
                failures.append(_fail(i, "invalid marker field"))
                continue
            original = originals.get(check["path"])
            if not isinstance(original, (bytes, bytearray)):
                failures.append(_fail(i, "missing or unreadable original"))
                continue
            try:
                m = marker.encode("utf-8")
            except UnicodeEncodeError:
                failures.append(_fail(i, "invalid marker encoding"))
                continue
            if bytes(data).count(m) != 1:
                failures.append(_fail(i, "marker not exactly once in candidate"))
                continue
            if bytes(original).count(m) != 1:
                failures.append(_fail(i, "marker not exactly once in original"))
                continue
            if bytes(data)[bytes(data).index(m):] != bytes(original)[bytes(original).index(m):]:
                failures.append(_fail(i, "suffix after marker changed"))
        elif t == "python_syntax":
            try:
                src = bytes(data).decode("utf-8-sig")
            except UnicodeDecodeError:
                failures.append(_fail(i, "candidate is not valid UTF-8 text"))
                continue
            try:
                ast.parse(src)
            except (SyntaxError, ValueError):
                failures.append(_fail(i, "invalid Python syntax"))
        else:
            failures.append(_fail(i, "unknown check type"))
    return {"passed": not failures, "failures": failures}
