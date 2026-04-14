"""FDA / ClinicalTrials.gov — uses the free REST API (more reliable than browser)."""

import logging
import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 10
CT_API_BASE = "https://clinicaltrials.gov/api/v2/studies"


def search_trials(
    query: str,
    phase: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search ClinicalTrials.gov API for trials.

    Args:
        query: Company, drug, or condition name.
        phase: Trial phase filter.
        status: Overall status filter.
        limit: Max results.
    """
    try:
        params = {
            "query.term": query,
            "pageSize": limit,
            "format": "json",
        }
        if phase:
            params["filter.phase"] = phase
        if status:
            params["filter.overallStatus"] = status
        headers = {"User-Agent": "ai-fund/1.0 (research; contact@example.com)"}
        resp = httpx.get(CT_API_BASE, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        studies = data.get("studies", [])
        trials = []
        for study in studies:
            protocol = study.get("protocolSection", {})
            id_module = protocol.get("identificationModule", {})
            status_module = protocol.get("statusModule", {})
            design_module = protocol.get("designModule", {})

            trials.append({
                "nct_id": id_module.get("nctId"),
                "title": id_module.get("briefTitle"),
                "status": status_module.get("overallStatus"),
                "phase": _get_phases(design_module),
                "start_date": status_module.get("startDateStruct", {}).get("date"),
            })

        logger.info("ClinicalTrials API: %d trials for '%s'", len(trials), query)
        return trials

    except Exception as e:
        logger.error("ClinicalTrials API failed for '%s': %s", query, e)
        return []


def get_pharma_trials(companies: list[str]) -> dict[str, list[dict]]:
    """Get Phase 3 trials for multiple pharma companies."""
    results = {}
    for company in companies:
        results[company] = search_trials(company)
    return results


def get_fda_approvals(limit: int = 10) -> list[dict]:
    """Get recent drug events from the FDA API."""
    try:
        resp = httpx.get(
            "https://api.fda.gov/drug/event.json",
            params={"limit": limit, "sort": "receivedate:desc"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [
            {
                "date": r.get("receivedate"),
                "drug": r.get("patient", {}).get("drug", [{}])[0].get("medicinalproduct")
                if r.get("patient", {}).get("drug") else None,
                "reaction": r.get("patient", {}).get("reaction", [{}])[0].get("reactionmeddrapt")
                if r.get("patient", {}).get("reaction") else None,
                "serious": r.get("serious"),
            }
            for r in results
        ]
    except Exception as e:
        logger.error("FDA API failed: %s", e)
        return []


def _get_phases(design_module: dict) -> str:
    phases = design_module.get("phases", [])
    return ", ".join(phases) if phases else "unknown"
