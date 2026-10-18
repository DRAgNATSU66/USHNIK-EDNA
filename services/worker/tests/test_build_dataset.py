"""build_dataset (sprint Day 7, t-1020-1): BOLD discovery and the missing-BOLD
path, per-route caps, near-duplicate grouping and group-aware splits, and the
leakage check. Fixtures only; no raw data needed."""
from __future__ import annotations

import csv
import json
import os
import random
from collections import Counter
from pathlib import Path

import pytest

from training import build_dataset as bd
from training import check_leakage, near_dup

_RNG = random.Random(7)


def rand_seq(n: int, rng: random.Random = _RNG) -> str:
    return "".join(rng.choice("ACGT") for _ in range(n))


def mutate(seq: str, n_snps: int, rng: random.Random) -> str:
    s = list(seq)
    for i in rng.sample(range(len(s)), n_snps):
        s[i] = {"A": "C", "C": "G", "G": "T", "T": "A"}[s[i]]
    return "".join(s)


# ---------------------------------------------------------------------------
# BOLD discovery
# ---------------------------------------------------------------------------

class TestFindBold:
    def test_missing_dir(self, tmp_path: Path):
        assert bd.find_bold_parquet(tmp_path / "bold") is None

    def test_empty_dir(self, tmp_path: Path):
        (tmp_path / "bold").mkdir()
        assert bd.find_bold_parquet(tmp_path / "bold") is None

    def test_ignores_other_files(self, tmp_path: Path):
        d = tmp_path / "bold"
        d.mkdir()
        (d / "notes.parquet").write_bytes(b"x")
        (d / "BOLD_Public.31-Jul-2026.tsv").write_bytes(b"x")
        assert bd.find_bold_parquet(d) is None

    def test_picks_newest_by_mtime_not_name(self, tmp_path: Path):
        d = tmp_path / "bold"
        d.mkdir()
        old = d / "BOLD_Public.31-Jul-2026.parquet"
        new = d / "BOLD_Public.02-Oct-2026.parquet"   # sorts before "31-Jul" by name
        old.write_bytes(b"x")
        new.write_bytes(b"x")
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (2_000_000, 2_000_000))
        assert bd.find_bold_parquet(d) == new


def _unite_fixture(raw: Path, n: int = 40) -> None:
    d = raw / "unite"
    d.mkdir(parents=True)
    rng = random.Random(3)
    with open(d / "sh_general_release_dynamic_test.fasta", "w") as fh:
        for i in range(n):
            name = f"Fungus_species{i}" if i % 2 else f"uncultured_Fungus{i}"
            fh.write(f">{name}|ACC{i}|SH{i}|reps|k__Fungi;p__Ascomycota;g__G{i};s__{name}\n{rand_seq(300, rng)}\n")


def test_build_runs_without_bold_and_logs_skip(tmp_path: Path, capsys):
    root = tmp_path / "data"
    raw = root / "raw"
    (raw / "bold").mkdir(parents=True)     # present but empty, as on the Linux box today
    (raw / "midori2").mkdir()
    (raw / "silva").mkdir()
    _unite_fixture(raw)
    bd.main(["--data-dir", str(root), "--only-routes", "misc_unknown", "--skip-blastdb",
             "--skip-supplementary"])
    out = capsys.readouterr().out
    assert "WARNING: skipping BOLD" in out
    report = json.loads((root / "processed" / "build_report.json").read_text())
    assert "bold" in report["skipped"]
    assert report["skipped"]["ncbi_blastdb"] == "--skip-blastdb"
    assert any(s["source"].startswith("unite:") and s["scanned"] == 40 for s in report["sources"])
    total = 0
    for split in ("train", "dev", "test"):
        with open(root / "processed" / "misc_unknown" / f"{split}.csv") as fh:
            total += sum(1 for _ in csv.DictReader(fh))
    assert total == report["routes"]["misc_unknown"]["total"] == 40


# ---------------------------------------------------------------------------
# caps
# ---------------------------------------------------------------------------

def test_route_caps_override_global_cap():
    c = bd.Collector(cap=2, route_caps={"bacteria_pathogen": 5})
    for i in range(10):
        c.add("bacteria_pathogen", "known_species", f"B{i}")
        c.add("fish", "known_species", f"F{i}")
    assert len(c.buckets[("bacteria_pathogen", "known_species")]) == 5
    assert len(c.buckets[("fish", "known_species")]) == 2
    assert c.seen_counts[("fish", "known_species")] == 10


def test_parse_route_caps():
    assert bd.parse_route_caps("bacteria_pathogen=20000, fish=10") == {"bacteria_pathogen": 20000, "fish": 10}
    assert bd.parse_route_caps(None) == {}
    with pytest.raises(SystemExit):
        bd.parse_route_caps("not_a_route=5")
    with pytest.raises(SystemExit):
        bd.parse_route_caps("fish=many")


# ---------------------------------------------------------------------------
# near-duplicate grouping
# ---------------------------------------------------------------------------

class TestNearDup:
    def test_kmer_codes_skip_n_windows(self):
        assert near_dup.kmer_codes("ACGT" * 3).size == 0            # shorter than k
        assert near_dup.kmer_codes("N" * 40).size == 0
        s = "ACGTACGTACGTACGTA"                                       # 17 bp -> 2 windows
        assert near_dup.kmer_codes(s).size == 2
        assert near_dup.kmer_codes(s[:8] + "N" + s[9:]).size == 0     # N in every window

    def test_one_snp_groups_unrelated_does_not(self):
        rng = random.Random(1)
        base = rand_seq(500, rng)
        seqs = [base, mutate(base, 1, rng), rand_seq(500, rng), "ACGT", "N" * 200]
        g = near_dup.near_duplicate_groups(seqs)
        assert g[0] == g[1]
        assert len({g[0], g[2], g[3], g[4]}) == 4

    def test_heavily_mutated_is_not_near_dup(self):
        rng = random.Random(2)
        base = rand_seq(500, rng)
        g = near_dup.near_duplicate_groups([base, mutate(base, 60, rng)])   # ~12% divergent
        assert g[0] != g[1]

    def test_chains_are_transitive(self):
        rng = random.Random(4)
        a = rand_seq(600, rng)
        b = mutate(a, 2, rng)
        c = mutate(b, 2, rng)
        g = near_dup.near_duplicate_groups([a, rand_seq(600, rng), c, b])
        assert g[0] == g[2] == g[3]

    def test_cross_set(self):
        rng = random.Random(5)
        ref = [rand_seq(400, rng) for _ in range(5)]
        q = [mutate(ref[2], 1, rng), rand_seq(400, rng)]
        assert near_dup.cross_set_near_duplicates(q, ref).tolist() == [True, False]
        assert near_dup.cross_set_near_duplicates([], ref).tolist() == []


# ---------------------------------------------------------------------------
# group-aware splits
# ---------------------------------------------------------------------------

def test_assign_groups_keeps_groups_together_and_stratifies():
    rng = random.Random(9)
    labels, groups = [], []
    gid = 0
    for lab, n in (("known_species", 3000), ("possible_novelty", 300)):
        made = 0
        while made < n:
            size = rng.choice([1, 1, 1, 1, 2, 3, 8])
            size = min(size, n - made)
            labels += [lab] * size
            groups += [gid] * size
            gid += 1
            made += size
    out = bd.assign_groups_to_splits(labels, groups, rng=random.Random(0))
    split_of_group = {}
    for g, s in zip(groups, out):
        assert split_of_group.setdefault(g, s) == s
    by = Counter(zip(out, labels))
    for lab, n in (("known_species", 3000), ("possible_novelty", 300)):
        for s, frac in (("dev", 0.1), ("test", 0.1), ("train", 0.8)):
            assert abs(by[(s, lab)] - frac * n) <= max(10, 0.03 * n), (s, lab, by[(s, lab)])


def _read_split(route_dir: Path, split: str) -> list[tuple[str, str]]:
    with open(route_dir / f"{split}.csv") as fh:
        return [(r["sequence"], r["label"]) for r in csv.DictReader(fh)]


def test_write_splits_group_mode_no_exact_or_near_dup_leak(tmp_path: Path):
    random.seed(11)
    rng = random.Random(11)
    c = bd.Collector(cap=10_000)
    for _ in range(150):
        base = rand_seq(450, rng)
        c.add("fish", "known_species", base)
        c.add("fish", "known_species", base)                 # exact duplicate
        for _ in range(rng.choice([0, 0, 1, 3])):
            c.add("fish", "known_species", mutate(base, 1, rng))   # near duplicates
    for _ in range(60):
        c.add("fish", "possible_novelty", rand_seq(450, rng))
    stats = bd.write_splits(c, tmp_path, target_routes=("fish",))
    route = tmp_path / "fish"
    splits = {s: _read_split(route, s) for s in ("train", "dev", "test")}
    seqs = {s: [q for q, _ in rows] for s, rows in splits.items()}
    for a, b in (("train", "dev"), ("train", "test"), ("dev", "test")):
        assert not set(seqs[a]) & set(seqs[b])
        assert not near_dup.cross_set_near_duplicates(seqs[b], seqs[a]).any()
    assert all(len(v) == len(set(v)) for v in seqs.values())
    assert stats["fish"]["split_mode"] == "group"
    assert stats["fish"]["near_dup"]["rows_in_multi_member_groups"] > 0
    assert sum(len(v) for v in seqs.values()) == stats["fish"]["total"]
    report = check_leakage.check(tmp_path)
    assert report["exact_cross_split_total"] == 0
    nd = report["routes"]["fish"]["near_duplicate"]
    assert nd["test_rows_with_near_dup_in_train_or_dev"] == 0
    assert nd["dev_rows_with_near_dup_in_train"] == 0


def test_write_splits_random_mode_unchanged_sizes(tmp_path: Path):
    random.seed(1)
    c = bd.Collector(cap=10_000)
    for i in range(100):
        c.add("fish", "known_species", rand_seq(200))
    stats = bd.write_splits(c, tmp_path, target_routes=("fish",), split_mode="random")
    assert {s: sum(v.values()) for s, v in stats["fish"]["by_split"].items()} == {"test": 10, "dev": 10, "train": 80}
    assert "near_dup" not in stats["fish"]


# ---------------------------------------------------------------------------
# leakage check
# ---------------------------------------------------------------------------

def _write(route_dir: Path, name: str, rows: list[tuple[str, str]]) -> None:
    route_dir.mkdir(parents=True, exist_ok=True)
    with open(route_dir / name, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sequence", "label"])
        w.writerows(rows)


def test_check_leakage_flags_overlap_and_ignores_leaky_archive(tmp_path: Path):
    rng = random.Random(21)
    a, b, c, d = (rand_seq(300, rng) for _ in range(4))
    r = tmp_path / "plant"
    _write(r, "train.csv", [(a, "known_species"), (b, "known_species")])
    _write(r, "dev.csv", [(c, "known_species")])
    _write(r, "test.csv", [(a, "known_species"), (mutate(c, 1, rng), "known_species")])
    _write(r, "test.leaky.csv", [(b, "known_species")])
    _write(tmp_path / "fish", "train.csv", [(d, "known_species")])
    _write(tmp_path / "fish", "dev.csv", [])
    _write(tmp_path / "fish", "test.csv", [(b, "known_species")])
    report = check_leakage.check(tmp_path)
    assert report["ignored_leaky_archives"] == ["plant/test.leaky.csv"]
    assert report["routes"]["plant"]["exact_cross_split_unique_sequences"] == {"train_dev": 0, "train_test": 1, "dev_test": 0}
    assert report["exact_cross_split_total"] == 1
    nd = report["routes"]["plant"]["near_duplicate"]
    assert nd["test_rows_with_near_dup_in_train"] == 1      # the exact copy of a
    assert nd["test_rows_with_near_dup_in_dev"] == 1        # the 1-SNP copy of c
    assert report["cross_route_unique_sequences"] == 1      # b in plant and fish
    assert check_leakage.main(["--processed", str(tmp_path), "--no-near-dup"]) == 1
