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

# NCBI renamed the top rank in 2025: Bacteria/Archaea/Eukaryota are now rank
# "domain" (was "superkingdom") and Viruses is rank "acellular root". The
# taxdump under tools/taxdump (2026-08) uses the new names, so without this
# alias no taxid-resolved lineage carried a superkingdom at all and
# routing.lineage_to_route could never return bacteria_pathogen for a
# BLAST-DB or MIDORI2 record. Both new ranks are stored under the old key
# that routing.py and every caller already read.
_RANK_ALIASES = {"domain": "superkingdom", "acellular root": "superkingdom"}


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
            rank = _RANK_ALIASES.get(rank, rank)
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

    def ancestors(self, taxid: int) -> list[int]:
        """[taxid, parent, ..., root] — empty if the taxid is unknown."""
        self._load()
        if taxid not in self._parent:
            return []
        chain = [taxid]
        seen = {taxid}
        current = taxid
        while True:
            parent = self._parent.get(current)
            if parent is None or parent == current or parent in seen:
                break
            chain.append(parent)
            seen.add(parent)
            current = parent
        return chain

    def lowest_common_ancestor(self, a: int, b: int) -> int | None:
        if a == b:
            return a
        chain_a = self.ancestors(a)
        if not chain_a:
            return None
        set_a = set(chain_a)
        for node in self.ancestors(b):
            if node in set_a:
                return node
        return None

    def taxids_for_name(self, name: str) -> list[int]:
        """Every taxid whose scientific name is exactly `name` (homonyms such
        as the bacterium and the stick-insect genus Bacillus give several)."""
        self._load()
        if not hasattr(self, "_by_name"):
            by_name: dict[str, list[int]] = {}
            for taxid, sci in self._name.items():
                by_name.setdefault(sci, []).append(taxid)
            self._by_name = by_name
        return list(self._by_name.get(name, ()))
