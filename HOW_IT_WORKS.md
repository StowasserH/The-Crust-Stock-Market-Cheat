# The Crust – Market Price Mod: Dokumentation

Wie dieser Mod entstand, wie die Pak-Dateien dekodiert wurden und welche
Strategien dabei zum Einsatz kamen.

---

## Inhaltsverzeichnis

1. [Ziel](#ziel)
2. [Werkzeuge und Voraussetzungen](#werkzeuge-und-voraussetzungen)
3. [Schritt 1 – Spielinstallation erkunden](#schritt-1--spielinstallation-erkunden)
4. [Schritt 2 – Das UE4-Pak-Format verstehen](#schritt-2--das-ue4-pak-format-verstehen)
5. [Schritt 3 – Pak v11: Index und Verzeichnis-Index lesen](#schritt-3--pak-v11-index-und-verzeichnis-index-lesen)
6. [Schritt 4 – Compact Entries dekodieren](#schritt-4--compact-entries-dekodieren)
7. [Schritt 5 – Dateidaten extrahieren und dekomprimieren](#schritt-5--dateidaten-extrahieren-und-dekomprimieren)
8. [Schritt 6 – UE4-Asset-Format (.uasset / .uexp) verstehen](#schritt-6--ue4-asset-format-uasset--uexp-verstehen)
9. [Schritt 7 – BasePrice-Werte modifizieren](#schritt-7--baseprice-werte-modifizieren)
10. [Schritt 8 – Neues Pak v3 erstellen](#schritt-8--neues-pak-v3-erstellen)
11. [Schritt 9 – Crash-Analyse und Fix](#schritt-9--crash-analyse-und-fix)
12. [Lessons Learned](#lessons-learned)
13. [Referenzen](#referenzen)

---

## Ziel

Alle Ressourcenpreise im Stock Market des Spiels „The Crust" (Unreal Engine 4.27)
auf einen sehr niedrigen Wert setzen, indem die relevanten Data-Assets als
`.pak`-Mod überschrieben werden.

---

## Werkzeuge und Voraussetzungen

| Was | Warum |
|-----|-------|
| Python 3 (stdlib: `struct`, `zlib`, `hashlib`) | Pak lesen/schreiben, zlib-Kompression, SHA-1 |
| Spielinstallation | Originale Assets als Basis |
| Hex-Dump (`xxd`) | Binärstruktur manuell prüfen |
| `strings` | Textinhalte in Binärdateien aufspüren |

Keine externen Abhängigkeiten, keine Drittanbieter-Tools wie UModel oder FModel
notwendig – alles mit Python-Bordmitteln.

---

## Schritt 1 – Spielinstallation erkunden

### Wo liegt das Spiel?

```
~/.local/share/Steam/steamapps/common/The Crust/
└── TheCrust/Content/Paks/
    ├── pakchunk0-WindowsNoEditor.pak   (~5,2 GB, Hauptarchiv)
    ├── pakchunk1-WindowsNoEditor.pak
    └── pakchunk0optional-WindowsNoEditor.pak
```

### Bestehendes Mod als Referenz

Im Arbeitsverzeichnis lag bereits `500-Market_Cheat_weigh_P.pak` (1,9 KB).
Mit `strings` ließ sich schnell erkennen, was darin steckt:

```
TheCrust/Content/Blueprints/Market/DA_GlobalMarket.uasset
TheCrust/Content/Blueprints/Market/DA_GlobalMarket.uexp
```

**Erkenntnis 1:** Der Mod überschreibt gezielt zwei Dateien innerhalb des Spiel-Paks.
Das `_P`-Suffix kennzeichnet einen „Patch"-Pak mit höherer Ladepriorität. Das
Zahl-Präfix (`500-`) steuert die Priorität unter mehreren Mods.

**Erkenntnis 2:** Die bestehende Mod referenziert `DA_GlobalMarket` (ohne Nummer),
das aktuelle Spiel verwendet `DA_GlobalMarket_1` bis `_4`. Die alte Mod ist daher
wirkungslos – ein Hinweis, dass das Spiel zwischenzeitlich aktualisiert wurde.

---

## Schritt 2 – Das UE4-Pak-Format verstehen

### Allgemeine Struktur

Eine `.pak`-Datei besteht aus drei Bereichen:

```
┌─────────────────────────────┐
│  Datendaten (Data Section)  │  ← komprimierte Dateiinhalte
│  Index                      │  ← Verzeichnis der Einträge
│  Footer (44 Bytes)          │  ← Pak-Version, Index-Offset, SHA-1
└─────────────────────────────┘
```

### Footer (letzten 44 Bytes)

```
Offset  Größe  Beschreibung
──────  ─────  ──────────────────────────────────
0       4      Magic: 0x5A6F12E1 (LE)
4       4      Version: z. B. 3 (alt) oder 11 (neu)
8       8      Index-Offset (absolut im Pak)
16      8      Index-Größe in Bytes
24      20     SHA-1-Hash des Index-Bereichs
```

**Strategie:** Footer immer von hinten lesen (`seek(-44, 2)` ist schon falsch,
weil v11 einen längeren Footer haben kann). Besser: die letzten 256 Bytes lesen
und darin das Magic `E1 12 6F 5A` rückwärts suchen.

```python
with open(pak_path, "rb") as f:
    f.seek(-256, 2)
    tail = f.read(256)
pos = tail.rfind(bytes.fromhex("e1126f5a"))
version    = struct.unpack("<I", tail[pos+4:pos+8])[0]
idx_offset = struct.unpack("<Q", tail[pos+8:pos+16])[0]
idx_size   = struct.unpack("<Q", tail[pos+16:pos+24])[0]
```

---

## Schritt 3 – Pak v11: Index und Verzeichnis-Index lesen

Das Spiel-Pak verwendet **Version 11** (UE 4.25+). Ab v8 änderte Epic Games den
Index grundlegend: Statt einer flachen Dateiliste gibt es jetzt drei separate
Bereiche.

### Index-Header (v8+)

```
Mount Point (FString)
File Count (int32)           ← Anzahl "Encoded Entries"
Path Hash Seed (int64)
Has Path Hash Index (int32)
  → Path Hash Index Offset (int64)
  → Path Hash Index Size   (int64)
  → Path Hash Index SHA-1  (20 Bytes)
Has Full Directory Index (int32)
  → Full Directory Index Offset (int64)
  → Full Directory Index Size   (int64)
  → Full Directory Index SHA-1  (20 Bytes)
Encoded Entries Size (int32) ← Gesamtgröße der kompakten Einträge
Encoded Entries Data …       ← ab hier folgen die eigentlichen Metadaten
```

**Wichtig:** Der Mount Point ist `../../../` – relative Pfade im Pak sind
relativ zum Spielverzeichnis.

### Full Directory Index (FDI)

Der FDI enthält die Klartextnamen aller Dateien im Pak:

```
Directory Count (int32)
Für jedes Verzeichnis:
  Name-Länge (int32)
  Name (null-terminierter String)
  Datei-Anzahl (int32)
  Für jede Datei:
    Name-Länge (int32)
    Name (null-terminierter String)
    Entry-Index (int32)      ← Byte-Offset in "Encoded Entries Data"
```

Mit einer einfachen Schleife lassen sich so alle Dateinamen und ihre
Entry-Indizes auslesen:

```python
pos = 0
dir_count = struct.unpack("<i", fdi[pos:pos+4])[0]; pos += 4
for _ in range(dir_count):
    dname_len = struct.unpack("<i", fdi[pos:pos+4])[0]; pos += 4
    dname = fdi[pos:pos+dname_len].rstrip(b"\x00").decode(); pos += dname_len
    fcount = struct.unpack("<i", fdi[pos:pos+4])[0]; pos += 4
    for _ in range(fcount):
        fname_len = struct.unpack("<i", fdi[pos:pos+4])[0]; pos += 4
        fname = fdi[pos:pos+fname_len].rstrip(b"\x00").decode(); pos += fname_len
        entry_idx = struct.unpack("<i", fdi[pos:pos+4])[0]; pos += 4
        print(f"{dname}{fname} → entry_idx={entry_idx}")
```

---

## Schritt 4 – Compact Entries dekodieren

Das v11-Format speichert Datei-Metadaten als kompakte 20-Byte-Einträge.
Das Format ist nicht öffentlich dokumentiert; es wurde durch Hex-Inspektion
rekonstruiert.

### Vorgehen

Die Entry-Indizes der gesuchten Dateien waren: 183732, 183752, 183772 …
(20-Byte-Abstände → bestätigt die feste Größe).

Rohdaten eines Compact-Entry (20 Bytes):

```
Byte  0– 3: Bitfield (Kompressionsmethode, Flags)
Byte  4– 7: Feld 1 (komprimierte Größe o. ä.)
Byte  8–11: Datei-Offset (32-Bit, absolut im Pak)   ← das Wichtige
Byte 12–15: Feld 3
Byte 16–19: Feld 4
```

**Strategie:** Anstatt das gesamte Bitfield-Format zu reverse-engineeren,
wurde der Offset-Kandidat (Bytes 8–11) direkt getestet – indem an dieser
Position im Pak nach dem zlib-Magic `78 9C` gesucht wurde:

```python
file_offset = struct.unpack("<I", compact[8:12])[0]
with open(pak_path, "rb") as f:
    f.seek(file_offset + 73)   # 73 = Größe des Inline-Entry-Headers
    probe = f.read(2)
# Ergebnis: b'\x78\x9c' → zlib-Daten bestätigt!
```

---

## Schritt 5 – Dateidaten extrahieren und dekomprimieren

Jede Datei im Pak beginnt mit einem **Inline-Entry-Header** (73 Bytes),
gefolgt von den komprimierten Blöcken.

### Inline-Entry-Header-Format

```
Offset  Größe  Beschreibung
──────  ─────  ──────────────────────────────────────
0       8      Datei-Offset im Pak (Selbstreferenz, hier 0)
8       8      Komprimierte Größe
16      8      Unkomprimierte Größe
24      4      Kompressionsmethode (1 = zlib)
28      20     SHA-1-Hash der unkomprimierten Daten
48      4      Anzahl Kompressionsblöcke
52      8      Block-Start (relativ zum Entry-Beginn)
60      8      Block-Ende  (relativ zum Entry-Beginn)
68      1      Verschlüsselt (0 = nein)
69      4      Block-Größe
──────  ─────
Gesamt: 73 Bytes → danach folgen sofort die zlib-Daten
```

**Warum 73 Bytes?** Das deckt sich mit dem Format des alten Pak v3-Mods
(dort war `block_start=73`), was die Interpretation bestätigt.

### Extraktion

```python
with open(pak_path, "rb") as f:
    f.seek(file_offset)
    hdr = f.read(73)

comp_size   = struct.unpack("<Q", hdr[8:16])[0]
block_start = struct.unpack("<Q", hdr[52:60])[0]   # = 73
block_end   = struct.unpack("<Q", hdr[60:68])[0]

with open(pak_path, "rb") as f:
    f.seek(file_offset + block_start)
    compressed = f.read(block_end - block_start)

data = zlib.decompress(compressed)
```

---

## Schritt 6 – UE4-Asset-Format (.uasset / .uexp) verstehen

UE4 teilt Assets in zwei Dateien auf:

| Datei | Inhalt |
|-------|--------|
| `.uasset` | Header: Namentabelle, Import-/Export-Tabellen, Metadaten |
| `.uexp` | Eigentliche Property-Daten (Werte der Felder) |

### uasset: Namentabelle lesen

Der Header beginnt mit dem UE4-Magic `0x9E2A83C1`, gefolgt von
Versionsinformationen. Die Namentabelle (Name Table) liegt an einem
im Header angegebenen Offset:

```
Magic        (4)  = 0x9E2A83C1
LegacyVersion(4)  = -7  (UE 4.25+)
UE3Version   (4)  = 0
UE4Version   (4)  = 0
Licensee     (4)  = 0
CustomVerCount(4) = 0
TotalHdrSize (4)
FolderName   (FString)
PackageFlags (4)
NameCount    (4)  ← z. B. 53
NameOffset   (4)  ← Byte-Position der Namentabelle
…
```

Jeder Namentabelleneintrag besteht aus:

```
Länge (int32) → positiv = UTF-8, negativ = UTF-16
String-Bytes (inkl. Null-Terminator)
Hash (4 Bytes, ignorieren)
```

So erhält man ein `{index: name}`-Dictionary:

```python
{
     0: '/Game/Blueprints/Market/DA_GlobalMarket_1',
     4: 'BasePrice',
    41: 'FloatProperty',
    46: 'None',
    49: 'ResourcePriceInfos',
    50: 'ResourceType',
    51: 'StructProperty',
    …
}
```

### uexp: Tagged Properties

UE4 serialisiert Objekt-Properties im „Tagged Format":

```
PropertyName  (FName = 8 Bytes: index + number)
TypeName      (FName = 8 Bytes)
DataSize      (int32 = 4 Bytes)
ArrayIndex    (int32 = 4 Bytes)
[HasGuid]     (1 Byte, meist 0)
[Value]       (DataSize Bytes)
```

Ein `FName` ist ein 64-Bit-Wert: 32-Bit-Index in die Namentabelle + 32-Bit-Nummer
(meist 0 für „keine Wiederholung").

Eine `FloatProperty` mit dem Namen `BasePrice` sieht so aus:

```
04 00 00 00 00 00 00 00   ← FName[4] = "BasePrice"
29 00 00 00 00 00 00 00   ← FName[41] = "FloatProperty"
04 00 00 00               ← DataSize = 4 Bytes
00 00 00 00               ← ArrayIndex = 0
00                        ← HasGuid = false
00 00 20 41               ← float32 LE = 10.0
```

---

## Schritt 7 – BasePrice-Werte modifizieren

### Suchstrategie

Statt den gesamten Property-Baum rekursiv zu parsen, wurde ein gezielter
Byte-Scan verwendet:

1. Finde alle Positionen, an denen `FName = "FloatProperty"` steht (Index 41).
2. Prüfe, ob 8 Bytes davor `FName = "BasePrice"` steht (Index 4).
3. Überschreibe die 4 Float-Bytes an Position `+17` relativ zu `FloatProperty`.

```python
float_idx = 41   # "FloatProperty"
bp_idx    =  4   # "BasePrice"

data = bytearray(uexp)
for i in range(8, len(data) - 21):
    if struct.unpack("<I", data[i:i+4])[0] == float_idx:
        if struct.unpack("<I", data[i-8:i-4])[0] == bp_idx:
            data[i+17:i+21] = struct.pack("<f", 10.0)
```

Dieser Ansatz ist robust gegenüber unbekannten verschachtelten Strukturen,
da er keinen vollständigen Parser benötigt.

### Ergebnis

Jede der 4 Dateien enthält **27 Ressourcen** mit Originalpreisen von 45 bis 65.000.
Alle 27 × 4 = **108 BasePrice-Werte** wurden auf 10.0 gesetzt.

---

## Schritt 8 – Neues Pak v3 erstellen

Für den Mod wird absichtlich das einfachere **Pak-Format v3** verwendet (statt v11).
UE4 akzeptiert v3-Mods auch in neueren Spielversionen, da der Engine-Pak-Loader
abwärtskompatibel ist.

### Aufbau einer v3-Pak-Datei

```
┌──────────────────────────────────────────────────────────────┐
│ Für jede Datei:                                              │
│   Inline-Entry-Header (73 Bytes)                             │
│   zlib-komprimierter Dateiinhalt                             │
├──────────────────────────────────────────────────────────────┤
│ Index:                                                       │
│   Mount Point Length (int32)                                 │
│   Mount Point String ("../../../\0")                         │
│   File Count (int32)                                         │
│   Für jede Datei:                                            │
│     Path Length (int32) + Path String                        │
│     Offset (int64)                                           │
│     Compressed Size (int64)                                  │
│     Uncompressed Size (int64)                                │
│     Compression Method (int32) = 1 (zlib)                   │
│     SHA-1 (20 Bytes)                                         │
│     Block Count (int32) = 1                                  │
│     Block Start (int64), Block End (int64)                   │
│     Encrypted (1 Byte) = 0                                   │
│     Block Size (int32) = 0                                   │
├──────────────────────────────────────────────────────────────┤
│ Footer (44 Bytes):                                           │
│   Magic   (4)  = 0x5A6F12E1                                  │
│   Version (4)  = 3                                           │
│   Index Offset (8)                                           │
│   Index Size   (8)                                           │
│   SHA-1 des Index (20)                                       │
└──────────────────────────────────────────────────────────────┘
```

### Dateiname und Priorität

```
500-Market_Price10_P.pak
│    │              │
│    │              └─ "_P" = Patch/Mod-Kennung
│    └──────────────── sprechender Name
└───────────────────── "500" = hohe Ladepriorität (überschreibt Basis-Paks)
```

### Installation

```bash
MODS_DIR="$HOME/.local/share/Steam/steamapps/common/The Crust/TheCrust/Content/Paks/~mods"
mkdir -p "$MODS_DIR"
cp 500-Market_Price10_P.pak "$MODS_DIR/"
```

---

## Schritt 9 – Crash-Analyse und Fix

### Crash 1: BasePrice = 1.0 (Fehlannahme)

Beim ersten Test crashte das Spiel sofort:

```
Fatal error!
Unhandled Exception: EXCEPTION_INT_DIVIDE_BY_ZERO
SecondsSinceStart: 0
Thread: GameThread
```

### Ursache

`EXCEPTION_INT_DIVIDE_BY_ZERO` ist eine **CPU-Exception** (x86 `idiv`-Befehl).
Sie tritt nur bei **Integer**-Division auf, nicht bei Float.

Das Spiel berechnet intern – wahrscheinlich für UI-Anzeige oder Marktinitialisierung:

```cpp
int32 minPrice = FMath::TruncToInt(BasePrice * MaxPriceNegativeDeviation);
// BasePrice=1.0, MaxNegDev=0.5 → TruncToInt(0.5) = 0
int32 result = someValue / minPrice;  // → EXCEPTION_INT_DIVIDE_BY_ZERO
```

### Beweis

Original-Werte aus dem Spiel:

| Ressource | BasePrice | MaxNegDev | `int(BP × ND)` |
|-----------|-----------|-----------|----------------|
| Aluminium | 50.0 | 0.5 | **25** ✓ |
| (Mod)     | 1.0  | 0.5 | **0**  ✗ crash |

### Fix

Mindest-sichere `BasePrice` bei `MaxNegDev = 0.5` (dem kleinsten vorkommenden Wert):

```
BasePrice × 0.5 ≥ 1.0  →  BasePrice ≥ 2.0
```

Mit Sicherheitsabstand: **`BasePrice = 10.0`**

```
10.0 × 0.5 = 5.0  →  int = 5  ✓
10.0 × 0.7 = 7.0  →  int = 7  ✓
```

Das ist immer noch **4–6.500× billiger** als die Originalpreise (45–65.000).

### Crash 2: Identischer Callstack trotz BasePrice = 10.0

Nach dem Fix auf 10.0 crashte das Spiel mit **exakt demselben Callstack-Hash**
(`5B38F7AB64D0F71D61884EAA2CE6B70DC4C79994`). Das bewies: `BasePrice` war nie
die eigentliche Ursache – nur ein Ablenkungsmanöver.

**Diagnose:** Vergleich der Index-Einträge zwischen dem funktionierenden
Original-Mod und unserem erzeugten Pak:

```
Original-Mod:   block_size im Index = 65536   ✓
Unsere Mod:     block_size im Index = 0        ✗  ← BUG
```

UE4 berechnet beim Laden eines komprimierten Assets die Anzahl der
Kompressionsblöcke:

```cpp
int32 numBlocks = FMath::DivideAndRoundUp(UncompressedSize, CompressionBlockSize);
//  CompressionBlockSize = 0  →  EXCEPTION_INT_DIVIDE_BY_ZERO
```

Das Feld `CompressionBlockSize` im Pak-Index-Eintrag gibt die maximale Größe
eines einzelnen Kompressionsblocks an (Standard: 65536 Bytes = 64 KB).
Unser Pak-Creator hatte dort fälschlicherweise `0` eingetragen.

**Fix:** Eine Zeile in `create_pak_v3`:

```python
# vorher (falsch):
index_data += struct.pack("<I", 0)
# nachher (korrekt):
index_data += struct.pack("<I", 65536)  # Standard-UE4-Blockgröße
```

**Wichtige Erkenntnis:** Wenn zwei Crashes mit unterschiedlichen Parametern
denselben Callstack-Hash haben, liegt die Ursache im Pak-Format selbst,
nicht in den Asset-Werten.

---

## Lessons Learned

### 1. Footer-Suche statt fixer Offsets

Nicht `seek(-44, 2)` verwenden – das funktioniert nur für v3. Stattdessen
die letzten 256 Bytes lesen und das Magic darin suchen. Robuster gegenüber
zukünftigen Versionen.

### 2. Byte-Scan statt vollständiger Parser

Für gezielte Modifikationen reicht ein Byte-Scan nach bekannten FName-Indices.
Ein vollständiger Property-Parser wäre zwar korrekter, aber viel aufwändiger
und fehleranfälliger bei unbekannten Property-Typen.

### 3. v3 für Mod-Paks

Mod-Paks können immer im alten Format v3 erstellt werden. Der UE4-Loader
unterstützt v3 auch in aktuellen Spielen. Das spart die Implementierung des
komplexen v11-Formats mit Path-Hash-Index und Full-Directory-Index.

### 4. Float-Werte vs. Integer-Logik

Auch wenn ein Feld im Data Asset als `FloatProperty` definiert ist, können
Spielcode-Pfade diesen Wert als Integer behandeln (z. B. für
Preiskategorien, UI-Ticks, Datenbankschlüssel). Zu kleine Float-Werte
(< 1.0 nach Truncation) können Integer-Divisionen crashen.
**Faustregel:** `BasePrice × min(MaxNegativeDeviation) ≥ 1.0`.

### 5. Gleicher Callstack-Hash = Pak-Formatfehler, nicht Asset-Werte

Wenn zwei Crashes mit unterschiedlichen Asset-Werten (1.0 vs. 10.0) denselben
`PCallStackHash` haben, ist die Ursache im Pak-Format zu suchen, nicht in den
Daten. Sofort den eigenen Pak-Writer mit dem Original-Mod-Pak vergleichen
(Hex-Dump der Index-Einträge).

### 6. Block-Offsets im Index sind **absolute** Pak-Positionen

Die `CompressionBlock.CompressedStart/End`-Felder im Index-Eintrag sind
**absolute Byte-Positionen im Pak-File**, nicht relativ zum Entry-Offset.

```python
# FALSCH (relativ):
index_data += struct.pack("<Q", 73)                    # block_start
index_data += struct.pack("<Q", 73 + compressed_size)  # block_end

# RICHTIG (absolut):
index_data += struct.pack("<Q", entry_offset + 73)
index_data += struct.pack("<Q", entry_offset + 73 + compressed_size)
```

Der Fehler ist bei der ersten Datei (entry_offset=0) nicht sichtbar –
dort sind relativ und absolut identisch. Erst ab der zweiten Datei
liest UE4 an der falschen Position, Decompression schlägt fehl:
`LowLevelFatalError: Retry was NOT successful.`

### 7. `CompressionBlockSize = 65536` im Pak-Index ist Pflicht

Das Feld `CompressionBlockSize` (letztes int32 im Index-Eintrag) muss auf
`65536` gesetzt sein – auch wenn die Datei kleiner als 64 KB ist und nur
einen einzigen Kompressionsblock hat. UE4 dividiert durch diesen Wert bei
der Block-Berechnung. Wert `0` → sofortiger Absturz beim Laden.

### 7. Mod-Kompatibilität bei Spielupdates

Mods, die `DA_GlobalMarket` (ohne Nummer) ansprechen, funktionieren nicht
mehr, wenn das Spiel auf `DA_GlobalMarket_1` bis `_4` umgestellt hat.
Der `create_mod.py` liest die Zieldateien dynamisch aus dem FDI –
bei Spielupdates einfach `TARGET_FILES` anpassen und das Skript neu ausführen.

---

## Referenzen

- UE4-Pak-Format: [github.com/nicklvsa/go-ue4pak](https://github.com/nicklvsa/go-ue4pak)
- UE4-Property-Serialisierung: [Unreal Engine Documentation – Asset Management](https://docs.unrealengine.com/4.27/en-US/ProductionPipelines/AssetManagement/)
- Pak-Version 8+ (Path Hash Index): [UE4-Source FPakFile.h](https://github.com/EpicGames/UnrealEngine/blob/release/Engine/Source/Runtime/PakFile/Public/IPlatformFilePak.h)
- zlib-Magic-Bytes: `78 9C` (default compression), `78 DA` (best compression)
- IEEE 754 float32: `00 00 20 41` = 10.0, `00 00 80 3F` = 1.0
