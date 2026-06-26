from __future__ import annotations

EMERGENCY_SYSTEM_PROMPT_TEMPLATE = """\
<role>
You are the Emergency Triage assistant for {hospital_name}. You are
speaking to someone who may be in a life-threatening situation, or who
is helping someone who is.
</role>

<tone>
Be calm, direct, and action-first. Use short sentences. Do not use
medical jargon. Do not hedge or apologize. Every second matters.
</tone>

<mandatory_first_sentence>
Your very first sentence MUST contain the emergency contact numbers
provided to you below, exactly as given. Do this before anything else
- before any acknowledgement, before any first-aid guidance.
</mandatory_first_sentence>

<emergency_contacts>
{emergency_contacts}
</emergency_contacts>

<first_aid_guidance>
The following first-aid steps have been pre-approved for the
situation(s) detected in the patient's message. Use ONLY this guidance
- do not add, modify, or invent any additional medical steps.

{first_aid_guidance}
</first_aid_guidance>

<strict_rules>
You must NEVER:
  - Offer a diagnosis or guess what condition the person has.
  - Tell the person to "wait and see" or downplay the situation.
  - Recommend any medication, dosage, or home remedy not listed above.
  - Suggest the AI assistant can help further with this situation -
    direct them to call the numbers above or go to the Emergency
    entrance immediately.

If no first-aid guidance was provided above for this situation, do not
invent any. Simply restate the emergency numbers and tell the person to
call now or go to the Emergency entrance (Ground Floor, Block A)
immediately.
</strict_rules>

<output_format>
Respond in plain, warm, direct language. 3-5 short sentences maximum.
No markdown, no lists unless the first-aid guidance itself is a list of
steps - in that case, present those steps as a simple numbered list.
</output_format>
"""

def build_emergency_prompt(hospital_name: str, emergency_contacts: str, first_aid_guidance: str) -> str:
    """
    Render the Emergency Triage system prompt.
    
    Returns
    -------
    The fully rendered system prompt string.
    """
    return EMERGENCY_SYSTEM_PROMPT_TEMPLATE.format(
        hospital_name=hospital_name,
        emergency_contacts=emergency_contacts,
        first_aid_guidance=first_aid_guidance,
    )


FALLBACK_EMERGENCY_CONTACTS = (
    "Hospital Emergency Hotline (24/7): 109\n"
    "Ambulance Dispatch: 01711-AMBU (01711-2628)\n"
    "National Emergency: 999"
)

FIRST_AID_GUIDANCE: dict[str, str] = {
    "chest pain": (
        "1. Help the person sit down and rest in a comfortable position.\n"
        "2. Loosen any tight clothing.\n"
        "3. If they have prescribed heart medication (such as aspirin or "
        "nitroglycerin) and are not allergic, help them take it as "
        "prescribed.\n"
        "4. Stay with them and keep them calm until help arrives.\n"
        "5. Do not let them walk around or drive."
    ),
    "heart attack": (
        "1. Help the person sit down and rest in a comfortable position.\n"
        "2. Loosen any tight clothing.\n"
        "3. If they have prescribed heart medication (such as aspirin or "
        "nitroglycerin) and are not allergic, help them take it as "
        "prescribed.\n"
        "4. Stay with them and keep them calm until help arrives.\n"
        "5. Do not let them walk around or drive."
    ),
    "can't breathe": (
        "1. Help the person sit upright - do not lay them down.\n"
        "2. Loosen tight clothing around the neck and chest.\n"
        "3. If they have a prescribed inhaler, help them use it.\n"
        "4. Keep the area calm and well-ventilated.\n"
        "5. Stay with them until help arrives."
    ),
    "cannot breathe": (
        "1. Help the person sit upright - do not lay them down.\n"
        "2. Loosen tight clothing around the neck and chest.\n"
        "3. If they have a prescribed inhaler, help them use it.\n"
        "4. Keep the area calm and well-ventilated.\n"
        "5. Stay with them until help arrives."
    ),
    "severe bleeding": (
        "1. Apply firm, direct pressure to the wound with a clean cloth "
        "or bandage.\n"
        "2. Do not remove the cloth if it becomes soaked - add more on "
        "top.\n"
        "3. If possible, raise the injured area above the level of the "
        "heart.\n"
        "4. Keep the person lying down and warm.\n"
        "5. Maintain pressure until help arrives."
    ),
    "unconscious": (
        "1. Check if the person is breathing.\n"
        "2. If they are breathing, place them on their side in the "
        "recovery position.\n"
        "3. If they are NOT breathing, begin CPR if you are trained, "
        "and continue until help arrives.\n"
        "4. Do not give them anything to eat or drink.\n"
        "5. Stay with them and keep them warm."
    ),
    "not responding": (
        "1. Check if the person is breathing.\n"
        "2. If they are breathing, place them on their side in the "
        "recovery position.\n"
        "3. If they are NOT breathing, begin CPR if you are trained, "
        "and continue until help arrives.\n"
        "4. Do not give them anything to eat or drink.\n"
        "5. Stay with them and keep them warm."
    ),
    "seizure": (
        "1. Clear the area around the person of anything that could "
        "hurt them.\n"
        "2. Do not hold them down or put anything in their mouth.\n"
        "3. Time the seizure if you can.\n"
        "4. Once it stops, place them on their side and stay with "
        "them until they are fully alert.\n"
        "5. If the seizure lasts more than 5 minutes, call emergency "
        "services immediately."
    ),
    "stroke": (
        "1. Note the time symptoms started - this is critical "
        "information for the medical team.\n"
        "2. Keep the person still and comfortable.\n"
        "3. Do not give them anything to eat or drink.\n"
        "4. If they are conscious, reassure them and stay with them.\n"
        "5. Call for emergency transport immediately - do not attempt "
        "to drive them yourself if an ambulance is available."
    ),
    "overdose": (
        "1. If the person is unconscious, place them in the recovery "
        "position on their side.\n"
        "2. Do not try to make them vomit.\n"
        "3. If you know what was taken, keep the container or packaging "
        "to show medical staff.\n"
        "4. Stay with them and monitor their breathing until help "
        "arrives."
    ),
}


def get_first_aid_guidance_for_text(text: str) -> str:
    """
    Return a formatted block of curated first-aid guidance for any
    FIRST_AID_GUIDANCE-style phrases found in `text`.

    Parameters
    ----------
    text    The patient's message (case-insensitive matching).

    Returns
    -------
    A formatted string containing one or more matching guidance
    sections, or a safe fallback string if nothing in
    FIRST_AID_GUIDANCE matched.
    """
    lowered = text.lower()
    matched_sections: list[str] = []

    for keyword, guidance in FIRST_AID_GUIDANCE.items():
        if keyword in lowered:
            matched_sections.append(f"For '{keyword}':\n{guidance}")

    if not matched_sections:
        return (
            "No specific pre-approved guidance matched this situation. "
            "Do not provide first-aid steps - direct the person to call "
            "emergency services or go to the Emergency entrance "
            "immediately."
        )

    return "\n\n".join(matched_sections)