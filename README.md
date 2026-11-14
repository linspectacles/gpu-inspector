# GPU Inspector

**Expose. Explore. Explain.**

GPU Inspector is a read-only Linux GPU and DRM inspector for GPU devices, DRM nodes, visible process clients, per-client memory regions and reported engine counters.

Current release: **0.0.4**

Repository: <https://github.com/linspectacles/gpu-inspector>


<p align="center">
  <a href="https://github.com/brunonlinespace/brunonlinespace/blob/main/linspectacles/gpu-inspector.png">
    <img
      src="https://raw.githubusercontent.com/brunonlinespace/brunonlinespace/main/linspectacles/gpu-inspector.png"
      alt="GPU Inspector screenshot"
      width="900"
    >
  </a>
</p>
## What GPU Inspector is

GPU Inspector answers a focused question: **what GPU/DRM devices does Linux expose, what relationships and client statistics do their drivers report, and which visible processes are using them?**

The applet is built on ordinary DRM, PCI sysfs and procfs evidence. Generic GPU discovery does not require a vendor utility or root access.

Its five-view model deliberately keeps device inventory, DRM nodes, clients, memory accounting and engine counters distinct rather than forcing vendor-specific GPU concepts into one synthetic schema.

## Highlights

- Five views: **GPUs**, **DRM Nodes**, **Clients**, **Memory** and **Engines**.
- GPU discovery from DRM/sysfs and PCI display-class devices.
- Primary, render and control DRM node inventory where exposed.
- PCI identity, bound driver/module, NUMA locality, IOMMU group and PCIe link fields where reported.
- Lazy visible-process DRM client inspection through procfs.
- DRM client de-duplication using reported client/device identity where available.
- Standard DRM per-client memory-region accounting without fabricating missing categories.
- Standard DRM cumulative engine/cycle/frequency fields where reported.
- Separate AMDGPU device-level VRAM/GTT information where exposed by stable sysfs fields.
- Explicit inaccessible/vanished-process coverage reporting.
- Export never scans unopened views.

## Data sources and acquisition

### GPU and DRM node inventory

- `/sys/class/drm/`
- `/dev/dri/`
- `/sys/bus/pci/devices/<BDF>/...`

### Visible DRM clients

- `/proc/<pid>/fd/<fd>`
- `/proc/<pid>/fdinfo/<fd>`

Standard `drm-*` fdinfo keys are retained according to what the running driver actually reports.

### Optional AMDGPU device-memory context

- `/sys/bus/pci/devices/<BDF>/mem_info_vram_*`
- `/sys/bus/pci/devices/<BDF>/mem_info_vis_vram_*`
- `/sys/bus/pci/devices/<BDF>/mem_info_gtt_*`

The GPU/DRM inventory is sysfs-based and requires no vendor utility. Client, Memory and Engines coverage is limited to DRM descriptors/fdinfo readable by the current user.

## Interface

GPU Inspector provides five views:

- **GPUs** — GPU identity, PCI/driver/DRM/topology context.
- **DRM Nodes** — primary/render/control nodes and ordinary node facts.
- **Clients** — visible process DRM clients.
- **Memory** — standard per-client DRM memory-region records.
- **Engines** — reported per-client DRM engine counters.

The GPUs/DRM foundation loads first. **Clients**, **Memory** and **Engines** are lazy and scan procfs only when first opened or explicitly refreshed. Memory and Engines can reuse the same current client snapshot where appropriate.

Search and view-specific selectors filter already-collected records. They do not trigger hidden acquisition.

The **Options...** surface provides Appearance, Sources, Export and About. Export can use the active view or all already-collected views, but it never opens/scans a view merely because it was selected for export.

## Read-only and scope boundaries

GPU Inspector does not elevate privileges, use NVML, scan debugfs, write sysfs, change device state, manage clocks/power/fans, reset GPUs, bind/unbind drivers, run GPU workloads or alter DRM-node permissions.

Important interpretation boundaries:

- Client visibility is limited to procfs/fdinfo readable by the current user.
- Missing fields are **Not reported**, never fabricated as zero.
- DRM engine busy-time values are **cumulative counters**, not instantaneous utilisation percentages.
- DRM per-client memory accounting remains separate from AMDGPU device-level VRAM/GTT totals.
- The bound driver is reported from actual system evidence; Intel is not assumed to mean `i915`, and NVIDIA is not assumed to provide vendor-specific statistics.
- GPU health or security verdicts are not inferred.

## Useful keyboard shortcuts

| Command | Shortcut |
| --- | --- |
| Toggle Metadata Details | `F3` |
| Refresh active view | `Shift+F5` |
| Toggle Metadata Details layout | `Ctrl+L` |
| Options | `Ctrl+/` |

## Running from source

The supplied source is directly runnable on Linux. The Python-side requirements are:

- Python 3.10 or later.
- PyQt6 for the graphical interface.

The source recommends PyQt6 `>=6.6,<6.12`.

Create a local virtual environment if you do not already have the required Python packages in the environment you want to use:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "PyQt6>=6.6,<6.12"
python3 -m linspectacles_gpu_inspector.standalone
```

No vendor GPU utility or root access is required for the generic inventory.

No RPM installation instructions are included in this README.

## LinSpectacles Hub

This applet can run independently, but it can also be installed and used inside **[LinSpectacles Hub](https://github.com/linspectacles/linspectacles-hub)**.

LinSpectacles Hub is the optional workbench for the LinSpectacles applet family. It provides shared applet discovery, navigation and management while each inspector remains independently runnable.

To install a portable or user applet through the Hub, open **Configuration... → Applets** and add the applet ZIP. Once discovered, the applet can be enabled and opened from the Hub navigation.

System-installed applets are discovered by the Hub from its system applet store and remain managed by the system package manager.

## Source layout and LinSpectacles integration

The supplied source contains:

```text
linspectacles_gpu_inspector/
├── __init__.py
├── standalone.py
├── LICENSE
├── applet.json
├── README.md
└── gpu_inspector/
    ├── __init__.py
    ├── applet.py
    ├── collectors.py
    ├── procfs.py
    ├── presentation.py
    ├── _support.py
    └── icon.png
```

`applet.json` defines the applet's LinSpectacles identity and integration metadata. `standalone.py` provides direct standalone launching, while the applet entrypoint allows the same inspector to run inside LinSpectacles Hub.

## Configuration

GPU Inspector persists presentation state implemented by the applet, including active view, Metadata Details visibility/layout and per-view column settings where supported.

Persisted UI state does not grant additional process visibility or change GPU/DRM state.

## Scope

GPU Inspector owns **GPU and DRM device/client evidence**.

**Hardware Topology** remains authoritative for broader PCI, NUMA and IOMMU topology. **Kernel Modules** remains authoritative for kernel-module inspection. **Power & Thermal Inspector** remains the system-wide thermal/power specialist. A **Display Server Inspector** owns graphical-session, compositor, output, mode and protocol evidence rather than having GPU Inspector infer those relationships.

## License

GNU General Public License v3.0 or later. See [`LICENSE`](LICENSE).

## Links

- LinSpectacles organisation: <https://github.com/linspectacles/>
- LinSpectacles Hub: <https://github.com/linspectacles/linspectacles-hub>
- Repository: <https://github.com/linspectacles/gpu-inspector>
- Issues: <https://github.com/linspectacles/gpu-inspector/issues>

<p align="center">
  <a href="https://github.com/linspectacles/gpu-inspector">
    <img
      src="gpu_inspector/icon.png"
      alt="GPU Inspector"
      width="256"
    >
  </a>
</p>
