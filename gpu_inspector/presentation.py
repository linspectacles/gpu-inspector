"""Pure inventory search/sort helpers (no UI or acquisition side effects)."""
from __future__ import annotations

import re

NUMERIC_COLUMNS = frozenset({
    'pid', 'fd', 'client_id', 'numa', 'iommu', 'major_minor',
    'total', 'shared', 'resident', 'purgeable', 'active',
    'busy_time', 'capacity', 'busy_cycles', 'total_cycles', 'max_frequency',
})
_NUMBER_UNIT = re.compile(r'^\s*([+-]?\d+(?:[.,]\d+)?)\s*([a-zA-Zµ/]+)?\s*$')
_UNITS = {
    'b': 1, 'bytes': 1, 'kib': 1024, 'mib': 1024**2, 'gib': 1024**3,
    'tib': 1024**4, 'kb': 1000, 'mb': 1000**2, 'gb': 1000**3,
    'ns': 1, 'us': 1000, 'µs': 1000, 'ms': 1000**2, 's': 1000**3,
    'hz': 1, 'khz': 1000, 'mhz': 1000**2, 'ghz': 1000**3,
    'cycles': 1,
}


def searchable_text(value):
    """Search all acquired metadata, including nested PCI, fdinfo and provenance."""
    if isinstance(value, dict):
        return ' '.join(str(key) + ' ' + searchable_text(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return ' '.join(searchable_text(item) for item in value)
    return '' if value is None else str(value)


def matches_search(record, query):
    return not query or query.casefold() in searchable_text(record).casefold()


def numeric_value(value, column):
    if value is None or value == '' or str(value).casefold() == 'not reported':
        return None
    if column == 'major_minor':
        try:
            a, b = str(value).split(':', 1)
            return (int(a), int(b))
        except (ValueError, TypeError):
            return None
    if isinstance(value, int):
        return value
    raw = str(value).strip().replace(',', '')
    m = _NUMBER_UNIT.fullmatch(raw)
    if not m:
        return None
    number, unit = m.groups()
    multiplier = _UNITS.get((unit or '').lower())
    if unit and multiplier is None:
        return None
    # Keep integer exactness for large cycle counters and byte counts.
    if '.' not in number:
        return int(number) * (multiplier or 1)
    return float(number) * (multiplier or 1)


def sorted_records(records, column, reverse=False):
    """Numeric-aware sorts, with genuinely unreported entries always at end."""
    if column not in NUMERIC_COLUMNS:
        return sorted(records, key=lambda r: str(r.get(column) or '').casefold(), reverse=reverse)
    available, missing = [], []
    for record in records:
        value = numeric_value(record.get(column), column)
        if value is None:
            missing.append(record)
        else:
            available.append((value, record))
    available.sort(key=lambda pair: pair[0], reverse=reverse)
    missing.sort(key=lambda r: str(r.get(column) or '').casefold(), reverse=reverse)
    return [r for _value, r in available] + missing
