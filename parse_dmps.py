"""
parse_dmps.py
─────────────────────────────────────────────────────────────────────────────
Parses maDMP JSON files (RDA DMP Common Standard v1.2) into a flat DataFrame
ready for Latent Class Analysis.

Full schema:
https://raw.githubusercontent.com/RDA-DMP-Common/RDA-DMP-Common-Standard/
refs/heads/master/examples/JSON/JSON-schema/1.2/maDMP-schema-1.2.json

Design decisions
────────────────
- Unit of analysis  : one row per DMP (plan-level)
- Multi-dataset     : Option 1 — aggregate to binary flags + counts
- unknown values    : Option C — split into two binary indicators
                        {field}_yes    : 1 iff value == "yes"
                        {field}_filled : 1 iff value in {yes, no}
- Free-text fields  : presence (binary) + length (plain-text chars, HTML stripped)
- Missing / null    : 0  (distinct from explicit "unknown")
"""

from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────

INPUT_DIR     = "argos_exports"
OUTPUT_CSV    = "dmp_features.csv"
OUTPUT_REPORT = "parse_report.txt"

# ── Generic helpers ───────────────────────────────────────────────────────────

def strip_html(text):
    if not text:
        return ""
    return BeautifulSoup(str(text), "html.parser").get_text(separator=" ").strip()

def text_features(raw, prefix):
    """Presence (0/1) + stripped character length for any free-text field."""
    if raw is None:
        return {f"{prefix}_present": 0, f"{prefix}_length": 0}
    clean = strip_html(raw)
    return {f"{prefix}_present": int(len(clean) > 0),
            f"{prefix}_length":  len(clean)}

def tristate(value, field_name):
    """yes/no/unknown → _yes and _filled binary indicators."""
    v = (value or "").strip().lower()
    return {f"{field_name}_yes":    int(v == "yes"),
            f"{field_name}_filled": int(v in ("yes", "no"))}

def is_orcid(identifier):
    return bool(re.match(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$",
                         str(identifier or "")))

def bin_count(n, thresholds=(1, 2, 6)):
    """0→0, 1→1, 2-5→2, 6+→3"""
    if n == 0:            return 0
    if n < thresholds[1]: return 1
    if n < thresholds[2]: return 2
    return 3

def normalise_id_block(raw):
    """
    v1.2 allows contact_id / contributor_id to be either a single object
    OR an array of objects. Always return a list.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    return [raw]


# ── Affiliation helper ────────────────────────────────────────────────────────

def affiliation_features(affiliations, prefix):
    """
    affiliations : list of Affiliation objects (v1.2 new)
    Returns binary flags for presence and identifier type.
    """
    affs = affiliations or []
    has_aff   = int(len(affs) > 0)
    has_ror   = 0
    has_grid  = 0
    has_isni  = 0

    for a in affs:
        aid  = a.get("affiliation_id") or {}
        atype = (aid.get("type") or "").lower()
        if atype == "ror":  has_ror  = 1
        if atype == "grid": has_grid = 1
        if atype == "isni": has_isni = 1
    return {
        f"{prefix}_has_affiliation":      has_aff,
        f"{prefix}_affiliation_has_ror":  has_ror,
        f"{prefix}_affiliation_has_grid": has_grid,
        f"{prefix}_affiliation_has_isni": has_isni,
    }


# ── Related / alternate identifier helpers ────────────────────────────────────

def related_id_features(related_ids, prefix):
    """
    related_identifier is new in v1.2 at both DMP and dataset level.
    Each item has: identifier, type, relation_type, resource_type (opt), etc.
    """
    items = related_ids or []
    if not items:
        return {f"{prefix}_has_related_id": 0,
                f"{prefix}_n_related_ids": 0}
    relation_types = {(r.get("relation_type") or "").lower() for r in items}
    return {
        f"{prefix}_has_related_id":          1,
        f"{prefix}_n_related_ids":           len(items),
        f"{prefix}_related_id_ispartof":     int("ispartof"     in relation_types),
        f"{prefix}_related_id_haspart":      int("haspart"      in relation_types),
        f"{prefix}_related_id_isderivedfrom":int("isderivedfrom"in relation_types),
        f"{prefix}_related_id_cites":        int("cites"        in relation_types),
    }

def alternate_id_features(alt_ids, prefix):
    """alternate_identifier new in v1.2."""
    items = alt_ids or []
    return {
        f"{prefix}_has_alternate_id": int(len(items) > 0),
        f"{prefix}_n_alternate_ids":  len(items),
    }


# ── Section parsers ───────────────────────────────────────────────────────────

# ·· DMP root ·················································
def parse_dmp_metadata(dmp):
    row = {}

    # dmp_id
    dmp_id  = dmp.get("dmp_id") or {}
    id_type = (dmp_id.get("type") or "").lower()
    row["dmp_id_present"]     = int(bool(dmp_id.get("identifier")))
    row["dmp_id_type_doi"]    = int(id_type == "doi")
    row["dmp_id_type_handle"] = int(id_type == "handle")
    row["dmp_id_type_ark"]    = int(id_type == "ark")
    row["dmp_id_type_url"]    = int(id_type == "url")
    row["dmp_id_type_other"]  = int(id_type not in ("doi","handle","ark","url","")
                                    and bool(id_type))

    # alternate_identifier at DMP level (v1.2)
    row.update(alternate_id_features(dmp.get("alternate_identifier"), "dmp"))

    # related_identifier at DMP level (v1.2)
    row.update(related_id_features(dmp.get("related_identifier"), "dmp"))

    # language
    lang = (dmp.get("language") or "").strip().lower()
    row["language_eng"]     = int(lang == "eng")
    row["language_present"] = int(len(lang) > 0)

    # timestamps
    # row["has_created"]  = int(bool(dmp.get("created")))
    # row["has_modified"] = int(bool(dmp.get("modified")))

    # ethical issues
    row.update(tristate(dmp.get("ethical_issues_exist"), "ethical_issues_exist"))
    row.update(text_features(dmp.get("ethical_issues_description"),
                              "ethical_issues_description"))
    row["has_ethical_issues_report"] = int(bool(dmp.get("ethical_issues_report")))

    # free-text plan fields
    row.update(text_features(dmp.get("title"),       "plan_title"))
    row.update(text_features(dmp.get("description"), "plan_description"))

    return row


# ·· Contact ···················································
def parse_contact(dmp):
    contact = dmp.get("contact") or {}
    ids     = normalise_id_block(contact.get("contact_id"))

    has_orcid   = 0
    has_isni    = 0
    has_openid  = 0
    for cid in ids:
        ctype = (cid.get("type") or "").lower()
        if ctype == "orcid" or is_orcid(cid.get("identifier")):
            has_orcid  = 1
        if ctype == "isni":   has_isni   = 1
        if ctype == "openid": has_openid = 1

    row = {
        "contact_has_name":        int(bool(contact.get("name"))),
        "contact_has_mbox":        int(bool(contact.get("mbox"))),
        "contact_has_id":          int(len(ids) > 0),
        "contact_id_is_orcid":     has_orcid,
        "contact_id_is_isni":      has_isni,
        "contact_id_is_openid":    has_openid,
        "contact_n_ids":           len(ids),        # v1.2 allows multiple IDs
    }
    # affiliation (v1.2)
    row.update(affiliation_features(contact.get("affiliation"), "contact"))
    return row


# ·· Contributors ··············································
def parse_contributors(dmp):
    contributors = dmp.get("contributor") or []
    n = len(contributors)

    has_orcid  = 0
    has_mbox   = 0
    has_affil  = 0
    roles      = set()

    for c in contributors:
        ids = normalise_id_block(c.get("contributor_id"))
        for cid in ids:
            ctype = (cid.get("type") or "").lower()
            if ctype == "orcid" or is_orcid(cid.get("identifier")):
                has_orcid = 1
        if c.get("mbox"):
            has_mbox = 1
        if c.get("affiliation"):
            has_affil = 1
        for r in (c.get("role") or []):
            roles.add(r.strip().lower())

    # DataCite contributorType vocabulary (commonly used in v1.2)
    datacite_roles = {
        "datamanager", "datacollector", "datacurator", "projectleader",
        "projectmanager", "researcher", "supervisor", "workpackageleader",
        "rightsholder", "producer", "distributor", "editor", "sponsor",
        "other",
    }

    return {
        "n_contributors":                   n,
        "n_contributors_binned":            bin_count(n),
        "contributor_has_orcid":            has_orcid,
        "contributor_has_mbox":             has_mbox,
        "contributor_has_affiliation":      has_affil,       # v1.2
        "contributor_role_owner":           int("owner" in roles),
        "contributor_role_researcher":      int(any("research" in r for r in roles)),
        "contributor_role_contact":         int("contact person" in roles),
        "contributor_role_datamanager":     int("datamanager" in roles),
        "contributor_role_steward":         int(any("steward" in r for r in roles)),
        "contributor_n_distinct_roles":     len(roles),
    }


# ·· Cost ·····················································
def parse_cost(dmp):
    costs = dmp.get("cost") or []
    n     = len(costs)
    has_value = has_currency = has_desc = 0
    total_value = 0.0
    for c in costs:
        if c.get("value") is not None:
            has_value    = 1
            total_value += float(c.get("value") or 0)
        if c.get("currency_code"): has_currency = 1
        if c.get("description"):   has_desc     = 1
    return {
        "has_cost":             int(n > 0),
        "n_cost_items":         n,
        "cost_has_value":       has_value,
        "cost_has_currency":    has_currency,
        "cost_has_description": has_desc,
        "cost_total_value":     total_value,
    }


# ·· Project / Funding ·········································
def parse_project(dmp):
    projects = dmp.get("project") or []
    if not projects:
        return {
            "has_project":              0,
            "project_has_description":  0,
            "project_has_start":        0,
            "project_has_end":          0,
            "project_has_project_id":   0,   # v1.2
            "has_funding":              0,
            "has_funder_id":            0,
            "funder_id_type_fundref":   0,
            "has_grant_id":             0,
            "funding_status_planned":   0,
            "funding_status_applied":   0,
            "funding_status_granted":   0,
            "funding_status_rejected":  0,
            "funding_has_status":       0,
            "funding_funder_is_ec":     0,
        }

    has_desc = has_start = has_end = has_pid = 0
    has_funding = has_fid = fid_fundref = has_gid = is_ec = 0
    statuses = set()

    for proj in projects:
        if proj.get("description"):  has_desc  = 1
        if proj.get("start"):        has_start = 1
        if proj.get("end"):          has_end   = 1
        if proj.get("project_id"):   has_pid   = 1   # v1.2

        for f in (proj.get("funding") or []):
            has_funding = 1
            fid = f.get("funder_id") or {}
            gid = f.get("grant_id")  or {}
            if fid.get("identifier"):
                has_fid  = 1
                fid_str  = str(fid.get("identifier") or "").lower()
                if "ec" in fid_str or "european commission" in fid_str:
                    is_ec = 1
            if (fid.get("type") or "").lower() == "fundref":
                fid_fundref = 1
            if gid.get("identifier"):
                has_gid = 1
            status = (f.get("funding_status") or "").lower()
            if status:
                statuses.add(status)

    return {
        "has_project":              1,
        "project_has_description":  has_desc,
        "project_has_start":        has_start,
        "project_has_end":          has_end,
        "project_has_project_id":   has_pid,
        "has_funding":              has_funding,
        "has_funder_id":            has_fid,
        "funder_id_type_fundref":   fid_fundref,
        "has_grant_id":             has_gid,
        "funding_status_planned":   int("planned"  in statuses),
        "funding_status_applied":   int("applied"  in statuses),
        "funding_status_granted":   int("granted"  in statuses),
        "funding_status_rejected":  int("rejected" in statuses),
        "funding_has_status":       int(len(statuses) > 0),
        "funding_funder_is_ec":     is_ec,
    }


# ·· Datasets (aggregated to plan level) ·······················

CERT_VALUES = {"din31644", "dini-zertifikat", "dsa", "iso16363",
               "iso16919", "trac", "wds", "coretrustseal"}

def parse_datasets(dmp):
    datasets = dmp.get("dataset") or []
    n = len(datasets)
    row = {"n_datasets": n, "n_datasets_binned": bin_count(n)}

    # ── tristate fields ──────────────────────────────────────
    for field in ("personal_data", "sensitive_data"):
        yes_f = filled_f = 0
        for ds in datasets:
            v = (ds.get(field) or "").strip().lower()
            if v == "yes":        yes_f    = 1
            if v in ("yes","no"): filled_f = 1
        row[f"dataset_{field}_yes"]    = yes_f
        row[f"dataset_{field}_filled"] = filled_f

    # ── dataset_id type ──────────────────────────────────────
    dsid_doi = dsid_handle = dsid_ark = dsid_url = dsid_other = 0
    for ds in datasets:
        dsid = ds.get("dataset_id") or {}
        t = (dsid.get("type") or "").lower()
        if t == "doi":    dsid_doi    = 1
        if t == "handle": dsid_handle = 1
        if t == "ark":    dsid_ark    = 1
        if t == "url":    dsid_url    = 1
        if t and t not in ("doi","handle","ark","url"): dsid_other = 1
    row.update({
        "dataset_id_type_doi":    dsid_doi,
        "dataset_id_type_handle": dsid_handle,
        "dataset_id_type_ark":    dsid_ark,
        "dataset_id_type_url":    dsid_url,
        "dataset_id_type_other":  dsid_other,
    })

    # ── v1.2: alternate_identifier and related_identifier on datasets ──
    has_alt_id = has_rel_id = 0
    for ds in datasets:
        if ds.get("alternate_identifier"): has_alt_id = 1
        if ds.get("related_identifier"):   has_rel_id = 1
    row["dataset_has_alternate_id"] = has_alt_id
    row["dataset_has_related_id"]   = has_rel_id

    # ── v1.2: is_reused ──────────────────────────────────────
    any_reused = any_reused_set = 0
    for ds in datasets:
        v = ds.get("is_reused")
        if v is not None:
            any_reused_set = 1
            if v is True: any_reused = 1
    row["dataset_any_is_reused"]     = any_reused
    row["dataset_is_reused_filled"]  = any_reused_set

    # ── v1.2: rights ─────────────────────────────────────────
    rights_present = rights_len = 0
    for ds in datasets:
        f = text_features(ds.get("rights"), "x")
        rights_present = max(rights_present, f["x_present"])
        rights_len    += f["x_length"]
    row["dataset_rights_any_present"]  = rights_present
    row["dataset_rights_total_length"] = rights_len

    # ── v1.2: creator on dataset ─────────────────────────────
    has_creator = creator_has_orcid = creator_has_affil = 0
    for ds in datasets:
        creators = ds.get("creator") or []
        if creators:
            has_creator = 1
            for cr in creators:
                ids = normalise_id_block(cr.get("creator_id"))
                for cid in ids:
                    ctype = (cid.get("type") or "").lower()
                    if ctype == "orcid" or is_orcid(cid.get("identifier")):
                        creator_has_orcid = 1
                if cr.get("affiliation"):
                    creator_has_affil = 1
    row["dataset_has_creator"]            = has_creator
    row["dataset_creator_has_orcid"]      = creator_has_orcid
    row["dataset_creator_has_affiliation"]= creator_has_affil

    # ── free-text / presence fields ──────────────────────────
    desc_present = title_present = preservation_present = 0
    desc_total_len = preservation_total_len = 0
    has_dqa = has_issued = has_keywords = 0
    has_security_privacy = has_technical_resource = 0
    has_tech_resource_id = 0   # v1.2
    n_keywords_total = 0

    for ds in datasets:
        d = text_features(ds.get("description"), "x")
        desc_present    = max(desc_present, d["x_present"])
        desc_total_len += d["x_length"]

        if ds.get("title"):
            title_present = 1

        p = text_features(ds.get("preservation_statement"), "x")
        preservation_present    = max(preservation_present, p["x_present"])
        preservation_total_len += p["x_length"]

        if ds.get("data_quality_assurance"): has_dqa     = 1
        if ds.get("issued"):                 has_issued  = 1
        kw = ds.get("keyword") or []
        if kw:
            has_keywords      = 1
            n_keywords_total += len(kw)
        if ds.get("security_and_privacy"):   has_security_privacy    = 1
        if ds.get("technical_resource"):
            has_technical_resource = 1
            for tr in (ds.get("technical_resource") or []):
                if tr.get("technical_resource_id"):
                    has_tech_resource_id = 1

    row.update({
        "dataset_desc_any_present":           desc_present,
        "dataset_desc_total_length":          desc_total_len,
        "dataset_title_any_present":          title_present,
        "dataset_preservation_any_present":   preservation_present,
        "dataset_preservation_total_length":  preservation_total_len,
        "dataset_has_dqa":                    has_dqa,
        "dataset_has_issued":                 has_issued,
        "dataset_has_keywords":               has_keywords,
        "dataset_n_keywords_total":           n_keywords_total,
        "dataset_has_security_privacy":       has_security_privacy,
        "dataset_has_technical_resource":     has_technical_resource,
        "dataset_tech_resource_has_id":       has_tech_resource_id,  # v1.2
    })

    # ── language ─────────────────────────────────────────────
    ds_langs = set()
    for ds in datasets:
        lang = (ds.get("language") or "").strip().lower()
        if lang: ds_langs.add(lang)
    row["dataset_any_language_set"] = int(len(ds_langs) > 0)
    row["dataset_all_eng"]          = int(ds_langs == {"eng"} if ds_langs else False)

    # ── type ─────────────────────────────────────────────────
    row["dataset_any_type_set"] = int(
        any(bool(ds.get("type")) for ds in datasets)
    )

    # ── metadata standards ────────────────────────────────────
    row["dataset_has_metadata_standard"] = int(
        any(bool(ds.get("metadata")) for ds in datasets)
    )

    # ── distributions ─────────────────────────────────────────
    row.update(_parse_distributions(datasets))

    return row


def _parse_distributions(datasets):
    row = {}

    n_with_format = n_with_bytesize = n_with_access = 0
    n_with_license = n_with_host = n_with_avail_url = 0
    n_with_dl_url = n_with_available_until = n_with_dist_issued = 0

    access_open = access_shared = access_closed = 0
    host_certified = host_has_geo = host_has_pid = 0
    host_versioning_yes = host_versioning_filled = 0
    host_has_backup = host_has_availability = host_has_host_id = 0  # host_id v1.2
    license_is_cc = license_has_embargo = 0

    certs_seen = set()
    pids_seen  = set()

    for ds in datasets:
        for dist in (ds.get("distribution") or []):

            da = (dist.get("data_access") or "").lower()
            if da == "open":   access_open   = 1; n_with_access += 1
            if da == "shared": access_shared = 1; n_with_access += 1
            if da == "closed": access_closed = 1; n_with_access += 1

            if dist.get("byte_size")       is not None: n_with_bytesize        += 1
            if dist.get("access_url"):                  n_with_avail_url       += 1
            if dist.get("download_url"):                n_with_dl_url          += 1
            if dist.get("available_until"):             n_with_available_until += 1
            if dist.get("issued"):                      n_with_dist_issued     += 1  # v1.2

            fmts = dist.get("format") or []
            if fmts: n_with_format += 1

            licenses = dist.get("license") or []
            if licenses:
                n_with_license += 1
                for lic in licenses:
                    ref = (lic.get("license_ref") or "").lower()
                    if "creativecommons" in ref or "cc-by" in ref:
                        license_is_cc = 1
                    if lic.get("start_date"):
                        license_has_embargo = 1

            host = dist.get("host")
            if host:
                n_with_host += 1
                if host.get("certified_with"):
                    host_certified = 1
                    certs_seen.add((host.get("certified_with") or "").lower())
                if host.get("geo_location"):  host_has_geo = 1
                pids = host.get("pid_system") or []
                if pids:
                    host_has_pid = 1
                    for p in pids: pids_seen.add(p.lower())
                sv = (host.get("support_versioning") or "").lower()
                if sv == "yes":          host_versioning_yes    = 1
                if sv in ("yes","no"):   host_versioning_filled = 1
                if host.get("backup_frequency") or host.get("backup_type"):
                    host_has_backup = 1
                if host.get("availability"):
                    host_has_availability = 1
                if host.get("host_id"):   # v1.2
                    host_has_host_id = 1

    row.update({
        "dist_any_format_specified":    int(n_with_format > 0),
        "dist_any_bytesize_specified":  int(n_with_bytesize > 0),
        "dist_any_access_specified":    int(n_with_access > 0),
        "dist_access_open":             access_open,
        "dist_access_shared":           access_shared,
        "dist_access_closed":           access_closed,
        "dist_any_license_specified":   int(n_with_license > 0),
        "dist_license_is_cc":           license_is_cc,
        "dist_license_has_embargo":     license_has_embargo,
        "dist_any_access_url":          int(n_with_avail_url > 0),
        "dist_any_download_url":        int(n_with_dl_url > 0),
        "dist_any_available_until":     int(n_with_available_until > 0),
        "dist_any_issued":              int(n_with_dist_issued > 0),   # v1.2
        "dist_any_host":                int(n_with_host > 0),
        "dist_host_certified":          host_certified,
        "dist_host_has_geo":            host_has_geo,
        "dist_host_has_pid_system":     host_has_pid,
        "dist_host_versioning_yes":     host_versioning_yes,
        "dist_host_versioning_filled":  host_versioning_filled,
        "dist_host_has_backup":         host_has_backup,
        "dist_host_has_availability":   host_has_availability,
        "dist_host_has_host_id":        host_has_host_id,   # v1.2
    })

    # Certification one-hots
    for cert in CERT_VALUES:
        row[f"dist_host_cert_{cert.replace('-','_')}"] = int(cert in certs_seen)

    # PID system one-hots (most analytically relevant)
    for pid in ("doi", "handle", "url", "urn", "ark", "other"):
        row[f"dist_host_pid_{pid}"] = int(pid in pids_seen)

    return row


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        warnings.warn(f"Could not read {filepath.name}: {e}")
        return None

    dmp = data.get("dmp")
    if not dmp:
        warnings.warn(f"No 'dmp' key in {filepath.name}")
        return None

    row = {"file": filepath.stem}
    row.update(parse_dmp_metadata(dmp))
    row.update(parse_contact(dmp))
    row.update(parse_contributors(dmp))
    row.update(parse_cost(dmp))
    row.update(parse_project(dmp))
    row.update(parse_datasets(dmp))
    return row


# ── Report ────────────────────────────────────────────────────────────────────

def write_report(df, json_count, skipped):
    lines = [
        "maDMP Parse Report (schema v1.2)",
        "=" * 70,
        f"Input directory      : {INPUT_DIR}",
        f"JSON files found     : {json_count}",
        f"Successfully parsed  : {len(df)}",
        f"Skipped (errors)     : {len(skipped)}",
        f"Features extracted   : {len(df.columns)}",
        "",
        "Feature statistics",
        "-" * 70,
        f"{'Feature':<55} {'mean':>6}  {'%filled':>7}",
        "-" * 70,
    ]
    fill_rates = df.notna().mean() * 100
    for col in df.columns:
        if df[col].dtype == object:
            lines.append(f"  {col:<53}  (text)")
        else:
            lines.append(
                f"  {col:<53}  {df[col].mean():6.3f}   {fill_rates[col]:6.1f}%"
            )

    if skipped:
        lines += ["", "Skipped files:"] + [f"  {f}" for f in skipped]

    lines += ["", "Tristate field summary (% _yes among filled DMPs)", "-" * 70]
    yes_cols    = [c for c in df.columns if c.endswith("_yes")]
    filled_cols = [c.replace("_yes", "_filled") for c in yes_cols]
    for yc, fc in zip(yes_cols, filled_cols):
        if fc in df.columns:
            filled = df[fc].sum()
            yes    = df[yc].sum()
            pct    = (yes / filled * 100) if filled > 0 else float("nan")
            lines.append(
                f"  {yc:<53}  {yes:5.0f}/{filled:5.0f}  ({pct:5.1f}% of filled)"
            )

    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Saved parse report : {OUTPUT_REPORT}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    input_path = Path(INPUT_DIR)
    json_files = sorted(input_path.glob("*.json"))

    if not json_files:
        print(f"No JSON files found in '{INPUT_DIR}'. Exiting.")
        return

    print(f"Found {len(json_files)} JSON files.")

    rows, skipped = [], []
    for fp in json_files:
        row = parse_file(fp)
        if row is not None:
            rows.append(row)
        else:
            skipped.append(fp.name)

    df = pd.DataFrame(rows).set_index("file")
    df.to_csv(OUTPUT_CSV)

    print(f"\nSaved feature matrix : {OUTPUT_CSV}")
    print(f"  Shape : {df.shape[0]} DMPs × {df.shape[1]} features")
    if skipped:
        print(f"  Skipped : {len(skipped)} files")

    write_report(df, len(json_files), skipped)
    print("\nDone. Next step: load dmp_features.csv into your LCA pipeline.")


if __name__ == "__main__":
    main()