"""
NCBI taxonomy resolver — taxid -> lineage, built from the standard taxdump
(nodes.dmp + names.dmp). Used to map BLAST-DB records (which only carry a
taxid) onto one of Synth Veda's 6 routes. Sources that already embed a
lineage string in their own format (BOLD's columns, MIDORI2/SILVA/UNITE
FASTA headers) don't need this — see routing.py for those.
"""
from __future__ import annotations

import functools
from pathlib import Path

# Ranks we actually care about for routing. Anything else in the lineage
# chain (no rank, subclass, etc.) is skipped.
_WANTED_RANKS = {"superkingdom", "kingdom", "phylum", "class", "order", "family", "genus", "species"}


class TaxonomyResolver:
    def __init__(self, taxdump_dir: Path | str):
        self._dir = Path(taxdump_dir)
        self._parent: dict[int, int] = {}
        self._rank: dict[int, str] = {}
        self._name: dict[int, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return

        nodes_path = self._dir / "nodes.dmp"
        names_path = self._dir / "names.dmp"

        with open(nodes_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                fields = [f.strip() for f in line.split("|")]
                taxid = int(fields[0])
                parent = int(fields[1])
                rank = fields[2]
                self._parent[taxid] = parent
                self._rank[taxid] = rank

        with open(names_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                fields = [f.strip() for f in line.split("|")]
                taxid = int(fields[0])
                name_txt = fields[1]
                name_class = fields[3]
                if name_class == "scientific name":
                    self._name[taxid] = name_txt

        self._loaded = True

    @functools.lru_cache(maxsize=200_000)
    def lineage(self, taxid: int) -> dict[str, str]:
        """
        Walk taxid up to the root, returning {rank: scientific_name} for
        every rank in _WANTED_RANKS found along the way. Empty dict if the
        taxid is unknown (e.g. deleted/merged node not worth chasing here).
        """
        self._load()
        result: dict[str, str] = {}
        current = taxid
        seen = set()
        while current in self._parent and current not in seen and current != 1:
            seen.add(current)
            rank = self._rank.get(current)
            if rank in _WANTED_RANKS and rank not in result:
                name = self._name.get(current)
                if name:
                    result[rank] = name
            parent = self._parent.get(current)
            if parent is None or parent == current:
                break
            current = parent
        return result

    def scientific_name(self, taxid: int) -> str | None:
        self._load()
        return self._name.get(taxid)
