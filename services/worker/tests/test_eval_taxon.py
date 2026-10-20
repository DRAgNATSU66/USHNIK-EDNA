"""Metric code of training/eval_taxon.py (t-1023-3): rank-aware precision/
recall, predicted lineage with and without the genus cap, truth basis,
wrong-route vs wrong-taxon split, same-record leakage, relabel verdicts."""
from __future__ import annotations

from training import eval_taxon as et


def _row(rid="fish:test:1", true_route="fish", label="known_species", final_route="fish", taxon=None, rank=None,
         lineage=None, status="assigned", capped=False, result_class="known_species", rule="head_class",
         extra_evidence=(), plan_routes=None, hits=None):
    payload = {"status": status, "taxon": (lineage or {}).get(rank) if rank else None, "rank": rank,
               "identity": 99.5, "lineage": lineage or {}, "hits": [], "reference_db_version": "v2"}
    combine = [{"step": "taxon", "rule": "genus_cap"}] if capped else []
    return {
        "id": rid, "true_route": true_route, "label": label,
        "decision": {"final_route": final_route, "predicted_taxon": taxon, "taxon_rank": rank,
                     "result_class": result_class, "rule": rule},
        "decision_trace": {"plan": {"routes": plan_routes or [final_route]},
                           "evidence": [{"provider": "reference_lookup", "route": final_route, "status": "ok",
                                         "payload": payload}, *extra_evidence],
                           "combine": combine},
        "ref_hits": {final_route: hits or []},
    }


PERCA = {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "family": "Percidae", "genus": "Perca",
         "species": "Perca fluviatilis"}


def test_norm_name_matches_reference_header_sanitising():
    assert et.norm_name("Homo sapiens") == et.norm_name("Homo_sapiens") == "homo sapiens"
    assert et.norm_name("Escherichia coli O157:H7") == "escherichia coli o157 h7"
    assert et.norm_name("") is None and et.norm_name(None) is None


def test_acc_base_strips_versions_and_silva_coordinates():
    assert et.acc_base("MG559732.1") == "MG559732"
    assert et.acc_base("AB000106.1.1343") == "AB000106"
    assert et.acc_base("gb|KX123456.2|") == "KX123456"
    assert et.acc_base("NA") is None and et.acc_base(None) is None


def test_predicted_lineage_species_call():
    eff, unc = et.predicted_lineage(_row(taxon="Perca fluviatilis", rank="species", lineage=PERCA))
    assert eff["species"] == "perca fluviatilis" and eff == unc


def test_predicted_lineage_genus_cap_keeps_uncapped_species():
    row = _row(taxon="Perca", rank="genus", lineage=PERCA, capped=True)
    eff, unc = et.predicted_lineage(row)
    assert "species" not in eff and eff["genus"] == "perca"
    assert unc["species"] == "perca fluviatilis"
    assert et.genus_capped(row)


def test_predicted_lineage_empty_without_assignment():
    assert et.predicted_lineage(_row(status="no_hit")) == ({}, {})
    assert et.predicted_lineage(_row(taxon=None, rank=None, lineage=PERCA)) == ({}, {})


def test_rank_metrics_is_rank_aware():
    truth = {"family": "percidae", "genus": "perca", "species": "perca fluviatilis"}
    pairs = [
        ({"family": "percidae", "genus": "perca", "species": "perca fluviatilis"}, truth),   # all right
        ({"family": "percidae", "genus": "perca"}, truth),                                   # genus call, right
        ({"family": "percidae", "genus": "sander", "species": "sander lucioperca"}, truth),  # wrong genus
        ({}, truth),                                                                          # no call
        ({"family": "percidae", "genus": "perca", "species": "perca flavescens"}, {"family": "percidae", "genus": "perca"}),
    ]
    m = et.rank_metrics(pairs)
    assert m["species"] == {"gradable": 4, "called": 2, "correct": 1, "wrong": 1, "precision_pct": 50.0,
                            "recall_pct": 25.0, "called_without_truth_at_rank": 1}
    assert m["genus"]["called"] == 4 and m["genus"]["correct"] == 3 and m["genus"]["gradable"] == 5
    assert m["genus"]["precision_pct"] == 75.0 and m["genus"]["recall_pct"] == 60.0
    assert m["family"]["precision_pct"] == 100.0


def test_rank_metrics_empty():
    m = et.rank_metrics([])
    assert m["species"]["precision_pct"] is None and m["species"]["recall_pct"] is None


def test_lca_matches_reference_builder_semantics():
    a = {"superkingdom": "eukaryota", "genus": "perca", "species": "perca fluviatilis"}
    b = {"superkingdom": "eukaryota", "family": "percidae", "genus": "perca", "species": "perca flavescens"}
    assert et.lca([a, b]) == {"superkingdom": "eukaryota", "family": "percidae", "genus": "perca"}
    assert et.lca([]) == {}


def test_grading_truth_prefers_qna020_tracer():
    t = {"reference_truth": {"lineage": {"genus": "Perca"}}, "lca_named": {"genus": "x"}, "lca_any": {"genus": "y"}}
    assert et.grading_truth(t) == ({"genus": "perca"}, "reference_named")
    assert et.grading_truth({"reference_truth": None, "lca_named": {"genus": "x"}})[1] == "named_copy_outside_reference_plan"
    assert et.grading_truth({"reference_truth": None, "lca_named": None, "lca_any": {"genus": "y"}})[1] == "unresolved_name_only"
    assert et.grading_truth(None) == (None, "untraced")


def test_genus_key_and_names_in():
    assert et.genus_key("Clostridium sensu stricto 1") == "clostridium"
    assert et.genus_key("Candidatus Pelagibacter") == "pelagibacter"
    assert et.genus_key("uncultured") is None
    names = et.names_in([{"organism": "uncultured Bacteroides sp.", "lineage": {"superkingdom": "Bacteria"}}])
    assert names == {"genus": {"bacteroides"}, "species": set(), "family": set()}
    names = et.names_in([{"organism": "uncultured bacterium", "lineage": {"superkingdom": "Bacteria"},
                          "path_lineage": {"genus": "Clostridium sensu stricto 1"}}])
    assert names["genus"] == {"clostridium"}
    names = et.names_in([{"organism": "Salmo trutta environmental sample", "lineage": {}}])
    assert names == {"genus": {"salmo"}, "species": {"salmo trutta"}, "family": set()}
    assert et.names_in([{"organism": "uncultured bacterium", "lineage": {}}]) == {"genus": set(), "species": set(),
                                                                                "family": set()}


def test_names_in_family_and_higher_words_are_not_genera():
    # 'Gobiidae environmental sample' names a family; 'Perciformes sp.' an order
    names = et.names_in([{"organism": "Gobiidae environmental sample", "lineage": {}}])
    assert names == {"genus": set(), "species": set(), "family": {"gobiidae"}}
    assert et.names_in([{"organism": "Perciformes sp.", "lineage": {}}])["genus"] == set()
    # a word the copy's own lineage holds above genus is not read as a genus
    names = et.names_in([{"organism": "Chordata environmental sample", "lineage": {"phylum": "Chordata"}}])
    assert names["genus"] == set()
    # family from the lineage, skipping unresolved placeholders
    names = et.names_in([{"organism": "", "lineage": {"family": "Salmonidae"}},
                         {"organism": "", "lineage": {"family": "uncultured"}}])
    assert names["family"] == {"salmonidae"}


def test_classify_relabel_verdicts():
    hit = {"genus": "Bacteroides", "species": "Bacteroides fragilis"}
    cats = {"uncultured"}
    v, _ = et.classify_relabel({"genus": {"bacteroides"}, "species": set()}, hit, cats, "possible_not_confirmable")
    assert v == "label_noise"
    v, _ = et.classify_relabel({"genus": {"prevotella"}, "species": set()}, hit, cats, "possible_not_confirmable")
    assert v == "real_disagreement"
    v, why = et.classify_relabel({"genus": {"bacteroides"}, "species": {"bacteroides ovatus"}}, hit, cats, "no")
    assert v == "real_disagreement" and "species" in why
    v, why = et.classify_relabel({"genus": set(), "species": set()}, hit, cats, "possible_not_confirmable")
    assert v == "undetermined" and "uncultured" in why
    v, _ = et.classify_relabel({"genus": set(), "species": set()}, hit, cats, "same_accession")
    assert v == "label_noise"
    v, _ = et.classify_relabel({"genus": {"bacteroides"}, "species": set()}, {"family": "Bacteroidaceae"}, cats, "no")
    assert v == "undetermined"
    fam = {"genus": set(), "species": set(), "family": {"bacteroidaceae"}}
    v, why = et.classify_relabel(fam, dict(hit, family="Bacteroidaceae"), cats, "no")
    assert v == "label_noise" and "family" in why
    v, why = et.classify_relabel(fam, dict(hit, family="Prevotellaceae"), cats, "no")
    assert v == "real_disagreement" and "family" in why
    v, why = et.classify_relabel({"genus": set(), "species": set(), "family": set()}, {"family": "Gobiidae"},
                                 {"environmental sample"}, "no")
    assert v == "undetermined" and "environmental sample" in why
    v, why = et.classify_relabel({"genus": {"bacteroides"}, "species": {"bacteroides fragilis"}}, hit, cats, "no",
                                 {"genus": {"bacteroides"}, "species": {"bacteroides fragilis"}})
    assert v == "label_noise" and "named copy" in why


def test_same_record_hits_uses_merged_copy_accessions_and_identity_floor():
    hits = [{"target_id": "BAC1", "accession": "XX000001.1", "identity": 99.6},
            {"target_id": "BAC2", "accession": "AB000106.1.1343", "identity": 99.2},
            {"target_id": "BAC3", "accession": "MG000001.1", "identity": 98.0}]
    ref_accs = {"BAC1": {"XX000001", "KY111111"}, "BAC3": {"MG000001"}}
    out = et.same_record_hits(hits, {"KY111111", "AB000106", "MG000001"}, ref_accs)
    assert [h["target_id"] for h in out] == ["BAC1", "BAC2"]   # BAC3 is below 99 %
    assert out[0]["shared_accessions"] == ["KY111111"]


def test_summarise_splits_wrong_route_from_wrong_taxon():
    truth = {
        "fish:test:1": {"reference_truth": {"lineage": PERCA}},
        "fish:test:2": {"reference_truth": {"lineage": PERCA}},
        "fish:test:3": {"reference_truth": {"lineage": PERCA}},
    }
    sander = {"family": "Percidae", "genus": "Sander", "species": "Sander lucioperca"}
    true_route_ev = {"provider": "reference_lookup", "route": "fish", "status": "ok",
                     "payload": {"status": "assigned", "lineage": PERCA}}
    rows = [
        _row("fish:test:1", taxon="Perca fluviatilis", rank="species", lineage=PERCA),
        _row("fish:test:2", taxon="Sander lucioperca", rank="species", lineage=sander),
        _row("fish:test:3", final_route="animal_general", taxon="Sander lucioperca", rank="species", lineage=sander,
             plan_routes=["animal_general", "fish"], extra_evidence=[true_route_ev]),
    ]
    s = et.summarise_taxon(rows, truth, {"fish:test:3": {"leaky": True}}, {"plant"})
    e = s["errors_by_rank"]["species"]
    assert e["wrong_call_right_route"] == 1 and e["wrong_call_wrong_route"] == 1
    assert e["wrong_route_true_route_planned"] == 1 and e["wrong_route_true_route_reference_correct"] == 1
    assert s["rank_metrics_all_traced"]["species"]["precision_pct"] == round(100 / 3, 1)
    assert s["leaky_rows"] == 1
    assert s["rank_metrics_all_traced_leaky_excluded"]["species"]["called"] == 2
    assert s["assigned_share_by_rank_pct"] == {"species": 100.0}


def test_summarise_genus_cap_effect():
    plant = {"kingdom": "Viridiplantae", "family": "Rosaceae", "genus": "Rosa", "species": "Rosa canina"}
    truth = {"plant:test:1": {"reference_truth": {"lineage": plant}},
             "plant:test:2": {"reference_truth": {"lineage": dict(plant, species="Rosa arvensis")}}}
    rows = [_row("plant:test:1", true_route="plant", final_route="plant", taxon="Rosa", rank="genus",
                 lineage=plant, capped=True),
            _row("plant:test:2", true_route="plant", final_route="plant", taxon="Rosa", rank="genus",
                 lineage=plant, capped=True)]
    cap = et.summarise_taxon(rows, truth, None, {"plant"})["genus_cap"]
    assert cap["rows_capped"] == 2 and cap["dropped_species_correct"] == 1
    assert cap["species_with_cap"]["called"] == 0
    assert cap["species_without_cap"]["called"] == 2 and cap["species_without_cap"]["precision_pct"] == 50.0


def test_audit_relabels_only_novelty_rows_relabelled():
    lin = {"genus": "Salmo", "species": "Salmo trutta"}
    rows = [
        _row("fish:test:1", label="possible_novelty", taxon="Salmo trutta", rank="species", lineage=lin,
             result_class="known_species", rule="novelty_suppressed_by_reference"),
        _row("fish:test:2", label="possible_novelty", result_class="possible_novelty"),
        _row("fish:test:3", label="known_species", taxon="Salmo trutta", rank="species", lineage=lin),
    ]
    truth = {"fish:test:1": {"copies": [{"organism": "uncultured Salmo sp.", "src": "midori2", "acc": "AB1.1",
                                         "lineage": {"genus": "Salmo"}, "usable_name": False}],
                             "accessions": ["AB1"], "n_copies": 1}}
    audit = et.audit_relabels(rows, truth, None)
    assert [a["id"] for a in audit] == ["fish:test:1"]
    assert audit[0]["verdict"] == "label_noise" and audit[0]["same_specimen"] == "possible_not_confirmable"
    assert audit[0]["source"]["name_categories"] == ["uncultured"]
    counts = et.relabel_counts(audit)
    assert counts["all"]["verdict"] == {"label_noise": 1}
    assert counts["by_rule"]["novelty_suppressed_by_reference"]["n"] == 1
