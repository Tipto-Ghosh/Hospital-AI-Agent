"""
The canonical @tool implementations for medication information.

Returns Pydantic model instances rather than raw ORM objects or JSON
strings.
These tools are read-only general drug information and are not
patient-specific, so no audit logging occurs here.
"""

from __future__ import annotations
from typing import Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from app.db.base import get_session_context
from app.db.repositories.medication_repo import MedicationRepository
from app.logger import logging

logger = logging.getLogger(__name__)


class MedicationInfoResult(BaseModel):
    """General information about a single medication."""
    found: bool
    generic_name: Optional[str] = None
    brand_names: Optional[str] = None
    drug_class: Optional[str] = None
    common_uses: Optional[str] = None
    side_effects: Optional[str] = None
    general_dosage: Optional[str] = None
    requires_prescription: Optional[bool] = None
    suggestions: list[str] = Field(
        default_factory = list,
        description = "Other medication names that partially matched, if no exact match was found.",
    )

class DrugInteractionEntry(BaseModel):
    """A single known interaction between two drugs."""
    drug_a: str
    drug_b: str
    severity: str
    description: str

class DrugInteractionResult(BaseModel):
    """
    Known interactions between two medications.

    An empty interactions list means nothing is recorded - this does
    **not** mean the combination is confirmed safe, only that no
    interaction is on file.
    """
    interactions: list[DrugInteractionEntry] = Field(default_factory = list)


@tool
async def query_medication_info(drug_name: str) -> MedicationInfoResult:
    """
    Look up general information about a medication by generic or brand
    name.

    Parameters
    ----------
    drug_name   Generic or brand name, e.g. "metformin" or "Glucophage". Fuzzy, case-insensitive matching.

    Returns
    -------
    MedicationInfoResult. found=true with full details for an exact or
    single fuzzy match. found=false with a list of suggestions if
    multiple partial matches exist, or an empty suggestions list if
    nothing matches at all.
    """
    async with get_session_context() as session:
        repo = MedicationRepository(session)

        exact = await repo.get_by_generic_name(drug_name)
        if exact is not None:
            logger.info(f"query_medication_info(drug_name={drug_name!r}) -> exact match: {exact.generic_name}")
            return MedicationInfoResult(
                found=True,
                generic_name=exact.generic_name,
                brand_names=exact.brand_names,
                drug_class=exact.drug_class,
                common_uses=exact.common_uses,
                side_effects=exact.side_effects,
                general_dosage=exact.general_dosage,
                requires_prescription=exact.requires_prescription,
            )

        matches = await repo.search(drug_name)
        if len(matches) == 1:
            m = matches[0]
            logger.info(f"query_medication_info(drug_name={drug_name!r}) -> single fuzzy match: {m.generic_name}")
            return MedicationInfoResult(
                found=True,
                generic_name=m.generic_name,
                brand_names=m.brand_names,
                drug_class=m.drug_class,
                common_uses=m.common_uses,
                side_effects=m.side_effects,
                general_dosage=m.general_dosage,
                requires_prescription=m.requires_prescription,
            )

    suggestions = [m.generic_name for m in matches]
    logger.info(f"query_medication_info(drug_name={drug_name!r}) -> no exact match, suggestions={suggestions}")
    return MedicationInfoResult(found=False, suggestions=suggestions)


@tool
async def check_drug_interaction(drug_a: str, drug_b: str) -> DrugInteractionResult:
    """
    Check for known interactions between two medications.

    Parameters
    ----------
    drug_a   Generic name of the first drug.
    drug_b   Generic name of the second drug.

    Returns
    -------
    DrugInteractionResult with an empty interactions list if nothing
    is on file for this pair.
    """
    async with get_session_context() as session:
        repo = MedicationRepository(session)
        results = await repo.get_interactions(drug_a, drug_b)

    entries = [
        DrugInteractionEntry(
            drug_a=r.drug_a,
            drug_b=r.drug_b,
            severity=r.severity,
            description=r.description,
        )
        for r in results
    ]

    logger.info(f"check_drug_interaction(drug_a={drug_a!r}, drug_b={drug_b!r}) -> {len(entries)} interaction(s)")
    return DrugInteractionResult(interactions=entries)


medication_tools = [query_medication_info, check_drug_interaction]