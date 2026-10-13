"""What the report's front page and provenance block say, as Markdown strings (HTMLPROV-01, D-6).

The notebook's Cell 2 and Cell 7 render these and build nothing themselves. The block used to
print the binding key, the analyst's local paths and the raw digest method (``git_blob_oid``). A
reader gets the project's name, file basenames and the method in words instead. The full paths
stay in ``provenance.json``, where the analyst has them.

Strings only: nothing here calls ``display()``.
"""
from __future__ import annotations

from pathlib import PureWindowsPath
from typing import Any, Mapping

from src.final.deliverable import MANIFEST_NAME
from src.final.product import PRODUCT_LINE

#: How each digest was computed, in words. The stored method value is unchanged: the golden
#: manifests hold it as data. A method missing here fails loudly rather than printing its code.
DIGEST_METHOD_WORDS = {
    "git_blob_oid": "git blob id",
    "sha256_bytes": "SHA-256 of the file's bytes",
}


def front_page_markdown(inputs: Any) -> str:
    """The title, the product line and, where the project declares one, its note."""
    lines = [f"# {inputs.project_display_name}", "", f"**{PRODUCT_LINE}**"]
    if inputs.project_note:
        lines += ["", f"*{inputs.project_note}*"]
    return "\n".join(lines)


def run_identity_markdown(inputs: Any, provenance: Mapping[str, Any]) -> str:
    params = provenance["params"]
    text = (
        f"**Project:** {inputs.project_public_name}  \n"
        f"**Run date:** {provenance['run_date']}  \n"
        f"**Iterations:** {params['iterations']:,}  \n"
        f"**Seed:** {params['seed']}  \n"
        f"**Day rate:** ${params['day_rate']:,.0f}/wd  \n"
        f"**Engine SHA:** `{provenance['engine_sha']}`"
    )
    if provenance["engine_tree_dirty"]:
        text += "  *(working tree dirty)*"
    return text


def basename(path: Any) -> str:
    """The file's name alone, whichever separator the recorded path used."""
    return PureWindowsPath(str(path)).name


def artefacts_markdown(artefacts: list[Any]) -> str:
    """Files by basename. The run folder is named by its role (R-8): its basename is
    ``<date>_<binding key>`` (``manifest_path``), and the key is not the project's name.

    The folder is recognised as the one holding the run's manifest, which is how
    ``manifest_path`` builds both - never by asking the disk, so a re-render where the folder is
    gone prints the same page (gate 3 round 1, W1)."""
    paths = [PureWindowsPath(str(p)) for p in artefacts]
    run_folders = {p.parent for p in paths if p.name == MANIFEST_NAME}
    return "\n".join(
        "- the run folder (state cache and provenance)" if p in run_folders else f"- `{p.name}`"
        for p in paths)


def provenance_markdown(provenance: Mapping[str, Any]) -> str:
    lines = [
        "**Provenance:** input digests are per file, so a same-filename re-issue of any one "
        "input is diagnosable. Full paths are in the run's `provenance.json`.",
        "",
    ]
    for name, d in provenance["input_sha256"].items():
        lines.append(f"- {name}: {DIGEST_METHOD_WORDS[d['method']]} `{d['value'][:16]}...`")
    return "\n".join(lines)
