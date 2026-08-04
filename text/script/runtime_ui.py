"""Build the text-owned data contract consumed by runtime patch composers."""

import hashlib
import json
from pathlib import Path

from project_paths import FONT_GENERATED_ROOT, TEXT_CORPUS_ROOT, TEXT_GENERATED_ROOT
from text.script.output_files import OutputFiles

OUTPUT_PATH = TEXT_GENERATED_ROOT / "runtime_ui" / "engine.json"
INPUTS = {
    "status_tables": Path("mirrored_words/NORMCOM.tables.json"),
    "demon_names": Path("fixed_bytes/DVLNAME.DAT.json"),
    "character_names": Path("fixed_bytes/CHARNAME.DAT.json"),
    "magic_names": Path("name_description/MAGNAME.DAT.json"),
    "combat_affinities": Path("mirrored_words/COMBAT.analysis_affinities.json"),
    "combat_result_labels": Path("fixed_bytes/COMBAT.result_labels.json"),
    "fusion_messages": Path("eve/SHOPSMP.EVE.json"),
    "dungeon_marker_names": Path("runtime_ui/dungeon_marker_names.json"),
    "equipment_ui": Path("runtime_ui/equipment_ui.json"),
    "healing_ui": Path("runtime_ui/healing_ui.json"),
    "name_entry": Path("runtime_ui/name_entry.json"),
    "shop_ui": Path("runtime_ui/shop_ui.json"),
}
CAPABILITIES = (
    "combat_vwf",
    "dungeon_locations",
    "equipment_ui",
    "fusion_menu",
    "msgr_text",
    "name_runtime",
    "smallfont_vwf",
    "status_ui",
)
FONT_BINDINGS = {
    "font8_metrics": "font8_metrics.json",
    "font12_metrics": "font12_metrics.json",
    "font16_metrics": "font16_metrics.json",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_runtime_ui_contract(
    corpus_root: Path = TEXT_CORPUS_ROOT,
    font_generated_root: Path = FONT_GENERATED_ROOT,
) -> str:
    inputs = {}
    sections = {}
    for name, relative in INPUTS.items():
        path = corpus_root / relative
        raw = path.read_bytes()
        inputs[name] = {
            "path": relative.as_posix(),
            "sha256": sha256(raw),
        }
        sections[name] = json.loads(raw)

    bindings = {}
    for name, filename in FONT_BINDINGS.items():
        path = font_generated_root / filename
        bindings[name] = {"path": filename, "sha256": sha256(path.read_bytes())}

    section_bindings = {
        name: {
            "path": f"runtime_ui/sections/{name}.json",
            "sha256": sha256(
                (
                    json.dumps(section, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n"
                ).encode("utf-8")
            ),
        }
        for name, section in sections.items()
    }
    body = {
        "version": 1,
        "kind": "engine_runtime_ui",
        "inputs": inputs,
        "font_bindings": bindings,
        "required_capabilities": list(CAPABILITIES),
        "section_bindings": section_bindings,
        "sections": sections,
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    body["contract_sha256"] = sha256(canonical)
    return json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_runtime_ui_contract(outputs: OutputFiles) -> None:
    contract_text = build_runtime_ui_contract()
    document = json.loads(contract_text)
    for name, section in document["sections"].items():
        section_text = (
            json.dumps(section, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        path = TEXT_GENERATED_ROOT / document["section_bindings"][name]["path"]
        outputs.text(path, section_text)
    outputs.text(OUTPUT_PATH, contract_text)
    print(f"Runtime UI contract -> {OUTPUT_PATH}")


if __name__ == "__main__":
    write_runtime_ui_contract(OutputFiles(check=False))
