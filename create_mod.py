#!/usr/bin/env python3
"""
The Crust - Stock Market Price Mod Creator
==========================================
Setzt alle BasePrice-Werte im Stock Market auf einen niedrigen Wert.

Warum nicht 1.0?
  Das Spiel berechnet intern: minPrice = int(BasePrice * MaxPriceNegativeDeviation)
  Mit BasePrice=1.0 und MaxNegDev=0.5..0.7 → int(0.5..0.7) = 0 → EXCEPTION_INT_DIVIDE_BY_ZERO
  Minimum sicherer Wert: BasePrice * min(MaxNegDev) >= 1  →  1.0 / 0.5 = 2.0
  NEW_PRICE = 10.0 (4–6500× billiger als original, sicher bei allen Devations)

Liest DA_GlobalMarket_1 bis _4 aus dem Spiel-Pak,
modifiziert die Preise und schreibt eine neue .pak-Mod-Datei.

Installation der fertigen Mod:
  mkdir -p ~/.local/share/Steam/steamapps/common/The Crust/TheCrust/Content/Paks/~mods/
  cp 500-Market_Price1_P.pak ~/.local/share/Steam/steamapps/common/The Crust/TheCrust/Content/Paks/~mods/
"""

import struct
import zlib
import hashlib
import os

# ─── Konfiguration ────────────────────────────────────────────────────────────

PAK_PATH = os.path.expanduser(
    "~/.local/share/Steam/steamapps/common/The Crust/TheCrust/Content/Paks/pakchunk0-WindowsNoEditor.pak"
)
OUTPUT_PAK = os.path.join(os.path.dirname(__file__), "500-Market_Price10_P.pak")

# Virtuelle Pfade der Zieldateien im Spiel-Pak
TARGET_FILES = [
    f"TheCrust/Content/Blueprints/Market/DA_GlobalMarket_{n}.{ext}"
    for n in [1, 2, 3, 4]
    for ext in ["uasset", "uexp"]
]


# ─── Pak v11: Index und Encoded Entries lesen ─────────────────────────────────

def read_pak_footer(pak_path):
    """Liest Footer des Spiel-Paks (v11) und gibt Index-Offset/-Größe zurück."""
    with open(pak_path, "rb") as f:
        f.seek(-256, 2)
        tail = f.read(256)
    magic = bytes.fromhex("e1126f5a")
    pos = tail.rfind(magic)
    if pos < 0:
        raise RuntimeError("Kein UE4-Pak-Magic gefunden!")
    version     = struct.unpack("<I", tail[pos+4:pos+8])[0]
    idx_offset  = struct.unpack("<Q", tail[pos+8:pos+16])[0]
    idx_size    = struct.unpack("<Q", tail[pos+16:pos+24])[0]
    return version, idx_offset, idx_size


def read_index_header(pak_path, idx_offset):
    """
    Liest den v8+-Index-Header und gibt zurück:
      enc_entries_start  – absoluter Byte-Offset der Encoded-Entries im Pak
      fdi_offset/size    – Full Directory Index Position
    """
    with open(pak_path, "rb") as f:
        f.seek(idx_offset)
        raw = f.read(220)

    pos = 0
    mount_len = struct.unpack("<i", raw[pos:pos+4])[0]; pos += 4 + mount_len
    _file_count = struct.unpack("<I", raw[pos:pos+4])[0]; pos += 4
    pos += 8   # path_hash_seed
    has_phi = struct.unpack("<I", raw[pos:pos+4])[0]; pos += 4
    pos += 8 + 8 + 20  # phi offset/size/hash
    has_fdi = struct.unpack("<I", raw[pos:pos+4])[0]; pos += 4
    fdi_offset = struct.unpack("<Q", raw[pos:pos+8])[0]; pos += 8
    fdi_size   = struct.unpack("<Q", raw[pos:pos+8])[0]; pos += 8
    pos += 20  # fdi hash
    enc_size = struct.unpack("<I", raw[pos:pos+4])[0]; pos += 4
    enc_start = idx_offset + pos
    return enc_start, fdi_offset, fdi_size


def find_entry_indices(pak_path, fdi_offset, fdi_size, targets):
    """
    Parst den Full Directory Index und gibt {virtual_path: entry_idx} zurück.
    entry_idx ist ein Byte-Offset in die Encoded Entries.
    """
    with open(pak_path, "rb") as f:
        f.seek(fdi_offset)
        fdi = f.read(fdi_size)

    pos = 0
    dir_count = struct.unpack("<i", fdi[pos:pos+4])[0]; pos += 4
    result = {}

    for _ in range(dir_count):
        if pos + 4 > len(fdi):
            break
        dlen = struct.unpack("<i", fdi[pos:pos+4])[0]; pos += 4
        if dlen <= 0 or pos + dlen > len(fdi):
            break
        dname = fdi[pos:pos+dlen].rstrip(b"\x00").decode("utf-8", errors="replace")
        pos += dlen
        fcount = struct.unpack("<i", fdi[pos:pos+4])[0]; pos += 4

        for _ in range(fcount):
            if pos + 4 > len(fdi):
                break
            flen = struct.unpack("<i", fdi[pos:pos+4])[0]; pos += 4
            if flen <= 0 or pos + flen > len(fdi):
                break
            fname = fdi[pos:pos+flen].rstrip(b"\x00").decode("utf-8", errors="replace")
            pos += flen
            entry_idx = struct.unpack("<i", fdi[pos:pos+4])[0]; pos += 4
            full = dname + fname
            if full in targets:
                result[full] = entry_idx

    return result


# ─── Datei aus Spiel-Pak extrahieren ──────────────────────────────────────────

def extract_file(pak_path, enc_start, entry_idx):
    """
    Liest den Compact-Entry am Byte-Offset entry_idx,
    ermittelt den Datei-Offset im Pak und dekomprimiert den Inhalt.

    Compact-Entry-Layout (20 Bytes):
      bitfield(4) | field1(4) | file_offset(4) | field3(4) | field4(4)

    Inline-Entry-Header vor den Daten (73 Bytes):
      offset(8) | comp_size(8) | uncomp_size(8) | method(4) | sha1(20)
      | block_count(4) | block_start(8) | block_end(8) | encrypted(1) | block_size(4)
    """
    with open(pak_path, "rb") as f:
        f.seek(enc_start + entry_idx)
        compact = f.read(20)

    # Bytes 8–11 enthalten den 32-bit-Datei-Offset (little endian)
    file_offset = struct.unpack("<I", compact[8:12])[0]

    with open(pak_path, "rb") as f:
        f.seek(file_offset)
        hdr = f.read(73)

    comp_size   = struct.unpack("<Q", hdr[8:16])[0]
    uncomp_size = struct.unpack("<Q", hdr[16:24])[0]
    method      = struct.unpack("<I", hdr[24:28])[0]
    block_count = struct.unpack("<I", hdr[48:52])[0]

    blocks = [
        (struct.unpack("<Q", hdr[52+b*16:52+b*16+8])[0],
         struct.unpack("<Q", hdr[52+b*16+8:52+b*16+16])[0])
        for b in range(block_count)
    ]

    with open(pak_path, "rb") as f:
        chunks = []
        for bs, be in blocks:
            f.seek(file_offset + bs)
            chunk = f.read(be - bs)
            chunks.append(zlib.decompress(chunk) if method == 1 else chunk)

    return b"".join(chunks)


# ─── UE4-Namentabelle parsen ──────────────────────────────────────────────────

def get_names(uasset):
    """Gibt {index: name_string} aus der UE4-Namentabelle zurück."""
    pos = 28
    fn_len = struct.unpack("<i", uasset[pos:pos+4])[0]; pos += 4 + fn_len
    pos += 4  # PackageFlags
    name_count  = struct.unpack("<i", uasset[pos:pos+4])[0]; pos += 4
    name_offset = struct.unpack("<i", uasset[pos:pos+4])[0]

    cur = name_offset
    names = {}
    for i in range(name_count):
        nlen = struct.unpack("<i", uasset[cur:cur+4])[0]; cur += 4
        if nlen > 0:
            name = uasset[cur:cur+nlen].rstrip(b"\x00").decode(); cur += nlen
        else:
            name = uasset[cur:cur+(-nlen*2)].decode("utf-16-le").rstrip("\x00")
            cur += -nlen * 2
        cur += 4  # hash
        names[i] = name
    return names


# ─── BasePrice-Werte in uexp setzen ───────────────────────────────────────────

def set_base_prices(uexp, names, new_price=10.0):
    """
    Setzt alle BasePrice-FloatProperty-Werte in den uexp-Daten auf new_price.
    Gibt die modifizierten Bytes zurück.

    Tagged-Property-Layout (relevant für FloatProperty):
      [PropName FName (8)] [TypeName FName (8)] [Size int32 (4)] [ArrayIdx int32 (4)]
      [HasGuid byte (1)] [float value (4)]
    """
    float_idx = next(k for k, v in names.items() if v == "FloatProperty")
    bp_idx    = next(k for k, v in names.items() if v == "BasePrice")

    data = bytearray(uexp)
    count = 0
    for i in range(8, len(data) - 21):
        if (struct.unpack("<I", data[i:i+4])[0] == float_idx and
                struct.unpack("<I", data[i-8:i-4])[0] == bp_idx):
            data[i+17:i+21] = struct.pack("<f", new_price)
            count += 1

    print(f"    {count} BasePrice-Werte → {new_price} (original: 45–65000)")
    return bytes(data)


# ─── Pak v3 erstellen ─────────────────────────────────────────────────────────

def create_pak_v3(files_dict, output_path):
    """
    Erstellt eine UE4 Pak v3 Datei.

    files_dict: {virtual_path: file_bytes}

    Datei-Aufbau:
      [Inline-Entry-Header (73 Bytes) + komprimierte Daten] × n
      [Index-Daten]
      [Footer: Magic(4) + Version(4) + IndexOffset(8) + IndexSize(8) + SHA1(20)]
    """
    COMPRESSION_ZLIB = 1
    HEADER_SIZE = 73

    data_section = b""
    index_entries = []

    for vpath, file_bytes in files_dict.items():
        entry_offset = len(data_section)
        compressed   = zlib.compress(file_bytes, 6)
        sha1         = hashlib.sha1(file_bytes).digest()
        block_start  = HEADER_SIZE
        block_end    = HEADER_SIZE + len(compressed)

        inline  = struct.pack("<Q", entry_offset)
        inline += struct.pack("<Q", len(compressed))
        inline += struct.pack("<Q", len(file_bytes))
        inline += struct.pack("<I", COMPRESSION_ZLIB)
        inline += sha1
        inline += struct.pack("<I", 1)           # block count
        inline += struct.pack("<Q", block_start)
        inline += struct.pack("<Q", block_end)
        inline += b"\x00"                        # not encrypted
        inline += struct.pack("<I", len(file_bytes))  # block size
        assert len(inline) == HEADER_SIZE

        data_section += inline + compressed
        index_entries.append({
            "vpath": vpath, "offset": entry_offset,
            "size": len(compressed), "uncompressed_size": len(file_bytes),
            "sha1": sha1, "block_start": block_start, "block_end": block_end,
        })

    # Index aufbauen
    mount = b"../../../\x00"
    index_data  = struct.pack("<i", len(mount)) + mount
    index_data += struct.pack("<I", len(index_entries))

    for e in index_entries:
        vp = e["vpath"].encode() + b"\x00"
        index_data += struct.pack("<i", len(vp)) + vp
        index_data += struct.pack("<Q", e["offset"])
        index_data += struct.pack("<Q", e["size"])
        index_data += struct.pack("<Q", e["uncompressed_size"])
        index_data += struct.pack("<I", COMPRESSION_ZLIB)
        index_data += e["sha1"]
        index_data += struct.pack("<I", 1)                  # block count
        # Block-Offsets im Index sind ABSOLUTE Positionen im Pak-File
        # (relativ zum Entry-Anfang wäre falsch – nur für Entry 0 zufällig korrekt)
        index_data += struct.pack("<Q", e["offset"] + e["block_start"])
        index_data += struct.pack("<Q", e["offset"] + e["block_end"])
        index_data += b"\x00"                               # encrypted
        index_data += struct.pack("<I", 65536)              # block size (64 KB, Standard-UE4)

    index_offset = len(data_section)
    index_sha1   = hashlib.sha1(index_data).digest()

    # Footer: Magic + Version + IndexOffset + IndexSize + SHA1
    footer  = struct.pack("<I", 0x5A6F12E1)
    footer += struct.pack("<I", 3)
    footer += struct.pack("<Q", index_offset)
    footer += struct.pack("<Q", len(index_data))
    footer += index_sha1
    assert len(footer) == 44

    with open(output_path, "wb") as f:
        f.write(data_section + index_data + footer)

    total = len(data_section) + len(index_data) + len(footer)
    print(f"  → {output_path} ({total} Bytes, {len(files_dict)} Dateien)")


# ─── Hauptprogramm ────────────────────────────────────────────────────────────

def main():
    print("The Crust – Market Price Mod Creator")
    print("=====================================\n")

    print(f"[1] Pak-Footer lesen: {PAK_PATH}")
    version, idx_offset, idx_size = read_pak_footer(PAK_PATH)
    print(f"    Pak-Version {version}, Index bei Offset {idx_offset}\n")

    print("[2] Index-Header parsen …")
    enc_start, fdi_offset, fdi_size = read_index_header(PAK_PATH, idx_offset)
    print(f"    Encoded-Entries-Start: {enc_start}")
    print(f"    Full Directory Index:  Offset={fdi_offset}, Size={fdi_size}\n")

    print("[3] Zieldateien im Verzeichnis-Index suchen …")
    entry_map = find_entry_indices(PAK_PATH, fdi_offset, fdi_size, set(TARGET_FILES))
    for path, idx in sorted(entry_map.items()):
        print(f"    {path}  →  entry_idx={idx}")
    print()

    print("[4] Dateien extrahieren, Preise auf 1.0 setzen …")
    files_for_pak = {}
    for vpath in sorted(entry_map):
        eidx = entry_map[vpath]
        raw  = extract_file(PAK_PATH, enc_start, eidx)
        name = vpath.split("/")[-1]

        if vpath.endswith(".uexp"):
            # Zugehöriges uasset (bereits in files_for_pak)
            uasset_path = vpath.replace(".uexp", ".uasset")
            uasset_data = files_for_pak.get(uasset_path)
            if uasset_data is None:
                # uasset noch nicht verarbeitet – direkt extrahieren
                uasset_eidx = entry_map[uasset_path]
                uasset_data = extract_file(PAK_PATH, enc_start, uasset_eidx)
            names  = get_names(uasset_data)
            print(f"  {name}:")
            raw = set_base_prices(raw, names, new_price=10.0)

        files_for_pak[vpath] = raw

    print()
    print("[5] Mod-Pak erstellen …")
    create_pak_v3(files_for_pak, OUTPUT_PAK)

    print("\nFertig!")
    print("\nInstallation:")
    install_dir = os.path.expanduser(
        "~/.local/share/Steam/steamapps/common/The Crust/TheCrust/Content/Paks/~mods/"
    )
    print(f"  mkdir -p \"{install_dir}\"")
    print(f"  cp \"{OUTPUT_PAK}\" \"{install_dir}\"")


if __name__ == "__main__":
    main()
