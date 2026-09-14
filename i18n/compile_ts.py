#!/usr/bin/env python3
"""
Minimal .ts -> .qm compiler for Qt5.
Implements the Qt5 binary .qm format.
Usage: python compile_ts.py pastastore_viewer_nl.ts
"""
import os
import struct
import sys
try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # nosec B405

# Qt .qm magic bytes (16 bytes)
QM_MAGIC = bytes([
    0x3c, 0xb8, 0x64, 0x18, 0xca, 0xef, 0x9c, 0x95,
    0xcd, 0x21, 0x1d, 0x4f, 0xa6, 0x6a, 0x37, 0x20,
])

# Top-level chunk tags
TAG_HASHES   = 0x42
TAG_MESSAGES = 0x69

# Per-message entry sub-tags
Q_Translation = 0x01
Q_SourceText  = 0x05
Q_Context     = 0x06
Q_Comment     = 0x07
Q_End         = 0x0f


def elf_hash(data: bytes) -> int:
    """ELF hash function used by Qt for message lookup."""
    h = 0
    for byte in data:
        h = ((h << 4) + byte) & 0xFFFFFFFF
        g = h & 0xF0000000
        if g:
            h ^= g >> 23
        h &= ~g
    return h


def _rot16(v: int) -> int:
    """Rotate a 32-bit value by 16 bits."""
    return ((v << 16) | (v >> 16)) & 0xFFFFFFFF


def message_hash(source: str, comment: str) -> int:
    """
    Compute the hash key stored in the Hashes section.
    Qt uses: elfHash(source) ^ rot16(elfHash(comment))
    When comment is empty Qt uses just elfHash(source).
    """
    h = elf_hash(source.encode("utf-8"))
    if comment:
        h ^= _rot16(elf_hash(comment.encode("utf-8")))
    return h


def write_chunk(tag: int, data: bytes) -> bytes:
    return struct.pack(">BI", tag, len(data)) + data


def encode_tlv(tag: int, data: bytes) -> bytes:
    return struct.pack(">BI", tag, len(data)) + data


def build_message_entry(context: str, source: str, translation: str, comment: str) -> bytes:
    """Build a single message record for the Messages section."""
    entry = b""
    entry += encode_tlv(Q_Context, context.encode("utf-8"))
    entry += encode_tlv(Q_SourceText, source.encode("utf-8"))
    if comment:
        entry += encode_tlv(Q_Comment, comment.encode("utf-8"))
    # Translation is UTF-16 BE (no BOM)
    entry += encode_tlv(Q_Translation, translation.encode("utf-16-be"))
    entry += bytes([Q_End])
    return entry


def ts_to_qm(ts_path: str) -> bytes:
    tree = ET.parse(ts_path)  # nosec B314
    root = tree.getroot()

    messages_data = bytearray()
    hash_pairs = []  # list of (hash_value, byte_offset)

    for ctx_elem in root.findall("context"):
        name_elem = ctx_elem.find("name")
        context = (name_elem.text or "").strip() if name_elem is not None else ""

        for msg_elem in ctx_elem.findall("message"):
            src_elem   = msg_elem.find("source")
            trans_elem = msg_elem.find("translation")
            cmt_elem   = msg_elem.find("comment")

            if src_elem is None or trans_elem is None:
                continue

            source      = (src_elem.text   or "").strip()
            translation = (trans_elem.text or "").strip()
            comment     = (cmt_elem.text   or "").strip() if cmt_elem is not None else ""

            # Skip unfinished / obsolete entries
            t_type = trans_elem.get("type", "")
            if t_type in ("unfinished", "obsolete", "vanished"):
                continue

            if not source or not translation:
                continue

            offset = len(messages_data)
            entry  = build_message_entry(context, source, translation, comment)
            messages_data.extend(entry)

            h = message_hash(source, comment)
            hash_pairs.append((h, offset))

    # Sort hash table by hash value for binary-search lookup
    hash_pairs.sort(key=lambda p: p[0])

    hashes_data = bytearray()
    for h, offset in hash_pairs:
        hashes_data.extend(struct.pack(">II", h, offset))

    qm = QM_MAGIC
    qm += write_chunk(TAG_HASHES,   bytes(hashes_data))
    qm += write_chunk(TAG_MESSAGES, bytes(messages_data))
    return qm


if __name__ == "__main__":
    ts_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "pastastore_viewer_nl.ts")
    qm_file = ts_file.replace(".ts", ".qm")

    qm_data = ts_to_qm(ts_file)
    with open(qm_file, "wb") as f:
        f.write(qm_data)

    print(f"Compiled {ts_file} -> {qm_file}  ({len(qm_data)} bytes, {len(qm_data)//8 - 2} message entries)")
