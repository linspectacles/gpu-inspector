"""Read-only Linux PCI/DRM device acquisition. No vendor tools required."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat

SYS_DRM = Path('/sys/class/drm')
SYS_PCI = Path('/sys/bus/pci/devices')
DEV_DRI = Path('/dev/dri')
NODE_RE = re.compile(r'^(card\d+|renderD\d+|controlD\d+)$')
PCI_RE = re.compile(r'^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$')
AMDGPU_MEMORY = (
    ('mem_info_vram_total', 'VRAM Total'),
    ('mem_info_vram_used', 'VRAM Used'),
    ('mem_info_vis_vram_total', 'Visible VRAM Total'),
    ('mem_info_vis_vram_used', 'Visible VRAM Used'),
    ('mem_info_gtt_total', 'GTT Total'),
    ('mem_info_gtt_used', 'GTT Used'),
)
PCI_FIELDS = ('class', 'vendor', 'device', 'subsystem_vendor', 'subsystem_device',
              'revision', 'numa_node', 'boot_vga', 'current_link_speed',
              'current_link_width', 'max_link_speed', 'max_link_width')


def acquired_at():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


def _source(fields, label, path, state):
    if fields is not None:
        fields.append({'field': label, 'path': str(path), 'state': state})


def read_field(path, source_fields=None, label=None):
    path = Path(path)
    try:
        result = path.read_text(encoding='utf-8', errors='replace').strip()
        _source(source_fields, label or path.name, path, 'Reported' if result else 'Empty')
        return result or None
    except FileNotFoundError:
        _source(source_fields, label or path.name, path, 'Not exposed (absent)')
    except PermissionError:
        _source(source_fields, label or path.name, path, 'Inaccessible (permission denied)')
    except (OSError, ValueError) as exc:
        _source(source_fields, label or path.name, path, f'Read failed ({type(exc).__name__})')
    return None


def link_name(path, source_fields=None, label=None):
    path = Path(path)
    try:
        if path.is_symlink():
            target = path.resolve(strict=True)
            _source(source_fields, label or path.name, path, f'Reported → {target}')
            return target.name
        _source(source_fields, label or path.name, path, 'Not exposed (no symlink)')
    except FileNotFoundError:
        _source(source_fields, label or path.name, path, 'Unresolved (broken symlink)')
    except PermissionError:
        _source(source_fields, label or path.name, path, 'Inaccessible (permission denied)')
    except (OSError, RuntimeError) as exc:
        _source(source_fields, label or path.name, path, f'Unresolved ({type(exc).__name__})')
    return None


def resolved(path, source_fields=None, label=None):
    path = Path(path)
    try:
        result = str(path.resolve(strict=True))
        _source(source_fields, label or path.name, path, f'Reported → {result}')
        return result
    except FileNotFoundError:
        _source(source_fields, label or path.name, path, 'Not exposed / unresolved')
    except PermissionError:
        _source(source_fields, label or path.name, path, 'Inaccessible (permission denied)')
    except (OSError, RuntimeError) as exc:
        _source(source_fields, label or path.name, path, f'Unresolved ({type(exc).__name__})')
    return None


def canonical_pci(path):
    """Find a real PCI ancestor; do not invent a PCI BDF for platform DRM."""
    if path is None:
        return None
    for node in (Path(path), *Path(path).parents):
        if PCI_RE.fullmatch(node.name):
            return node.name
    return None


def pci_values(device_dir, source_fields=None):
    result = {key: read_field(device_dir / key, source_fields, key) for key in PCI_FIELDS}
    if result['numa_node'] == '-1':
        result['numa_node'] = None
    result['driver'] = link_name(device_dir / 'driver', source_fields, 'driver')
    result['driver_path'] = resolved(device_dir / 'driver', source_fields, 'driver target') if result['driver'] else None
    result['module'] = link_name(device_dir / 'driver' / 'module', source_fields, 'driver module') if result['driver'] else None
    result['iommu_group'] = link_name(device_dir / 'iommu_group', source_fields, 'iommu_group')
    return result


def kind_for(node):
    if re.fullmatch(r'card\d+', node):
        return 'Primary'
    if re.fullmatch(r'renderD\d+', node):
        return 'Render'
    if re.fullmatch(r'controlD\d+', node):
        return 'Control'
    return None


def discover(sys_drm=SYS_DRM, sys_pci=SYS_PCI, dev_dri=DEV_DRI):
    """Return (GPUs, DRM nodes, timestamp); unresolved nodes stay unassociated.

    A real platform device may form a GPU group, but a node whose /device
    relationship cannot be resolved is NEVER promoted to a fabricated GPU.
    """
    sys_drm, sys_pci, dev_dri = map(Path, (sys_drm, sys_pci, dev_dri))
    stamp = acquired_at()
    groups = {}
    pci_paths = {}
    if sys_pci.is_dir():
        for device_dir in sorted(sys_pci.iterdir()):
            if not PCI_RE.fullmatch(device_dir.name):
                continue
            cls = read_field(device_dir / 'class')
            if cls is None or not cls.lower().startswith('0x03'):
                continue
            key = 'pci:' + device_dir.name.lower()
            canonical = resolved(device_dir) or str(device_dir)
            pci_paths[device_dir.name.lower()] = device_dir
            groups[key] = {'key': key, 'pci_address': device_dir.name,
                           'sys_device': canonical, 'nodes': [], 'sources': [str(device_dir)],
                           'association': 'PCI device identified'}

    raw_nodes = []
    if sys_drm.is_dir():
        for node_dir in sorted(sys_drm.iterdir()):
            name = node_dir.name
            if not NODE_RE.fullmatch(name):
                continue  # card0-HDMI-A-1 etc. are connector entries, not nodes.
            field_provenance = []
            device_path = resolved(node_dir / 'device', field_provenance, 'DRM device relationship')
            pci = canonical_pci(device_path)
            # A missing /device relation is not evidence of a distinct physical GPU.
            key = ('pci:' + pci.lower()) if pci else (('platform:' + device_path) if device_path else None)
            if key is not None and key not in groups:
                groups[key] = {'key': key, 'pci_address': pci, 'sys_device': device_path,
                               'nodes': [], 'sources': [str(node_dir)],
                               'association': 'Resolved platform device' if not pci else 'Resolved PCI device'}
            major_minor = read_field(node_dir / 'dev', field_provenance, 'DRM major:minor')
            dev_path = dev_dri / name
            rdev = None
            try:
                major, minor = (int(v) for v in (major_minor or '').split(':'))
                rdev = os.makedev(major, minor)
            except (ValueError, TypeError, OverflowError):
                pass
            fs_stat = None
            try:
                st = dev_path.stat()
                if stat.S_ISCHR(st.st_mode):
                    if rdev is None:
                        rdev = st.st_rdev
                        fs_stat = st
                        _source(field_provenance, 'Device node identity', dev_path, 'Reported (character device; sysfs major:minor unavailable)')
                    elif st.st_rdev == rdev:
                        fs_stat = st
                        _source(field_provenance, 'Device node identity', dev_path, 'Reported (matches sysfs major:minor)')
                    else:
                        _source(field_provenance, 'Device node identity', dev_path, 'Mismatch with sysfs major:minor')
                else:
                    _source(field_provenance, 'Device node identity', dev_path, 'Not a character device')
            except FileNotFoundError:
                _source(field_provenance, 'Device node identity', dev_path, 'Not present')
            except PermissionError:
                _source(field_provenance, 'Device node identity', dev_path, 'Inaccessible (permission denied)')
            except OSError as exc:
                _source(field_provenance, 'Device node identity', dev_path, f'Stat failed ({type(exc).__name__})')
            node = {'node': name, 'type': kind_for(name), 'gpu_key': key,
                    'pci_address': pci, 'major_minor': major_minor,
                    'device_path': str(dev_path), 'sys_path': str(node_dir),
                    'sys_device': device_path, 'rdev': rdev,
                    'exists': fs_stat is not None,
                    'device_confirmed': ('Present; sysfs major:minor not exposed' if fs_stat is not None and not major_minor
                                         else ('Present; matches sysfs major:minor' if fs_stat is not None
                                               else 'Not confirmed')),
                    'mode': stat.filemode(fs_stat.st_mode) if fs_stat else None,
                    'uid': fs_stat.st_uid if fs_stat else None,
                    'gid': fs_stat.st_gid if fs_stat else None,
                    'association': ('Resolved PCI device' if pci else 'Resolved platform device') if key else 'Unresolved (no sysfs device relationship)',
                    'acquired': stamp, 'sources': [str(node_dir), str(node_dir / 'device'), str(node_dir / 'dev'), str(dev_path)],
                    'source_fields': field_provenance}
            if key is not None:
                group = groups[key]
                group['nodes'].append(node)
                group['sources'].extend(node['sources'])
            raw_nodes.append(node)

    gpus = []
    for key, group in sorted(groups.items()):
        pci = group['pci_address']
        pci_dir = pci_paths.get(pci.lower()) if pci else None
        if pci and pci_dir is None:
            pci_dir = sys_pci / pci
        device_dir = pci_dir if (pci_dir and pci_dir.is_dir()) else (Path(group['sys_device']) if group['sys_device'] else None)
        source_fields = []
        props = pci_values(device_dir, source_fields) if device_dir is not None else {}
        for associated_node in group['nodes']:
            source_fields.extend(associated_node.get('source_fields', []))
        cards = [n['node'] for n in group['nodes'] if n['type'] == 'Primary']
        renders = [n['node'] for n in group['nodes'] if n['type'] == 'Render']
        driver = props.get('driver')
        human = f'GPU {pci}' if pci else f'GPU {Path(group["sys_device"]).name}'
        vendor = props.get('vendor')
        device = props.get('device')
        vendor_device = ' / '.join((vendor or 'Not reported', device or 'Not reported'))
        mem = {}
        if driver == 'amdgpu':
            for field, title in AMDGPU_MEMORY:
                raw = read_field(device_dir / field, source_fields, title)
                if raw is not None:
                    try:
                        mem[title] = int(raw)
                    except ValueError:
                        _source(source_fields, title, device_dir / field, 'Invalid integer value')
        record = dict(group)
        record.update(props)
        record.update({'gpu': human, 'vendor_device': vendor_device,
                       'drm_card': ', '.join(cards) or 'Not reported',
                       'render_node': ', '.join(renders) or 'Not reported',
                       'numa': props.get('numa_node') or 'Not reported',
                       'iommu': props.get('iommu_group') or 'Not reported',
                       'driver': driver or 'Not reported', 'device_memory': mem,
                       'acquired': stamp,
                       'sources': list(dict.fromkeys(group['sources'] + ([str(device_dir)] if device_dir else []))),
                       'source_fields': source_fields})
        gpus.append(record)
    by_key = {g['key']: g for g in gpus}
    for node in raw_nodes:
        gpu = by_key.get(node['gpu_key'])
        node['gpu'] = gpu['gpu'] if gpu else 'Not reported'
        node['driver'] = gpu['driver'] if gpu else 'Not reported'
    raw_nodes.sort(key=lambda n: (n['gpu'], {'Primary': 0, 'Render': 1, 'Control': 2}.get(n['type'], 3), n['node']))
    return gpus, raw_nodes, stamp
