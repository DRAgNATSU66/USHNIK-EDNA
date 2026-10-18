# Q5 checkpoint: a source for every partner panel

Roadmap task **t-1025-4** (`docs/ROADMAP_REAL_DATA.md` Part B, Day 12, 25 Oct). Decision text:
`docs/decisions.md` 2026-10-14 **Q5**: try real public data first, and remove a panel for v1 only if
that fails. Part A rows M1, M2, M3 and B16 list the panels. Checked on **2026-10-18**. All the
queries below ran that day from the dev box, with no credentials.

**Done when:** each external-data panel has a source or is marked for removal. All 29 `MockTag`
panels on the three partner pages are covered below.

## Decision key

| Code | Meaning |
|------|---------|
| **a** | Computed from our own data only (uploads, results, reviews, field log). No external call |
| **a+b** | Our own data, plus a public source as a lookup or fallback. The panel shows which one supplied each value |
| **b** | Comes from a public source, keyed by the upload's `latitude`, `longitude` and `collected_at` |
| **c** | No viable v1 source. The panel is **removed** for v1 and listed under "v2: external data" below |

**Counts:** a = 6 · a+b = 7 · b = 4 · c = 12, for 29 panels in total. 17 panels stay (11 of them use
a public source), and 12 are removed. A further 6 kept panels lose some invented sub-content. See
"Partial removals" below.

**Panel count against the roadmap:** Academia has **12** panel `MockTag`s, not the 13 in Part A
M3. M3 lists wind and current as one item. Its 13th `MockTag`, at `Academia.jsx:517`, is the legend
inside the warning banner, not a panel. Industrial has 11 and Legislative has 6, which matches the
roadmap.

## Panel table

Line numbers refer to `web_frontend/src/pages/partner/*.jsx` on `LATEST_USHNIK` @ `cab84b3`. The
"Verified by" column points to rows **V1–V12** in the verification log below.

### Industrial (`partner/Industrial.jsx`, M1)

| # | Panel (line) | Decision | Source / fields | Verified by | Notes |
|---|--------------|----------|-----------------|-------------|-------|
| I1 | ACTIVE INCIDENTS + "source detections" modal (`:332`, `INCIDENTS` `:14`) | **a+b** | **a:** `taxonomic_assignments[].predicted_taxon`, `confidence_tier`, `contamination_flagged`. Also the upload's `original_filename`, `checksum_sha256`, `latitude`/`longitude` and `analysis_id`. **b:** WoRMS REST. `AphiaIDByName` gives the AphiaID. `AphiaAttributesByAphiaID` gives the IUCN Red List Category and year. `AphiaDistributionsByAphiaID` gives `establishmentMeans` (Alien/Native) and `invasiveness` per locality | V9, V10 | An incident is one of two things. (1) A green-tier taxon that WoRMS lists as IUCN CR, EN or VU. (2) A taxon listed as Alien or Invasive at a WoRMS locality in the sample's region. Remove the "within permit zone / active dredging" wording, because we hold no permit-zone data. Depends on B4 (species-level `predicted_taxon`). Share the backend logic with L2 |
| I2 | AVERAGE IMPACT SCORE (`:342`) | **c** | None. "Impact score" has no definition, and the app has no "project" entity | — | Invented composite metric |
| I3 | PENDING AUDITS (`:347`) | **c** | None. Audit schedules are partner workflow data, and no store or feed exists | — | Product feature, not external data |
| I4 | ENVIRONMENTAL RISK RADAR (`:359`, `RADAR_VALS` `:45`) | **c** | None for regulatory fines, permit delays or supply disruption. The other two axes (biodiversity loss, biofouling) have no defined formula | — | Remove the whole radar |
| I5 | BIOLOGICAL IMPACT METRICS (`:370`) | **a+b** (partial) | Keep **"Alien / invasive DNA share"**: the fraction of classified reads whose taxon is Alien or Invasive in WoRMS distributions near the sample (**b**), using `taxonomic_assignments` (**a**) | V10 | Remove **Mitigation success 62%** and **Indicator species stability 24%**. Both need a before/after restoration baseline design that we do not have. Depends on B4 |
| I6 | AUDIT TRAIL + "Schedule Audit" (`:399`, `scheduleAudit` `:308`) | **c** | None | — | Also remove the fake-success `setTimeout` button |
| I7 | REMEDIATION PLAN (`:406`) | **c** | None | — | Partner workflow data |
| I8 | DOCUMENT HUB (`:415`) | **a** | Field-log attachments (B10): `GET /field-log/attachments?analysis_id=…` returns `original_filename`, `content_type`, `size_bytes`, `checksum_sha256`, `uploader_name` and `created_at`. Downloads go through `GET /field-log/attachments/{id}/download` | n/a (internal) | Replace the three hard-coded PDF names |
| I9 | QUICK NOTES & TASKS (`:426`) | **a** (notes only) | `GET /field-log/entries?analysis_id=…&kind=note`: `body`, `author_name`, `created_at` | n/a (internal) | The task checkbox has no model behind it, so drop it or move it to v2. Notes are real today |
| I10 | PREDICTIVE THRESHOLD · BIOFOULING (`:466`) | **c** | None. No public "regulatory biofouling limit" exists to forecast against, and "~45 days ±12" has no model behind it | — | — |
| I11 | REMEDIATION ROI · COST DELTA (`:473`) | **c** | None. No contractor rate card or fine schedule is available | — | — |

### Legislative (`partner/Legislative.jsx`, M2)

| # | Panel (line) | Decision | Source / fields | Verified by | Notes |
|---|--------------|----------|-----------------|-------------|-------|
| L1 | BIODIVERSITY HOTSPOT MAP · BAY OF BENGAL (`:467`, `HOTSPOTS` `:66`) | **a+b** | **a:** one marker per upload with `latitude`/`longitude`. Marker style comes from that analysis's `biodiversity.predicted_taxon_richness`, `novelty_fraction` and I1-style flags. **b:** surface current vectors `uo`/`vo` from Copernicus Marine `cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m_202406` replace the illustrative flow polylines | V4 | Remove the hard-coded hotspots and the "winter monsoon" polylines. If the current layer slips, drop the lines and keep the markers |
| L2 | ACTIVE ALERTS + alert modal (`:480`, `ALERTS` `:22`) | **a+b** | Same rules and sources as I1 (WoRMS IUCN category + Alien/Invasive). Severity: IUCN CR/EN = Critical, VU = High, locality Invasive = High, Alien with uncertain invasiveness = Medium | V9, V10 | Remove the "presence within the last ~7–14 days" claim: eDNA persistence varies and we have no source for that window. Templated suggested actions per alert type may stay |
| L3 | INDICATOR SPECIES TREND (`:508`) | **a** | Detection frequency of a **partner-supplied indicator taxon list** across that partner's uploads, ordered by `collected_at`, using `taxonomic_assignments.predicted_taxon` | n/a (internal) | Needs at least 3 dated uploads; with fewer, show "insufficient samples". Needs the indicator list (user action). Depends on B4 |
| L4 | HABITAT-ASSOCIATED TAXA DECLINE (`:515`) | **c** | No verified source maps taxa to the vulnerable habitats this panel names (mangrove, seagrass) | — | v2: build it from WoRMS functional-group or habitat traits, or merge into L3 using a habitat-tagged list |
| L5 | ECONOMIC RISK & COMPLIANCE EXPOSURE (`:524`, `ECON` `:57`) | **c** | None (₹ exposure figures, fine schedule, rate card) | — | Also remove the `runFeasibility()` fake run (`:444`) |
| L6 | CRYPTOGRAPHIC CHAIN OF CUSTODY (`:588`) | **a** | Upload doc: `original_filename`, `checksum_sha256`, `user_id` resolved to a display name, `created_at`, `storage_uri`. The worker re-verifies the hash on read (`services/worker/app/storage.py:333`) | n/a (internal) | Replace the hard-coded `9f3a…c41e77b2` and "M. Fernandes" |

### Academia (`partner/Academia.jsx`, M3)

| # | Panel (line) | Decision | Source / fields | Verified by | Notes |
|---|--------------|----------|-----------------|-------------|-------|
| A1 | DISSOLVED OXYGEN (`:565`) | **a+b** | **a:** `dissolved_oxygen_mg_l`, when the uploader entered it. **b** (fallback): Copernicus Marine `GLOBAL_ANALYSISFORECAST_BGC_001_028`, dataset `cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m_202311`, var `o2` (mmol m⁻³). Multiply by 0.031998 to get mg/L | V5 | Label each value "measured" or "modelled (CMEMS)". Remove the hard-coded 78% / 6.4 mg/L |
| A2 | TOXICITY INDEX (`:571`) | **c** | No public toxicity product exists for an arbitrary point, and we have no lab-panel integration | — | — |
| A3 | TEMPERATURE · AT DEPTH (`:581`) | **b** | Copernicus Marine `GLOBAL_ANALYSISFORECAST_PHY_001_024`, `cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m_202406`, var `thetao` at 50 depth levels. Use the surface level, a mid level, and the level nearest `depth_meters`. Show the uploader's `temperature_celsius` beside it when present | V2, V3 | Remove the hard-coded 4.2 °C and the 1840 m default (`:604`). Cross-check: CMEMS surface 30.28 °C against OISST 30.25 °C at the same point |
| A4 | pH LEVEL (`:609`) | **a+b** | **a:** `ph`. **b** (fallback): `GLOBAL_ANALYSISFORECAST_BGC_001_028`, `cmems_mod_glo_bgc-car_anfc_0.25deg_P1D-m_202311`, var `ph` | V6 | Remove the hard-coded 7.9 |
| A5 | SALINITY (when not recorded) (`:614`) | **a+b** | **a:** `salinity_ppt` (already real). **b** (fallback): `cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m_202406`, var `so` (1e-3, i.e. PSU) | V7 | This removes the "NOT RECORDED" `MockTag` for any upload with coordinates and a date |
| A6 | WIND SPEED BY DAY (`:626`) | **b** | ECMWF ERA5 through Open-Meteo `GET https://archive-api.open-meteo.com/v1/era5`, vars `wind_speed_10m` and `wind_direction_10m` (hourly), aggregated to daily over the 7 days ending at `collected_at` | V8 | Open-Meteo's free API is **non-commercial only** (10k calls/day). For commercial deployment, use ERA5 from the Copernicus Climate Data Store (free account), or a paid Open-Meteo key. Remove the hard-coded `vals` |
| A7 | CURRENT SPEED BY DAY (`:633`) | **b** | Copernicus Marine `cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m_202406`, vars `uo`/`vo`. Speed = √(uo²+vo²); the direction is the bearing the flow is heading toward | V4, V11 | Alternative: Open-Meteo Marine `ocean_current_velocity` (same non-commercial terms). It gave 1.0–1.6 km/h on 2026-10-01, which agrees with the CMEMS value |
| A8 | MULTI-OMICS & ENVIRONMENTAL OVERLAY (`:642`) | **b** (re-scoped) | Environmental lines: CMEMS daily `thetao`, `so` and `ph` for ±15 days around `collected_at` (V2, V6, V7). DNA line: our read counts per upload at that site (**a**). "Multi-omics" layer: MGnify API public samples within a bounding box, with their SSU taxonomy, as nearby context | V2, V6, V7, V12 | Rename it to "Environmental context & nearby public metagenomes". The single-point-per-upload limitation the panel text describes goes away, because CMEMS supplies the series. Remove `WavesSVG` sample data |
| A9 | SONIC ACTIVITY · AMBIENT NOISE (`:657`) | **c** | No public ambient-noise feed exists for an arbitrary lat/long, and we have no hydrophone. Not queried: we know of no gridded observational product | — | — |
| A10 | ACTIVITY RHYTHMS · VERTICAL MIGRATION (`:670`) | **c** | Needs acoustic backscatter or sub-daily sampling. Each upload has one `collected_at` | — | — |
| A11 | SPECIES CO-OCCURRENCE NETWORK (`:681`) | **a** | Q6: server-side top-50 taxa by count of `taxonomic_assignments.predicted_taxon` per analysis, across the partner's analyses. Spearman ρ between taxa across samples, with a minimum co-occurrence threshold | n/a (internal) | Replace the 140 random `rnd()` nodes. Needs at least 5 analyses; with fewer, show "insufficient samples". Depends on B4 |
| A12 | FAIR ZIP BUNDLE (`:718`) | **a** | The original upload bytes (through `storage_uri`), `GET /reports/{id}/export/json` and `/export/csv`, and the upload metadata + `context` block. All of this is internal | n/a (internal) | Not external data. It is a build task (zip assembly). The JSON/CSV buttons are already real |

### Partial removals inside kept panels

These six kept panels lose invented sub-content:

- **I1:** remove the "within permit zone" wording.
- **I5:** remove the mitigation-success and indicator-stability sub-metrics.
- **I9:** remove the task checkboxes.
- **L1:** replace the illustrative flow polylines.
- **L2:** remove the "~7–14 days" persistence claim.
- **A3:** remove the hard-coded 4.2 °C and 1840 m.

Separately, the footers on Industrial (`:486`) and Legislative (`:545`) still read "Reference DB: MarineGenomeDB
v4.2 · Matched 15 Aug 2026". This is not a `MockTag`, but it is invented. Replace it with the
B4 reference DB version.

## Verification log (2026-10-18, all requests anonymous)

Sample point for every query: **15.6° N, 82.3° E** (Bay of Bengal, the `Sector 3` hotspot
coordinate on the Legislative page). Sample date: **2026-10-01**.

| ID | Source | Exact request that returned data | Sample value | Resolution / latency | Access / licence |
|----|--------|----------------------------------|--------------|----------------------|------------------|
| V1 | NOAA ERDDAP (NCEI), OISST v2.1 prelim | `https://www.ncei.noaa.gov/erddap/griddap/ncdc_oisst_v2_avhrr_prelim_by_time_zlev_lat_lon.csv?sst%5B(last)%5D%5B(0.0)%5D%5B(15.625)%5D%5B(82.375)%5D` | `2026-10-16T12:00:00Z, 15.625, 82.375, sst=30.09 °C` | 0.25°, daily, surface only. Latest prelim date was 2 days before the query. The final dataset `ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon` ended at 2026-10-02 (30.25 °C), about 16 days behind | Free, no auth, US public domain. Use as a fallback or cross-check for surface temperature |
| V2 | Copernicus Marine PHY, `cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m_202406` | ARCO zarr chunk `https://s3.waw3-1.cloudferro.com/mdl-arco-time-012/arco/GLOBAL_ANALYSISFORECAST_PHY_001_024/cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m_202406/timeChunked.zarr/thetao/1583.49.2.1` (blosc-lz4 float32; index from `.zmetadata` + coordinate arrays) | `2026-10-01, 15.5833 N, 82.3333 E, −0.49 m: thetao=30.2808 °C` | 1/12° (~9 km), daily mean, 50 levels to 5728 m. Time axis 2022-06-01 → 2026-10-27 (analysis + 10-day forecast). For dates before 2022-06, use `GLOBAL_MULTIYEAR_PHY_001_030` (STAC metadata returned HTTP 200) | Free of charge under the Copernicus Marine licence; attribution "E.U. Copernicus Marine Service Information". **The supported access path (`copernicusmarine` toolbox) needs a free account.** The anonymous ARCO read worked but is undocumented |
| V3 | Same dataset, at depth | Chunks `…/thetao/1583.18.2.1` and `…/thetao/1583.10.2.1` | `−541.09 m: 9.1562 °C`; `−1941.89 m: 2.5621 °C` | as V2 | as V2 |
| V4 | Copernicus Marine PHY currents, `cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m_202406` | `https://s3.waw3-1.cloudferro.com/mdl-arco-time-007/arco/GLOBAL_ANALYSISFORECAST_PHY_001_024/cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m_202406/timeChunked.zarr/uo/1583.49.2.1` (and `/vo/1583.49.2.1`) | `uo=−0.3439 m/s, vo=−0.0728 m/s`, so speed = 0.352 m/s (0.68 kn), heading toward 258° (WSW) | as V2 | as V2 |
| V5 | Copernicus Marine BGC, `cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m_202311` | `https://s3.waw3-1.cloudferro.com/mdl-arco-time-006/arco/GLOBAL_ANALYSISFORECAST_BGC_001_028/cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m_202311/timeChunked.zarr/o2/1795.49.0.0` | `2026-10-01, 15.50 N, 82.25 E, −0.49 m: o2=207.2282 mmol m⁻³` (= 6.63 mg/L) | 0.25°, daily, 50 levels. Time axis 2021-11-01 → 2026-10-27. Earlier dates: `GLOBAL_MULTIYEAR_BGC_001_029` (STAC metadata returned HTTP 200) | as V2 |
| V6 | Copernicus Marine BGC, `cmems_mod_glo_bgc-car_anfc_0.25deg_P1D-m_202311` | `…/GLOBAL_ANALYSISFORECAST_BGC_001_028/cmems_mod_glo_bgc-car_anfc_0.25deg_P1D-m_202311/timeChunked.zarr/ph/1795.49.0.0` (same host and bucket as V5) | `ph=8.0317` | as V5 | as V2 |
| V7 | Copernicus Marine PHY salinity, `cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m_202406` | `https://s3.waw3-1.cloudferro.com/mdl-arco-time-010/arco/GLOBAL_ANALYSISFORECAST_PHY_001_024/cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m_202406/timeChunked.zarr/so/1583.49.2.1` | `so=30.7870` (1e-3) | as V2 | as V2 |
| V8 | ECMWF ERA5 through Open-Meteo | `https://archive-api.open-meteo.com/v1/era5?latitude=15.6&longitude=82.3&start_date=2026-10-01&end_date=2026-10-01&hourly=wind_speed_10m,wind_direction_10m&wind_speed_unit=kn&timezone=UTC` | `2026-10-01T00:00: 4.2 kn @ 185°`. Daily max for 1–7 Oct (`/v1/archive`, `daily=wind_speed_10m_max`): 4.6, 6.7, 5.7, 6.6, 5.2, 5.7, 6.1 kn | 0.25°, hourly. Values came back through **2026-10-17** (the day before the query), which is shorter than ERA5's usual ~5-day lag. Store the model or source with each value | Free, no key. **Non-commercial use only** (Open-Meteo terms page: "You may only use the free API services for non-commercial purposes"). Data is CC BY 4.0 |
| V9 | WoRMS REST, IUCN status | `https://www.marinespecies.org/rest/AphiaIDByName/Rhincodon%20typus?marine_only=true` returned `105847`. `https://www.marinespecies.org/rest/AphiaAttributesByAphiaID/105847?include_inherited=false` returned IUCN Red List Category | `IUCN Red List Category = Endangered`, Criteria A2bd+4bd, Year Assessed 2016. Also `CITES Annex = II` | Per taxon. Cache per AphiaID. The IUCN copy inside WoRMS can lag behind the IUCN site | Free, no auth, CC BY. The direct IUCN Red List API v4 (`https://api.iucnredlist.org/api/v4/…`) returned **HTTP 403 without a token**, so we use WoRMS instead |
| V10 | WoRMS REST, alien / invasive status by locality | `https://www.marinespecies.org/rest/AphiaIDByName/Mytilopsis%20sallei?marine_only=false` returned `397147`. `https://www.marinespecies.org/rest/AphiaDistributionsByAphiaID/397147` | `Visakhapatnam: Alien / Invasive`; `Andaman Sea: Alien / Uncertain`; `Caribbean Sea: Native` | Per taxon × locality name. Matching a locality to the sample's coordinates needs a region lookup (MRGID or name list) | Free, no auth, CC BY |
| V11 | Open-Meteo Marine (currents, alternative to V4) | `https://marine-api.open-meteo.com/v1/marine?latitude=15.6&longitude=82.3&start_date=2026-10-01&end_date=2026-10-01&hourly=ocean_current_velocity,ocean_current_direction,sea_surface_temperature&timezone=UTC` | `ocean_current_velocity` 1.0–1.6 km/h over 2026-10-01 (0.28–0.44 m/s, consistent with V4's 0.35 m/s) | Nearest grid point 15.625 N, 82.29 E, hourly | Same non-commercial terms as V8 |
| V12 | MGnify (EMBL-EBI) API | `https://www.ebi.ac.uk/metagenomics/api/v1/samples?latitude_gte=10&latitude_lte=22&longitude_gte=80&longitude_lte=95&page_size=5` | 208 samples in the box. First: `SRS12469199` at 12.0081 N, 92.9416 E, in study `MGYS00006756` "Metagenomic exploration of Surface waters from the Andaman and Nicobar Islands, India" (14 samples). Its analysis `MGYA00788554` (amplicon, pipeline 5.0) returned SSU taxonomy through `…/analyses/MGYA00788554/taxonomy/ssu`, with 1200 lineages, e.g. `Bacteria` count 7807 | Static archive. Coverage is sparse and depends on the study. Many samples have no `collection-date` (the first 5 all returned `None`) | Free, no auth (EMBL-EBI terms of use) |

### Failed or partial verification attempts (recorded as they happened)

- **`coastwatch.pfeg.noaa.gov` (the West Coast CoastWatch ERDDAP, dataset `ncdcOisst21Agg_LonPM180`)
  timed out twice** from the dev box (`curl: (28) Connection timed out after 60001 ms`). Its mirror
  `upwell.pfeg.noaa.gov` answered, but only with a `302` redirect back to coastwatch.pfeg. The NCEI
  ERDDAP (V1) served the same OISST product. **Use `www.ncei.noaa.gov/erddap` as the ERDDAP host.**
- `coastwatch.noaa.gov/erddap/search/…` and `polarwatch.noaa.gov/erddap/search/…` returned website
  404 pages, not ERDDAP. We did not use them.
- **IUCN Red List API v4: HTTP 403 without a token.** This was expected, and WoRMS (V9) replaces it.
- The MGnify `ordering=-count` parameter on the taxonomy endpoint had no effect, and results came
  back unsorted. Sort on our side.
- **Not verified by query:** the Copernicus Climate Data Store (the commercial-safe route to ERA5),
  because it needs an account. The `copernicusmarine` toolbox login flow was not tested either,
  because we have no account yet.

## User actions needed

1. **Create a free Copernicus Marine account** (marine.copernicus.eu → Register) and put the
   credentials in the API/worker env, e.g. `COPERNICUSMARINE_SERVICE_USERNAME` and
   `COPERNICUSMARINE_SERVICE_PASSWORD`, for the Day 13 environmental-context service. Anonymous ARCO
   reads worked on 2026-10-18 (V2–V7), but that path is undocumented and could start requiring
   auth. Without the account, the Day 13 service depends on it.
2. **Decide whether the deployment is commercial.** If it is, Open-Meteo's free API (V8, V11) is not
   allowed. Either buy an Open-Meteo API key or register for the Copernicus Climate Data Store (free)
   and pull ERA5 wind from there. Currents already come from Copernicus Marine (V4), so this
   affects wind only.
3. **Supply the indicator-species list** (taxon names) for L3. Without it, L3 shows "no indicator
   list configured" rather than a trend.
4. **Optional:** request an IUCN Red List API token (free for non-commercial use) if WoRMS's copy of
   IUCN categories (V9) is not current enough for legal-facing alerts.

## v2: external data (removed for v1)

These 12 panels have no viable v1 source. Remove them from the pages and add this list to
`prd.md` under "v2: external data", as Q5 requires.

| # | Panel | Page | What v2 would need |
|---|-------|------|--------------------|
| I2 | Average impact score | Industrial | A defined impact methodology and a "project" entity |
| I3 | Pending audits | Industrial | An audit-schedule store (partner workflow, not a public feed) |
| I4 | Environmental risk radar | Industrial | Regulatory-fine, permit and supply-chain data sources |
| I6 | Audit trail + Schedule Audit | Industrial | An audit-record store and a scheduling backend |
| I7 | Remediation plan | Industrial | A remediation tracker |
| I10 | Predictive threshold · biofouling | Industrial | A regulatory biofouling limit and a validated forecast model |
| I11 | Remediation ROI · cost delta | Industrial | Contractor rate card and fine schedule |
| L4 | Habitat-associated taxa decline | Legislative | Taxon-to-habitat association data (WoRMS traits or a curated list) |
| L5 | Economic risk & compliance exposure | Legislative | Economic and regulatory exposure models, and a real feasibility run |
| A2 | Toxicity index | Academia | A toxicology lab-panel integration |
| A9 | Sonic activity · ambient noise | Academia | Hydrophone or passive-acoustic data |
| A10 | Activity rhythms · vertical migration | Academia | Acoustic backscatter or sub-daily sampling |

Sub-panel content removed from kept panels (also v2): I5 mitigation success and indicator
stability, and the I9 task checkboxes.

## What this unblocks

- **Day 13 (BE, environmental context service):** one lookup per upload with coordinates + date
  returns `thetao` (surface/mid/sample depth), `so`, `uo`/`vo`, `o2` and `ph` from Copernicus
  Marine (V2–V7), plus ERA5 wind (V8). Each value is cached with its dataset ID, grid cell and
  timestamp. OISST on NCEI ERDDAP (V1) is the no-auth fallback for surface temperature.
- **Day 13 (BE, `GET /partner/summary`, B16):** I1, L1, L2, L3 and A11 aggregate over uploads and
  results plus the cached WoRMS status per AphiaID (V9, V10).
- **Taxon-based panels depend on B4:** I1, I5, L2, L3 and A11 need species-level `predicted_taxon`
  from the reference lookup. Without it, they show "no species-level assignments".
