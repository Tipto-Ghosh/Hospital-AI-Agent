import os 
from dotenv import load_dotenv
load_dotenv()
from celery import Celery

from app.logger import logging
from app.config import get_settings
from app.notifications import email, sms

logger = logging.getLogger(__name__)
settings = get_settings()


celery_app = Celery(
    "hospital_ai_notifications",
    broker = settings.redis.CELERY_BROKER_URL,
    backend = os.environ.get("CELERY_RESULT_BACKEND", settings.redis.CELERY_BROKER_URL),
)

celery_app.conf.update(
    task_serializer = "json",
    result_serializer = "json",
    accept_content = ["json"],
    timezone = "UTC",
    enable_utc = True,
    task_acks_late = True,
    worker_prefetch_multiplier = 1,
)

@celery_app.task(bind = True, max_retries = 3, default_retry_delay = 30)
def send_appointment_confirmation(self, patient_phone: str, appointment_details: str) -> bool:
    """ 
    Send an appointment confirmation SMS to the patient.
    
    Called immediately after a successful create_appointment() write in action_executer_node.
    Runs in the background via Celery so the patient-facing response is not blocked
    on delivery.
    
    Retries up to 3 times on failure, with a 30-second delay between attempts.
    """
    
    # appointment details
    doctor_name = appointment_details.get("doctor_name", "your doctor")
    scheduled_at = appointment_details.get("scheduled_at", "the scheduled time")
    appointment_id = appointment_details.get("appointment_id", "")
    message = (
        f"Your appointment with {doctor_name} is confirmed for {scheduled_at}. ",
        f"Appointment ID: {appointment_id}. Please arrive 10 minutes early.",
        f"{os.getenv("HOSPITAL_NAME", "City General Hospital")}."
    )
    
    try:
        # Send the SMS
        success = sms.send(phone = patient_phone, message = message)
        if not success:
            raise Exception("SMS delivery failed.")
        logger.info(f"Appointment confirmation SMS sent to {patient_phone}.")
        return True
    except Exception as e:
        logger.error(f"Failed to send appointment confirmation SMS to {patient_phone}: {e}")
        
        # Retry the task if it fails
        raise self.retry(exc = e, countdown = 30 * (2 ** self.request.retries))


@celery_app.task(bind = True, max_retries = 3, default_retry_delay = 30)
def send_cancellation_notice(self, patient_contact: str, appointment_details: dict) -> bool:
    """
    Send a cancellation confirmation SMS to the patient.
 
    Called by action_executor_node after a successful cancel_appointment
    write. `patient_contact` may be a phone number or email address -
    this task treats it as a phone number; for email delivery a separate
    task (send_receipt_email) is the right choice.
 
    Parameters
    ----------
    patient_contact: Phone number or contact info on file.
    appointment_details: Dict with at minimum: appointment_id, doctor_name, scheduled_at (ISO string).
 
    Retry policy
    ------------
    Up to 3 retries with exponential backoff.
    """
    doctor_name = appointment_details.get("doctor_name", "your doctor")
    scheduled_at = appointment_details.get("scheduled_at", "the scheduled time")
    appointment_id = appointment_details.get("appointment_id", "")
 
    message = (
        f"Your appointment with {doctor_name} scheduled for {scheduled_at} "
        f"(ID: {appointment_id}) has been cancelled. "
        f"City General Hospital."
    )
 
    try:
        success = sms.send(phone=patient_contact, message=message)
        if not success:
            raise RuntimeError("sms.send() returned False")
        logger.info(
            f"send_cancellation_notice: delivered for appointment_id={appointment_id}"
        )
        return True
    except Exception as exc:
        logger.warning(
            f"send_cancellation_notice: attempt {self.request.retries + 1}/4 "
            f"failed for appointment_id={appointment_id}: {exc}"
        )
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))

@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def send_otp_sms(self, phone: str, otp: str) -> bool:
    """
    Deliver a 6-digit OTP to the patient's phone via SMS.
 
    Called by auth_agent_node (app/agents/shared/auth_agent.py) during
    the two-stage identity verification flow. The OTP is stored in Redis under "otp:{patient_id}" with a 5-minute TTL
    before this task is queued, this task's job is delivery only.
 
    The message body is intentionally minimal and does not name the
    hospital system or embed a link, following standard OTP SMS
    security guidance (avoids phishing lookalike messages).
 
    Parameters
    ----------
    phone   Full phone number, e.g. "01987654321".
    otp     6-digit code, zero-padded (e.g. "042817").
 
    Retry policy
    ------------
    Up to 3 retries with exponential backoff starting at 10 s (10 s,
    20 s, 40 s). The shorter base delay is intentional - OTP delivery
    is time-sensitive (5-minute Redis TTL), so retries happen faster
    than for other notification types.
    """
    message = f"Your verification code is {otp}. Valid for 5 minutes. Do not share this code."
 
    try:
        success = sms.send(phone=phone, message=message)
        if not success:
            raise RuntimeError("sms.send() returned False")
        logger.info(f"send_otp_sms: OTP delivered to phone ending in {phone[-4:]}")
        return True
    except Exception as exc:
        logger.warning(
            f"send_otp_sms: attempt {self.request.retries + 1}/4 "
            f"failed for phone ending in {phone[-4:]}: {exc}"
        )
        raise self.retry(exc=exc, countdown=10 * (2 ** self.request.retries))

@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_receipt_email(self, patient_email: str, invoice_id: str) -> bool:
    """
    Email a billing receipt to the patient.
 
    Called by the billing agent's request_receipt tool after the
    patient requests a copy of their invoice. Does not attach the full
    invoice PDF (that would require fetching binary data from the DB
    inside the task) — the email body contains the invoice ID and
    directs the patient to the online payment portal or billing desk
    for a full itemized copy.
 
    Parameters
    ----------
    patient_email   Patient's email address on file.
    invoice_id      Invoice PK, e.g. "INV-20241101-0001".
 
    Retry policy
    ------------
    Up to 3 retries with exponential backoff (30 s, 60 s, 120 s).
    """
    subject = f"City General Hospital — Receipt for Invoice {invoice_id}"
    body = (
        f"Dear Patient,\n\n"
        f"This is a confirmation that your receipt for invoice {invoice_id} "
        f"has been processed.\n\n"
        f"To view or download a full itemized copy, please visit our billing "
        f"portal at pay.cityhospital.com or contact the Billing Desk at "
        f"Ground Floor, Block A, Ext. 104.\n\n"
        f"City General Hospital\n"
    )
 
    try:
        success = email.send(
            to_address=patient_email,
            subject=subject,
            body_text=body,
        )
        if not success:
            raise RuntimeError("email.send() returned False")
        logger.info(f"send_receipt_email: delivered to {patient_email} for invoice_id={invoice_id}")
        return True
    except Exception as exc:
        logger.warning(
            f"send_receipt_email: attempt {self.request.retries + 1}/4 "
            f"failed for {patient_email} invoice_id={invoice_id}: {exc}"
        )
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))