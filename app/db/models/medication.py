"""
ORM models for static reference / lookup tables.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import TEXT,DateTime,Enum,Boolean,Integer,String,event,func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.logger import logging
from app.exception import CustomException

# Severity levels for drug interactions — ordered from least to most serious
INTERACTION_SEVERITIES = ("mild", "moderate", "severe", "contraindicated")

# HospitalInfo categories — constrains what the Information Agent can query
HOSPITAL_INFO_CATEGORIES = ("hours", "location", "policy", "service", "contact", "faq")


class Medication(Base):
    """
    Maps to the `medications` table.

    Reference record for a drug — not tied to any patient.
    Contains general pharmacological information only.

    Fields intentionally excluded from LLM responses
    -------------------------------------------------
    - general_dosage: agents must never quote specific dosage to a patient.
      They may say "dosage varies — consult your prescribing doctor."
    - contraindications: agents flag the existence of contraindications
      and direct the patient to their doctor; they do not enumerate them.

    requires_prescription flag
    --------------------------
    If True, the agent must not provide detailed usage guidance and must
    direct the patient to get a valid prescription from a licensed doctor.
    """

    __tablename__ = "medications"

    medication_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    # Core identity
    generic_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
        comment="INN / generic drug name, e.g. 'metformin'.",
    )
    brand_names: Mapped[Optional[str]] = mapped_column(
        TEXT,
        nullable=True,
        comment="Comma-separated brand names, e.g. 'Glucophage, Fortamet'.",
    )

    # Classification
    drug_class: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Pharmacological class, e.g. 'biguanide antidiabetic'.",
    )

    # General information
    common_uses: Mapped[Optional[str]] = mapped_column(
        TEXT,
        nullable=True,
        comment="General therapeutic indications. Never patient-specific.",
    )
    side_effects: Mapped[Optional[str]] = mapped_column(
        TEXT,
        nullable=True,
        comment="Common and notable side effects. Always mention 'consult doctor'.",
    )
    contraindications: Mapped[Optional[str]] = mapped_column(
        TEXT,
        nullable=True,
        comment=(
            "Known contraindications. "
            "Agent must flag existence and direct patient to their doctor — "
            "never enumerate the full list to the patient."
        ),
    )
    general_dosage: Mapped[Optional[str]] = mapped_column(
        TEXT,
        nullable=True,
        comment=(
            "General population dosage range for reference ONLY. "
            "Agent must NEVER quote this directly — always say "
            "'dosage is determined by your doctor'."
        ),
    )

    # Prescription requirement 
    requires_prescription: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment=(
            "If True, agent must not provide detailed guidance and must "
            "direct patient to obtain a prescription."
        ),
    )

    def __repr__(self) -> str:
        rx_flag = "Rx" if self.requires_prescription else "OTC"
        return (
            f"<Medication id={self.medication_id} "
            f"name={self.generic_name!r} class={self.drug_class!r} [{rx_flag}]>"
        )

# DrugInteraction
class DrugInteraction(Base):
    """
    Maps to the `drug_interactions` table.

    Each row records a known interaction between two drugs (drug_a, drug_b).
    The pair is unordered in practice — the tool layer queries for both
    (drug_a=X, drug_b=Y) and (drug_a=Y, drug_b=X) to catch all combinations,
    or seeds both orderings at load time.

    Severity levels
    ---------------
    mild            — minor interaction, generally safe with monitoring
    moderate        — significant interaction, may require dose adjustment
    severe          — serious interaction, alternative drug recommended
    contraindicated — must NOT be co-administered under any circumstances

    Agent behaviour rules by severity
    ----------------------------------
    mild/moderate   → inform patient, recommend mentioning to their doctor
    severe          → strong advisory to contact their prescribing doctor
                       before continuing both medications
    contraindicated → immediate hard warning: "Do not take these together.
                       Contact your doctor immediately."
                       Always route to Information Agent for emergency contact
                       if patient indicates they have already taken both.
    """

    __tablename__ = "drug_interactions"

    interaction_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    # Drug pair 
    drug_a: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Generic name of the first drug in the interaction pair.",
    )
    drug_b: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Generic name of the second drug in the interaction pair.",
    )

    # Severity
    severity: Mapped[str] = mapped_column(
        Enum(*INTERACTION_SEVERITIES, name="interaction_severity_enum"),
        nullable=False,
        index=True,
        comment="Clinical severity of the interaction.",
    )

    # Clinical description
    description: Mapped[str] = mapped_column(
        TEXT,
        nullable=False,
        comment=(
            "Plain-language description of the interaction mechanism and risk. "
            "The agent surfaces a simplified version of this — never the raw text."
        ),
    )

    @property
    def is_contraindicated(self) -> bool:
        """Convenience property — True if this interaction is absolutely forbidden."""
        return self.severity == "contraindicated"

    @property
    def requires_immediate_advisory(self) -> bool:
        """True if agent must issue a strong warning (severe or contraindicated)."""
        return self.severity in ("severe", "contraindicated")

    def __repr__(self) -> str:
        return (
            f"<DrugInteraction id={self.interaction_id} "
            f"{self.drug_a!r} ✕ {self.drug_b!r} [{self.severity}]>"
        )

# HospitalInfo
class HospitalInfo(Base):
    """
    Maps to the `hospital_info` table.

    Static lookup table for all public-facing hospital information.
    The Information Agent reads from this table — it must NEVER answer
    questions about hospital policy, hours, or services from LLM training
    data. Every factual claim must be backed by a row in this table or
    retrieved via ChromaDB RAG (which is also seeded from this table).

    Categories
    ----------
    hours    — opening times, visiting hours, emergency hours
    location — building directions, floor maps, department locations
    policy   — visitor policy, payment policy, cancellation policy
    service  — available medical services and procedures
    contact  — phone numbers, email addresses, department extensions
    faq      — frequently asked patient questions

    ChromaDB ingestion
    ------------------
    The scripts/ingest_rag_docs.py script reads all rows from this table
    and loads them into ChromaDB.  The content field is embedded using
    nomic-embed-text / all-MiniLM-L6-v2.  Queries that don't exactly
    match a SQL lookup fall through to the RAG retriever.

    last_updated
    ------------
    Automatically set by the DB server on every UPDATE.  The admin API
    uses this to show hospital staff when a piece of information was
    last reviewed — important for keeping patient-facing info accurate.
    """

    __tablename__ = "hospital_info"

    info_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    # Category & topic 
    category: Mapped[str] = mapped_column(
        Enum(*HOSPITAL_INFO_CATEGORIES, name="hospital_info_category_enum"),
        nullable=False,
        index=True,
        comment="Broad category — used for agent tool routing.",
    )
    topic: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment=(
            "Specific topic within the category, e.g. 'ICU visiting hours', "
            "'radiology location', 'accepted insurance plans'."
        ),
    )

    # Content
    content: Mapped[str] = mapped_column(
        TEXT,
        nullable=False,
        comment=(
            "The full information text shown (in summarised form) to the patient. "
            "Also embedded into ChromaDB for semantic search."
        ),
    )

    # Freshness tracking
    last_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Auto-updated by the DB on every change. Used to flag stale content.",
    )

    def __repr__(self) -> str:
        return (
            f"<HospitalInfo id={self.info_id} "
            f"category={self.category!r} topic={self.topic!r}>"
        )


# Lifecycle event listeners — log reference data changes & catch errors

# Medication listeners
@event.listens_for(Medication, "after_insert")
def _log_medication_insert(mapper, connection, target: Medication) -> None:
    try:
        logging.info(
            "Medication created: id=%d, name=%s, class=%s, rx=%s",
            target.medication_id,
            target.generic_name,
            target.drug_class,
            target.requires_prescription,
        )
    except Exception as exc:
        logging.exception("Logging failure during Medication insert event.")
        raise CustomException(
            error_message="Failed to process Medication insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Medication, "after_update")
def _log_medication_update(mapper, connection, target: Medication) -> None:
    try:
        logging.info(
            "Medication updated: id=%d, name=%s, class=%s, rx=%s",
            target.medication_id,
            target.generic_name,
            target.drug_class,
            target.requires_prescription,
        )
    except Exception as exc:
        logging.exception("Logging failure during Medication update event.")
        raise CustomException(
            error_message="Failed to process Medication update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(Medication, "after_delete")
def _log_medication_delete(mapper, connection, target: Medication) -> None:
    try:
        logging.info(
            "Medication deleted: id=%d, name=%s",
            target.medication_id,
            target.generic_name,
        )
    except Exception as exc:
        logging.exception("Logging failure during Medication delete event.")
        raise CustomException(
            error_message="Failed to process Medication delete event.",
            error_detail=str(exc),
        ) from exc


# DrugInteraction listeners 
@event.listens_for(DrugInteraction, "after_insert")
def _log_drug_interaction_insert(mapper, connection, target: DrugInteraction) -> None:
    try:
        logging.info(
            "DrugInteraction created: id=%d, drugs=%sx%s, severity=%s",
            target.interaction_id,
            target.drug_a,
            target.drug_b,
            target.severity,
        )
    except Exception as exc:
        logging.exception("Logging failure during DrugInteraction insert event.")
        raise CustomException(
            error_message="Failed to process DrugInteraction insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(DrugInteraction, "after_update")
def _log_drug_interaction_update(mapper, connection, target: DrugInteraction) -> None:
    try:
        logging.info(
            "DrugInteraction updated: id=%d, drugs=%sx%s, severity=%s",
            target.interaction_id,
            target.drug_a,
            target.drug_b,
            target.severity,
        )
    except Exception as exc:
        logging.exception("Logging failure during DrugInteraction update event.")
        raise CustomException(
            error_message="Failed to process DrugInteraction update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(DrugInteraction, "after_delete")
def _log_drug_interaction_delete(mapper, connection, target: DrugInteraction) -> None:
    try:
        logging.info(
            "DrugInteraction deleted: id=%d, drugs=%sx%s",
            target.interaction_id,
            target.drug_a,
            target.drug_b,
        )
    except Exception as exc:
        logging.exception("Logging failure during DrugInteraction delete event.")
        raise CustomException(
            error_message="Failed to process DrugInteraction delete event.",
            error_detail=str(exc),
        ) from exc


# HospitalInfo listeners
@event.listens_for(HospitalInfo, "after_insert")
def _log_hospital_info_insert(mapper, connection, target: HospitalInfo) -> None:
    try:
        logging.info(
            "HospitalInfo created: id=%d, category=%s, topic=%s",
            target.info_id,
            target.category,
            target.topic,
        )
    except Exception as exc:
        logging.exception("Logging failure during HospitalInfo insert event.")
        raise CustomException(
            error_message="Failed to process HospitalInfo insert event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(HospitalInfo, "after_update")
def _log_hospital_info_update(mapper, connection, target: HospitalInfo) -> None:
    try:
        logging.info(
            "HospitalInfo updated: id=%d, category=%s, topic=%s",
            target.info_id,
            target.category,
            target.topic,
        )
    except Exception as exc:
        logging.exception("Logging failure during HospitalInfo update event.")
        raise CustomException(
            error_message="Failed to process HospitalInfo update event.",
            error_detail=str(exc),
        ) from exc


@event.listens_for(HospitalInfo, "after_delete")
def _log_hospital_info_delete(mapper, connection, target: HospitalInfo) -> None:
    try:
        logging.info(
            "HospitalInfo deleted: id=%d, category=%s, topic=%s",
            target.info_id,
            target.category,
            target.topic,
        )
    except Exception as exc:
        logging.exception("Logging failure during HospitalInfo delete event.")
        raise CustomException(
            error_message="Failed to process HospitalInfo delete event.",
            error_detail=str(exc),
        ) from exc