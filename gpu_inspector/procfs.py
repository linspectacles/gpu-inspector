"""Explicit, non-privileged /proc DRM fdinfo acquisition. No process writes."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import pwd
import stat


def acquired_at():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


def parse_fdinfo(raw):
    """Keep complete raw fdinfo fields, including unknown vendor fields."""
    result = {}
    for line in raw.splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        if key.strip():
            result[key.strip()] = value.strip()
    return result


def process_name(proc_dir):
    try:
        return (proc_dir / 'comm').read_text(errors='replace').strip() or 'Not reported'
    except OSError:
        return 'Not reported'


def engine_names(fields):
    """A reported capacity/cycle/frequency-only engine is still an engine."""
    prefixes = ('drm-engine-capacity-', 'drm-engine-', 'drm-total-cycles-',
                'drm-cycles-', 'drm-maxfreq-')
    names = set()
    for key in fields:
        for prefix in prefixes:
            if key.startswith(prefix) and key[len(prefix):]:
                names.add(key[len(prefix):])
                break
    return sorted(names)


def memory_names(fields):
    names = set()
    for key in fields:
        # drm-total-cycles- is engine evidence, not a memory-region name.
        if key.startswith('drm-total-cycles-'):
            continue
        for prefix in MEMORY_PREFIXES:
            if key.startswith(prefix) and key[len(prefix):]:
                names.add(key[len(prefix):])
                break
    return sorted(names)


def scan_clients(nodes, proc_root=Path('/proc')):
    """Collect visible DRM open FDs, deduplicated by resolved GPU + client ID.

    /proc errors are explicit acquisition failures. Vanished processes and
    vanished descriptors are counted separately from permission denial.
    """
    stamp = acquired_at()
    proc_root = Path(proc_root)
    index = {n['rdev']: n for n in nodes if n.get('rdev') is not None}
    entries = {}
    counters = {'accessible': 0, 'inaccessible': 0, 'vanished': 0,
                'inaccessible_fds': 0, 'vanished_fds': 0, 'fd_errors': 0,
                'seen_processes': 0, 'drm_fds': 0,
                'scan_state': 'Not scanned', 'scan_error': None}
    if not index:
        counters['scan_state'] = 'No usable DRM nodes'
        return [], counters, stamp
    try:
        dirs = sorted((p for p in proc_root.iterdir() if p.name.isdigit()), key=lambda p: int(p.name))
    except OSError as exc:
        counters['scan_state'] = 'Error'
        counters['scan_error'] = f'Unable to enumerate {proc_root}: {type(exc).__name__}: {exc}'
        return [], counters, stamp
    counters['scan_state'] = 'Completed'

    for proc_dir in dirs:
        pid = int(proc_dir.name)
        counters['seen_processes'] += 1
        try:
            fd_entries = list((proc_dir / 'fd').iterdir())
        except FileNotFoundError:
            if proc_dir.exists():
                counters['fd_errors'] += 1
            else:
                counters['vanished'] += 1
            continue
        except PermissionError:
            counters['inaccessible'] += 1
            continue
        except OSError:
            if not proc_dir.exists():
                counters['vanished'] += 1
            else:
                counters['inaccessible'] += 1
            continue
        counters['accessible'] += 1
        comm = process_name(proc_dir)
        cmdline = None
        process_notes = []
        try:
            cmdline = (proc_dir / 'cmdline').read_bytes().replace(b'\0', b' ').decode('utf-8', 'replace').strip()
        except OSError as exc:
            process_notes.append(f'{proc_dir / "cmdline"}: {type(exc).__name__}')
        try:
            owner_uid = proc_dir.stat().st_uid
            owner = pwd.getpwuid(owner_uid).pw_name
        except KeyError:
            owner = None
        except OSError as exc:
            owner_uid, owner = None, None
            process_notes.append(f'{proc_dir}: UID unavailable ({type(exc).__name__})')

        process_vanished = False
        for descriptor in fd_entries:
            if not descriptor.name.isdigit():
                continue
            fd_path = proc_dir / 'fd' / descriptor.name
            fdinfo_path = proc_dir / 'fdinfo' / descriptor.name
            try:
                st = descriptor.stat()
            except FileNotFoundError:
                if not proc_dir.exists():
                    process_vanished = True
                    break
                counters['vanished_fds'] += 1
                continue
            except PermissionError:
                counters['inaccessible_fds'] += 1
                continue
            except OSError:
                if not proc_dir.exists():
                    process_vanished = True
                    break
                counters['fd_errors'] += 1
                continue
            if not stat.S_ISCHR(st.st_mode) or st.st_rdev not in index:
                continue
            node = index[st.st_rdev]
            try:
                raw = fdinfo_path.read_text(encoding='utf-8', errors='replace')
            except FileNotFoundError:
                if not proc_dir.exists():
                    process_vanished = True
                    break
                counters['vanished_fds'] += 1
                continue
            except PermissionError:
                counters['inaccessible_fds'] += 1
                continue
            except OSError:
                if not proc_dir.exists():
                    process_vanished = True
                    break
                counters['fd_errors'] += 1
                continue
            counters['drm_fds'] += 1
            fields = parse_fdinfo(raw)
            cid = fields.get('drm-client-id')
            # The sysfs DRM-node identity is canonical even when drm-pdev is
            # absent on one of several descriptors for the same client.
            gpu_identity = node.get('gpu_key') or f'drm-rdev:{st.st_rdev}'
            identity = ('client', gpu_identity, cid) if cid else ('fd', pid, descriptor.name, gpu_identity)
            source_fields = [
                {'field': 'DRM descriptor', 'path': str(fd_path), 'state': 'Reported'},
                {'field': 'DRM fdinfo', 'path': str(fdinfo_path), 'state': 'Reported'},
                {'field': 'Process name', 'path': str(proc_dir / 'comm'),
                 'state': 'Reported' if comm != 'Not reported' else 'Not reported'},
                {'field': 'Process command', 'path': str(proc_dir / 'cmdline'),
                 'state': 'Reported' if cmdline is not None else 'Inaccessible / disappeared'},
            ]
            notes = list(process_notes)
            if node.get('gpu_key') is None:
                notes.append(f'{node.get("sys_path")}/device: GPU relationship unresolved; DRM node identity used for client grouping')
            if fields.get('drm-pdev') and node.get('pci_address'):
                if fields['drm-pdev'].lower() != node['pci_address'].lower():
                    notes.append(f'{fdinfo_path}: drm-pdev {fields["drm-pdev"]} differs from sysfs PCI {node["pci_address"]}; sysfs association retained')
            if identity not in entries:
                entries[identity] = {
                    'process': comm, 'pid': pid, 'gpu': node.get('gpu', 'Not reported'),
                    'gpu_key': node.get('gpu_key'), 'client_id': cid or 'Not reported',
                    'client_name': fields.get('drm-client-name') or 'Not reported',
                    'drm_node': node['node'], 'fd': descriptor.name,
                    'node_type': node['type'], 'pdev': fields.get('drm-pdev'),
                    'drm_driver': fields.get('drm-driver'),
                    'uid': owner_uid, 'user': owner, 'command': cmdline,
                    'fields': fields, 'pids': [pid], 'fds': [f'{pid}:{descriptor.name}'],
                    'sources': [str(fd_path), str(fdinfo_path)],
                    'source_fields': source_fields, 'source_notes': notes,
                    'acquired': stamp,
                }
            else:
                item = entries[identity]
                if pid not in item['pids']:
                    item['pids'].append(pid)
                item['fds'].append(f'{pid}:{descriptor.name}')
                item['sources'].extend([str(fd_path), str(fdinfo_path)])
                item['source_fields'].extend(source_fields[:2])
                item['source_notes'].extend(notes)
                # Same kernel DRM client: never sum cumulative counters. Keep
                # first reported value; include only keys not yet reported.
                for key, value in fields.items():
                    if key not in item['fields']:
                        item['fields'][key] = value
                    elif item['fields'][key] != value:
                        # Cumulative counters naturally change between reads.
                        # Only stable identity mismatches warrant an explicit note.
                        if key in ('drm-driver', 'drm-pdev', 'drm-client-name'):
                            item['source_notes'].append(
                                f'{fdinfo_path}: {key} differs between observations; original value retained')
                if item['pdev'] is None and fields.get('drm-pdev'):
                    item['pdev'] = fields['drm-pdev']
                if item['client_name'] == 'Not reported' and fields.get('drm-client-name'):
                    item['client_name'] = fields['drm-client-name']
                if item['drm_driver'] is None and fields.get('drm-driver'):
                    item['drm_driver'] = fields['drm-driver']
        if process_vanished:
            counters['vanished'] += 1
            counters['accessible'] -= 1
    return list(entries.values()), counters, stamp


ENGINE_PREFIXES = ('drm-engine-', 'drm-engine-capacity-', 'drm-cycles-',
                   'drm-total-cycles-', 'drm-maxfreq-')
MEMORY_PREFIXES = ('drm-total-', 'drm-shared-', 'drm-resident-', 'drm-purgeable-',
                   'drm-active-', 'drm-memory-')
STANDARD_FIELDS = ('drm-driver', 'drm-client-id', 'drm-client-name', 'drm-pdev')


def engine_records(clients):
    result = []
    for client in clients:
        fields = client['fields']
        for engine in engine_names(fields):
            result.append({**client, 'engine': engine,
                           'busy_time': fields.get('drm-engine-' + engine, 'Not reported'),
                           'capacity': fields.get('drm-engine-capacity-' + engine, 'Not reported'),
                           'busy_cycles': fields.get('drm-cycles-' + engine, 'Not reported'),
                           'total_cycles': fields.get('drm-total-cycles-' + engine, 'Not reported'),
                           'max_frequency': fields.get('drm-maxfreq-' + engine, 'Not reported')})
    return result


def memory_records(clients):
    result = []
    for client in clients:
        fields = client['fields']
        for region in memory_names(fields):
            # drm-memory-<region> is an older resident alias, not a total.
            result.append({**client, 'region': region,
                           'total': fields.get('drm-total-' + region, 'Not reported'),
                           'shared': fields.get('drm-shared-' + region, 'Not reported'),
                           'resident': fields.get('drm-resident-' + region, 'Not reported'),
                           'purgeable': fields.get('drm-purgeable-' + region, 'Not reported'),
                           'active': fields.get('drm-active-' + region, 'Not reported'),
                           'legacy_memory': fields.get('drm-memory-' + region)})
    return result


def raw_driver_fields(client):
    return {k: v for k, v in client.get('fields', {}).items()
            if k not in STANDARD_FIELDS and not k.startswith(ENGINE_PREFIXES + MEMORY_PREFIXES)
            and k not in ('pos', 'flags', 'mnt_id', 'ino')}
