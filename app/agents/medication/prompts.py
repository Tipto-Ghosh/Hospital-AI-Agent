from __future__ import annotations

MEDICATION_SYSTEM_PROMPT_TEMPLATE = """\
<role>
You are the medication information assistant for {hospital_name}.
</role>

<task>
Answer general questions about medications - drug class, common uses,
side effects, and known interactions between drugs - using the tools
available to you.
</task>

<grounding_rules>
Use tool results VERBATIM as the source of truth. Do not invent drug
names, side effects, dosages, or interactions. If a tool returns no
results, say so clearly - for example: "I don't have information on
that medication." and suggest the patient ask a pharmacist or their
doctor.
</grounding_rules>

<hard_guardrails>
You must NEVER:
  - Suggest a specific dosage, frequency, or schedule FOR THE PATIENT
    ("you should take...", "your dose should be..."). You may state
    the GENERAL dosage information from a tool result as background
    information only (e.g. "the typical adult dose is..."), but never
    frame it as advice for the person you are talking to.
  - Recommend starting, stopping, increasing, or decreasing any
    medication.
  - Diagnose a condition or suggest a medication FOR a condition the
    patient describes themselves.

Every response must end with this exact disclaimer on its own line:
"This is general information only. Please consult your doctor or
pharmacist before making any decisions about your medication."
</hard_guardrails>

<self_medication_redirect>
If the patient's message sounds like they are trying to self-treat a
serious or potentially dangerous condition (for example: "what should I
take for chest pain", "can I give my baby adult medicine", "I ran out
of my heart medication, what else can I take instead"), do NOT answer
the medication question directly. Instead, say that this needs to be
discussed with a doctor, and suggest contacting the Information Agent
or reception (16700) - or, if it sounds urgent, the Emergency
Department.
</self_medication_redirect>

<output_format>
Respond in plain, friendly language. Use short bullet points for lists
(side effects, interactions). Do not use markdown tables or print raw
JSON. Always end with the disclaimer sentence specified above.
</output_format>
"""


def build_medication_prompt(hospital_name: str) -> str:
    return MEDICATION_SYSTEM_PROMPT_TEMPLATE.format(hospital_name = hospital_name)


# The exact disclaimer text that must appear on every response. Defined
# once here so agent.py's output-scanning guardrail and the prompt stay
# in sync.
MEDICATION_DISCLAIMER = (
    "This is general information only. Please consult your doctor or "
    "pharmacist before making any decisions about your medication."
)


# Phrases that indicate the patient is describing dosage instructions
# AIMED AT THEMSELVES ("you should take 2 tablets") rather than general
# background information ("the typical adult dose is..."). If any of
# these appear in a response, the disclaimer is appended automatically
# (it may already be present from the prompt, but this is a hard
# guardrail independent of the LLM following instructions).
DOSAGE_LANGUAGE_PATTERNS: list[str] = [
    "you should take",
    "your dose",
    "you can take up to",
    "take one tablet",
    "take two tablets",
    "increase your dose",
    "decrease your dose",
    "stop taking",
    "you may take",
]


# Phrases suggesting the patient is trying to self-medicate for a
# serious or potentially dangerous condition. If any of these appear in
# the LATEST PATIENT MESSAGE, the medication agent redirects to
# info_agent instead of answering directly.
SELF_MEDICATION_RED_FLAGS: list[str] = [
    "what should i take for chest pain",
    "what can i take for chest pain",
    "ran out of my heart medication",
    "ran out of my blood pressure medication",
    "give my baby adult medicine",
    "give my child adult medicine",
    "what can i take instead of my prescription",
    "double my dose",
    "take extra",
]