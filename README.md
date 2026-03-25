# The Crust – Market Price Mod

A mod for **The Crust** (Steam) that sets all stock market resource prices to **10** — making them **4× to 6,500× cheaper** than the original values (45–65,000).

> **NexusMods:** https://www.nexusmods.com/thecrust/mods/18

---

## What it does

The mod patches the four market data assets (`DA_GlobalMarket_1` through `_4`) and sets all 108 `BasePrice` float values to `10.0`.

| | Original | Modded |
|---|---|---|
| Cheapest resource | 45 | 10 |
| Most expensive resource | 65,000 | 10 |

> **Why 10 and not 1?**
> The game computes `minPrice = int(BasePrice × MaxPriceNegativeDeviation)` internally.
> With `BasePrice = 1.0` and `MaxNegDev = 0.5`, this yields `int(0.5) = 0`, triggering an `EXCEPTION_INT_DIVIDE_BY_ZERO` crash.
> `BasePrice = 10.0` is the safe minimum with a comfortable margin: `10 × 0.5 = 5 > 0` ✓

---

## Installation

### Pre-built mod (recommended)

1. Download `500-Market_Price10_P.pak` from the [Releases](../../releases) page or [NexusMods](https://www.nexusmods.com/thecrust/mods/18).
2. Create the mods folder if it does not exist:
   ```bash
   mkdir -p ~/.local/share/Steam/steamapps/common/The\ Crust/TheCrust/Content/Paks/~mods/
   ```
3. Copy the file there:
   ```bash
   cp 500-Market_Price10_P.pak ~/.local/share/Steam/steamapps/common/The\ Crust/TheCrust/Content/Paks/~mods/
   ```
4. Launch the game — prices are immediately in effect.

### Uninstall

Delete the file from the `~mods` folder and restart the game.

---

## Build it yourself

If you want to regenerate the mod from the game's own files (e.g. after a game update):

**Requirements:**
- Python 3 (standard library only — no third-party packages needed)
- The Crust installed via Steam

**Run:**
```bash
python3 create_mod.py
```

The script reads `DA_GlobalMarket_1` through `_4` directly from the game's main pak, patches all `BasePrice` values, and writes a fresh `500-Market_Price10_P.pak`.

If the game updates and renames the market assets again, adjust `TARGET_FILES` in `create_mod.py` accordingly.

---

## How it works

The mod is a UE4 **Pak v3 patch file** (`_P` suffix = higher load priority, `500-` prefix = priority order).
It overrides the game's market data assets without modifying any original game files.

The Python script (`create_mod.py`):
1. Parses the game's **Pak v11** index (UE 4.25+ format) to locate the target assets.
2. Extracts and decompresses the `.uasset` / `.uexp` pairs using zlib.
3. Scans the UE4 tagged-property binary data and patches every `FloatProperty` named `BasePrice` to `10.0`.
4. Packages the modified assets into a new **Pak v3** file (UE4's loader is fully backwards-compatible with v3).

For a full technical deep-dive, see [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

---

## Compatibility

- Game: **The Crust** (tested with the version shipping `DA_GlobalMarket_1` – `_4`)
- Platform: Linux (Steam) — Windows paths differ, but the mod file itself is cross-platform
- No mod manager required

---

## License

[MIT](LICENSE)
