"""최소 GLB(glTF 2.0 바이너리) 쓰기/읽기. 외부 의존성 없음.

쓰기: 단일 메시, POSITION/NORMAL/COLOR_0(float VEC3, 선형 색공간 — glTF 규약), uint32 인덱스.
읽기: validate_mesh용. 모든 메시 프리미티브의 POSITION/COLOR_0/인덱스를 모아 반환.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _pad4(b: bytes, fill: bytes = b"\x00") -> bytes:
    return b + fill * ((4 - len(b) % 4) % 4)


def write_glb(path: Path, V: np.ndarray, F: np.ndarray, C_linear: np.ndarray, N: np.ndarray | None = None,
              extras: dict | None = None, name: str = "room") -> None:
    V = np.ascontiguousarray(V, np.float32)
    F = np.ascontiguousarray(F, np.uint32)
    C = np.ascontiguousarray(C_linear, np.float32)
    arrays = [("POSITION", V, "VEC3", 5126, 34962), ("COLOR_0", C, "VEC3", 5126, 34962)]
    if N is not None:
        arrays.insert(1, ("NORMAL", np.ascontiguousarray(N, np.float32), "VEC3", 5126, 34962))
    arrays.append(("_indices", F.reshape(-1), "SCALAR", 5125, 34963))

    blob, views, accs, attrs = b"", [], [], {}
    for i, (key, arr, typ, ct, target) in enumerate(arrays):
        data = arr.tobytes()
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
        acc = {"bufferView": i, "componentType": ct, "count": int(arr.shape[0]), "type": typ}
        if key == "POSITION":
            acc["min"] = V.min(0).tolist()
            acc["max"] = V.max(0).tolist()
        accs.append(acc)
        if key != "_indices":
            attrs[key] = i
        blob = _pad4(blob + data)
    gltf = {
        "asset": {"version": "2.0", "generator": "AR_HomeStudio cv/recon", "extras": extras or {}},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"name": name, "primitives": [{"attributes": attrs, "indices": len(arrays) - 1,
                                                    "material": 0, "mode": 4}]}],
        "materials": [{"name": "room_vertex_color", "doubleSided": True,
                       "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0,
                                                "roughnessFactor": 1.0}}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": accs,
    }
    js = _pad4(json.dumps(gltf, separators=(",", ":")).encode(), b" ")
    total = 12 + 8 + len(js) + 8 + len(blob)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(js), b"JSON") + js)
        f.write(struct.pack("<I4s", len(blob), b"BIN\x00") + blob)


def _accessor(gltf: dict, binary: bytes, idx: int) -> np.ndarray:
    a = gltf["accessors"][idx]
    bv = gltf["bufferViews"][a["bufferView"]]
    dt = np.dtype(_CT[a["componentType"]])
    nc = _NC[a["type"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride", 0) or dt.itemsize * nc
    raw = np.frombuffer(binary, np.uint8, count=stride * (a["count"] - 1) + dt.itemsize * nc, offset=off)
    out = np.lib.stride_tricks.as_strided(raw, (a["count"], dt.itemsize * nc), (stride, 1)).copy()
    arr = out.view(dt).reshape(a["count"], nc)
    if a.get("normalized"):
        arr = arr.astype(np.float32) / np.iinfo(dt).max
    return arr


def read_glb(path: Path) -> dict:
    data = Path(path).read_bytes()
    magic, ver, total = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or ver != 2:
        raise ValueError(f"glTF 2.0 바이너리가 아닙니다: magic={magic} version={ver}")
    off, gltf, binary = 12, None, b""
    while off < total:
        ln, typ = struct.unpack_from("<I4s", data, off)
        chunk = data[off + 8: off + 8 + ln]
        if typ == b"JSON":
            gltf = json.loads(chunk)
        elif typ == b"BIN\x00":
            binary = chunk
        off += 8 + ln
    Vs, Cs, Fs, has_color, node_xf = [], [], [], True, False
    base = 0
    for node in gltf.get("nodes", []):
        if any(k in node for k in ("matrix", "rotation", "scale", "translation")):
            node_xf = True
    for mesh in gltf["meshes"]:
        for prim in mesh["primitives"]:
            if prim.get("mode", 4) != 4:
                continue
            V = _accessor(gltf, binary, prim["attributes"]["POSITION"]).astype(np.float64)
            if "COLOR_0" in prim["attributes"]:
                C = _accessor(gltf, binary, prim["attributes"]["COLOR_0"]).astype(np.float64)[:, :3]
            else:
                has_color, C = False, np.zeros_like(V)
            F = (_accessor(gltf, binary, prim["indices"]).reshape(-1, 3) if "indices" in prim
                 else np.arange(len(V)).reshape(-1, 3)).astype(np.int64)
            Vs.append(V)
            Cs.append(C)
            Fs.append(F + base)
            base += len(V)
    return dict(gltf=gltf, V=np.concatenate(Vs), C=np.concatenate(Cs), F=np.concatenate(Fs),
                has_color=has_color, node_transform=node_xf)
