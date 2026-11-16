"""Structured-output schema must stay inside API limits: no optional params (limit 24),
no union types (limit 16), additionalProperties false everywhere."""
from radar.extract import build_schema


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def test_schema_limits(cfg):
    s = build_schema([p.id for p in cfg.enabled()])
    optional = unions = 0
    for n in walk(s):
        if n.get("type") == "object":
            assert n.get("additionalProperties") is False
            optional += len(set(n.get("properties", {})) - set(n.get("required", [])))
        if isinstance(n.get("type"), list) or "anyOf" in n:
            unions += 1
        for bad in ("minimum", "maximum", "minLength", "maxLength", "multipleOf"):
            assert bad not in n
    assert optional == 0 and unions == 0
