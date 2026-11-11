"""Save states: the whole console between two instructions, as bytes, and back.

A save state is everything that changes as the console runs: the CPU (6502-python's
``CPUState``), the board, the PPU, the APU, the cartridge with its mapper, its RAM,
its sound chips and disk, and the devices in the ports. It is *not* the wiring: a
state is loaded into a :class:`~famicom_python.system.System` built from the same
cartridge on the same machine, which already holds the configuration (``Machine``,
``Timing``, the ROM image), the callables that connect the parts, and the
references between them. Loading writes the saved values into that system's
objects, in place, so the references stay as they were built.

**What is saved**, by walking the object graph from the system: every attribute of
an object whose class belongs to ``famicom_python`` (or to ``ym2413_python``, the
VRC7's sound chip), depth first in attribute order, as plain data. Not saved:

- callables (the board's interrupt inputs, bus observers, devices' clocks);
- frozen dataclasses (the configuration: ``Machine``, ``Timing``, ``RomImage``,
  ``BoardInfo``, the APU tables), and the loader's record (``System.loaded``);
- the CPU object (its ``capture_state`` is saved instead);
- a second path to an object already saved (the APU's ``lengths`` names the
  channels' length counters; a sound chip names its cartridge): it is written as a
  reference, and loading leaves it, since the system built for loading has the same
  sharing;
- the ROM image's bytes, where an attribute holds them unchanged.

**The format** is zlib-compressed JSON: a header (format, version, the cartridge's
SHA-1, the machine's name) and the encoded graph, each value tagged by type. It
holds no code: loading creates nothing but this package's own classes and plain
data, and refuses a state for another cartridge or machine.

**Equivalence** is the test (tests/test_state.py, scripts/state_roundtrip.py): a
run saved at some instruction boundary and loaded into a fresh system continues
exactly as the run that was never interrupted, bus cycle for bus cycle.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import zlib
from array import array
from typing import TYPE_CHECKING, Any

from sixfiveohtwo import CPUState

if TYPE_CHECKING:
    from .system import System

FORMAT = "famicom-python state"
VERSION = 1
# Modules whose objects are part of the state.
MODULES = ("famicom_python", "ym2413_python")
# Attributes that are not state: the loader's record, observers of the bus.
SKIPPED = {"loaded", "bus_observers", "_tiles", "_colours"}


class StateError(ValueError):
    """A state that cannot be loaded into this system."""


def _rom_sha1(system: System) -> str:
    loaded = system.loaded
    if loaded is None:
        return ""
    image = loaded.image
    return hashlib.sha1(image.prg + image.chr + image.misc).hexdigest()


def _ours(value: object) -> bool:
    module = type(value).__module__
    return module.split(".", 1)[0] in MODULES


def _frozen(value: object) -> bool:
    params = getattr(type(value), "__dataclass_params__", None)
    return dataclasses.is_dataclass(value) and params is not None and params.frozen


class _Encoder:
    def __init__(self, system: System) -> None:
        self.seen: dict[int, str] = {}
        self.cpu = system.cpu
        loaded = system.loaded
        image = loaded.image if loaded is not None else None
        # The ROM image's bytes, by identity: written by name, not content.
        self.images: dict[int, str] = {}
        if image is not None:
            for name in ("prg", "chr", "misc", "trainer", "header"):
                self.images[id(getattr(image, name))] = name

    def value(self, value: Any, path: str) -> Any:
        if value is None or isinstance(value, (bool, int, str, float)):
            return value
        if isinstance(value, bytes):
            name = self.images.get(id(value))
            if name is not None:
                return {"image": name}
            return {"bytes": base64.b64encode(value).decode()}
        if isinstance(value, bytearray):
            return {"bytearray": base64.b64encode(value).decode()}
        if isinstance(value, array):
            return {"array": value.typecode, "data": base64.b64encode(value.tobytes()).decode()}
        if isinstance(value, list):
            return [self.value(item, f"{path}[{i}]") for i, item in enumerate(value)]
        if isinstance(value, tuple):
            return {"tuple": [self.value(item, f"{path}[{i}]") for i, item in enumerate(value)]}
        if isinstance(value, (set, frozenset)):
            return {"set": sorted(self.value(item, path) for item in value)}
        if isinstance(value, dict):
            pairs = [
                [self.value(k, path), self.value(v, f"{path}[{k!r}]")] for k, v in value.items()
            ]
            return {"dict": pairs}
        if _ours(value) and not _frozen(value):
            if id(value) in self.seen:
                return {"ref": self.seen[id(value)]}
            self.seen[id(value)] = path
            return self.object(value, path)
        raise StateError(f"{path}: cannot save a {type(value).__qualname__}")

    def object(self, value: object, path: str) -> dict:
        fields = {}
        for name, attribute in vars(value).items():
            if name in SKIPPED or attribute is self.cpu:
                continue
            if _frozen(attribute) or isinstance(attribute, type):
                continue  # configuration, or a class
            if callable(attribute) and not _ours(attribute):
                continue  # a function, a lambda or a bound method: wiring
            if (
                isinstance(attribute, (list, tuple))
                and attribute
                and all(callable(item) and not _ours(item) for item in attribute)
            ):
                continue  # a list of callables: wiring
            fields[name] = self.value(attribute, f"{path}.{name}")
        cls = type(value)
        return {"object": f"{cls.__module__}.{cls.__qualname__}", "fields": fields}


def save_state(system: System) -> bytes:
    """The state of ``system`` as bytes (between two of its steps). A
    PlayChoice-10 cabinet (supervisor.PlayChoice) is saved whole: the game's
    System as any other, with the supervisor and its Z80 beside it."""
    if hasattr(system, "supervisor"):
        return _save_cabinet(system)
    return zlib.compress(json.dumps(_body(system), separators=(",", ":")).encode(), 6)


def _save_cabinet(cabinet: Any) -> bytes:
    supervisor = cabinet.supervisor
    encoder = _Encoder(cabinet.game)
    encoder.cpu = supervisor.cpu  # the Z80: its capture_state is saved instead
    body = _body(cabinet.game)
    body["supervisor"] = {
        "cpu": dataclasses.asdict(supervisor.cpu.capture_state()),
        "state": encoder.value(supervisor, "supervisor"),
        "lines": [cabinet.in_reset, cabinet.stopped, cabinet._nmi],
    }
    return zlib.compress(json.dumps(body, separators=(",", ":")).encode(), 6)


def _body(system: System) -> dict:
    encoder = _Encoder(system)
    cpu = dataclasses.asdict(system.cpu.capture_state())
    body = {
        "format": FORMAT,
        "version": VERSION,
        "rom_sha1": _rom_sha1(system),
        "machine": system.machine.name,
        "cpu": cpu,
        "instructions": system.instructions,
        "board": encoder.value(system.board, "board"),
    }
    return body


class _Decoder:
    """Applies an encoded graph to a system, in place where it can.

    The encoder writes each object once, at the first path that reaches it,
    and a reference at every later one. The decoder walks in the same order,
    keeps each object it restores by that path, and gives a reference the
    object restored there, so sharing is as it was saved, whatever the system
    loaded into shares. An existing object is updated in place only by the
    first path that claims it; another path saved with an object of its own
    gets a new one.
    """

    def __init__(self, system: System) -> None:
        loaded = system.loaded
        self.image = loaded.image if loaded is not None else None
        self.objects: dict[str, object] = {}  # restored objects by their saved path
        self.claimed: set[int] = set()  # existing objects already updated

    def fresh(self, encoded: Any, path: str) -> Any:
        """A value built from ``encoded`` with nothing to update in place."""
        if encoded is None or isinstance(encoded, (bool, int, str, float)):
            return encoded
        if isinstance(encoded, list):
            return [self.fresh(item, f"{path}[{i}]") for i, item in enumerate(encoded)]
        if "ref" in encoded:
            return self.reference(encoded)
        if "bytes" in encoded:
            return base64.b64decode(encoded["bytes"])
        if "bytearray" in encoded:
            return bytearray(base64.b64decode(encoded["bytearray"]))
        if "array" in encoded:
            out = array(encoded["array"])
            out.frombytes(base64.b64decode(encoded["data"]))
            return out
        if "image" in encoded:
            if self.image is None:
                raise StateError("a state naming the ROM image, without one")
            return getattr(self.image, encoded["image"])
        if "tuple" in encoded:
            items = encoded["tuple"]
            return tuple(self.fresh(item, f"{path}[{i}]") for i, item in enumerate(items))
        if "set" in encoded:
            return {self.fresh(item, path) for item in encoded["set"]}
        if "dict" in encoded:
            out = {}
            for k, v in encoded["dict"]:
                key = self.fresh(k, path)
                out[key] = self.fresh(v, f"{path}[{key!r}]")
            return out
        if "object" in encoded:
            cls = _class(encoded["object"])
            obj = cls.__new__(cls)
            self.objects[path] = obj
            for name, value in encoded["fields"].items():
                setattr(obj, name, self.fresh(value, f"{path}.{name}"))
            return obj
        raise StateError(f"cannot load {str(encoded)[:80]}")

    def reference(self, encoded: dict) -> object:
        try:
            return self.objects[encoded["ref"]]
        except KeyError:
            raise StateError(f"a reference to nothing saved: {encoded['ref']}") from None

    def into(self, current: Any, encoded: Any, path: str) -> Any:
        """``encoded`` applied to ``current``: updated in place where it is an
        object (or a container of objects) of the same shape not yet claimed,
        else built fresh. Returns the value the attribute should hold."""
        if isinstance(encoded, dict) and "ref" in encoded:
            return self.reference(encoded)
        if isinstance(encoded, dict) and "object" in encoded:
            if (
                _ours(current)
                and _qualified(current) == encoded["object"]
                and id(current) not in self.claimed
            ):
                self.claimed.add(id(current))
                self.objects[path] = current
                self.apply(current, encoded["fields"], path)
                return current
            return self.fresh(encoded, path)
        if isinstance(encoded, list) and isinstance(current, list) and len(current) == len(encoded):
            for i, item in enumerate(encoded):
                current[i] = self.into(current[i], item, f"{path}[{i}]")
            return current
        if isinstance(encoded, dict) and "tuple" in encoded and isinstance(current, tuple):
            items = encoded["tuple"]
            if len(items) == len(current):
                return tuple(
                    self.into(c, e, f"{path}[{i}]")
                    for i, (c, e) in enumerate(zip(current, items, strict=True))
                )
        if isinstance(encoded, dict) and "dict" in encoded and isinstance(current, dict):
            out = {}
            for k, v in encoded["dict"]:
                key = self.fresh(k, path)
                out[key] = self.into(current.get(key), v, f"{path}[{key!r}]")
            return out
        return self.fresh(encoded, path)

    def apply(self, obj: object, fields: dict, path: str) -> None:
        for name, encoded in fields.items():
            setattr(obj, name, self.into(getattr(obj, name, None), encoded, f"{path}.{name}"))


def _qualified(value: object) -> str:
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def _class(name: str) -> type:
    """A class of this package (or the sound chip's) by its qualified name."""
    import importlib

    module, _, qualname = name.rpartition(".")
    while module and module.split(".", 1)[0] in MODULES:
        try:
            found: Any = importlib.import_module(module)
        except ModuleNotFoundError:
            module, _, outer = module.rpartition(".")
            qualname = f"{outer}.{qualname}"
            continue
        for part in qualname.split("."):
            found = getattr(found, part)
        if isinstance(found, type):
            return found
        break
    raise StateError(f"not a class a state may hold: {name}")


def load_state(system: System, data: bytes) -> None:
    """Put ``system`` in the state ``data`` was saved from (same cartridge and machine)."""
    cabinet: Any = None
    if hasattr(system, "supervisor"):
        cabinet, system = system, system.game  # type: ignore[attr-defined]
    try:
        body = json.loads(zlib.decompress(data))
    except (zlib.error, ValueError) as error:
        raise StateError(f"not a save state: {error}") from None
    if body.get("format") != FORMAT or body.get("version") != VERSION:
        raise StateError(f"not a {FORMAT} version {VERSION}")
    if body["rom_sha1"] != _rom_sha1(system):
        raise StateError("a state of another cartridge")
    if body["machine"] != system.machine.name:
        raise StateError(f"a state of the {body['machine']}, not the {system.machine.name}")
    if (cabinet is None) != ("supervisor" not in body):
        raise StateError("a cabinet's state and a console's are not each other's")
    decoder = _Decoder(system)
    decoder.into(system.board, body["board"], "board")
    system.cpu.restore_state(CPUState(**body["cpu"]))
    system.instructions = body["instructions"]
    if cabinet is not None:
        saved = body["supervisor"]
        supervisor = cabinet.supervisor
        _Decoder(system).into(supervisor, saved["state"], "supervisor")
        z80 = supervisor.cpu
        z80.restore_state(type(z80.capture_state())(**saved["cpu"]))
        cabinet.in_reset, cabinet.stopped, cabinet._nmi = saved["lines"]
