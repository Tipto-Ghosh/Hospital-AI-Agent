from __future__ import annotations
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.medication import DrugInteraction, Medication
from app.logger import logging

class MedicationRepository:
    """
    Read-only access to medications and drug_interactions.

    Parameters
    session: Active AsyncSession.
    """
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def search(
        self,
        drug_name: str,
        limit: int = 10,
    ) -> list[Medication]:
        """
        Fuzzy search for a medication by generic or brand name.

        Matches against:
          - generic_name   (e.g. "metformin" matches "metformin")
          - brand_names    (e.g. "glucophage" matches "Glucophage, Fortamet")

        Both comparisons are case-insensitive partial matches.

        Parameters
        ----------
        drug_name       Partial drug name typed by the patient or agent.
        limit           Maximum rows to return (default 10).

        Returns
        -------
        List of Medication ordered by generic_name.
        Returns an empty list if no match — agents should then tell
        the patient the drug isn't in the hospital's reference database
        and advise consulting a pharmacist.

        Example
        -------
            results = await repo.search("paracet")
            # → [Medication(generic_name='paracetamol', ...)]
        """
        term = drug_name.strip().lower()
        if not term:
            return []

        result = await self._s.execute(
            select(Medication)
            .where(
                or_(
                    func.lower(Medication.generic_name).contains(term),
                    func.lower(Medication.brand_names).contains(term),
                )
            )
            .order_by(Medication.generic_name)
            .limit(limit)
        )
        meds = list(result.scalars().all())
        logging.debug("medication search %r → %d results", drug_name, len(meds))
        return meds

    async def get_by_generic_name(self, generic_name: str) -> Medication | None:
        """
        Exact (case-insensitive) lookup by generic name.

        Used after search() narrows the list and the agent picks the
        specific drug to display information for.
        """
        result = await self._s.execute(
            select(Medication).where(
                func.lower(Medication.generic_name) == generic_name.strip().lower()
            )
        )
        return result.scalar_one_or_none()

    async def get_interactions(
        self,
        drug_a: str,
        drug_b: str,
    ) -> list[DrugInteraction]:
        """
        Return all known interactions between two drugs.

        Checks both orderings (drug_a=X & drug_b=Y) and
        (drug_a=Y & drug_b=X) so the caller doesn't need to worry
        about which name was seeded first.

        Parameters
        ----------
        drug_a      Generic name of the first drug (case-insensitive).
        drug_b      Generic name of the second drug (case-insensitive).

        Returns
        -------
        List of DrugInteraction rows.  May contain multiple rows if the
        same pair has both orderings seeded.

        Empty list means no known interaction in the database — agents
        must say "no known interaction found in our database" and NOT
        "these drugs are safe to combine" (absence of evidence ≠ safety).

        Severity handling (enforced at agent layer)
        -------------------------------------------
        contraindicated → immediate hard warning, contact doctor now
        severe          → strong advisory, contact prescribing doctor
        moderate        → inform patient, mention to their doctor
        mild            → informational, monitor for symptoms
        """
        a = drug_a.strip().lower()
        b = drug_b.strip().lower()

        result = await self._s.execute(
            select(DrugInteraction)
            .where(
                or_(
                    and_(
                        func.lower(DrugInteraction.drug_a) == a,
                        func.lower(DrugInteraction.drug_b) == b,
                    ),
                    and_(
                        func.lower(DrugInteraction.drug_a) == b,
                        func.lower(DrugInteraction.drug_b) == a,
                    ),
                )
            )
            .order_by(DrugInteraction.severity)
        )
        interactions = list(result.scalars().all())
        logging.debug(
            "get_interactions(%r, %r) → %d rows", drug_a, drug_b, len(interactions)
        )
        return interactions

    async def get_all_interactions_for_drug(
        self,
        drug_name: str,
        severity_filter: str | None = None,
    ) -> list[DrugInteraction]:
        """
        Return all known interactions involving a single drug.

        Used when a patient asks "are there any interactions I should
        know about for <drug>?" — checks both drug_a and drug_b columns.

        Parameters
        ----------
        drug_name           Generic name (case-insensitive).
        severity_filter     If provided, filter to this severity level only.
                            One of 'mild', 'moderate', 'severe', 'contraindicated'.

        Returns
        -------
        List of DrugInteraction ordered by severity (most serious first
        via ENUM ordering: contraindicated > severe > moderate > mild).
        """
        name = drug_name.strip().lower()
        filters = [
            or_(
                func.lower(DrugInteraction.drug_a) == name,
                func.lower(DrugInteraction.drug_b) == name,
            )
        ]
        if severity_filter:
            filters.append(DrugInteraction.severity == severity_filter)

        result = await self._s.execute(
            select(DrugInteraction)
            .where(*filters)
            .order_by(DrugInteraction.severity.desc())
        )
        return list(result.scalars().all())