import os
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='[%(asctime)s]: %(message)s:')

project_name = "hospital_ai_agent"

list_of_files = [
    # Root files
    "README.md",
    "docker-compose.yml",
    "docker-compose.prod.yml",
    ".env.example",
    
    # App root
    f"app/__init__.py",
    f"app/main.py",
    f"app/config.py",
    
    # API routes
    f"app/api/__init__.py",
    f"app/api/routes/__init__.py",
    f"app/api/routes/chat.py",
    f"app/api/routes/appointments.py",
    f"app/api/routes/doctors.py",
    f"app/api/routes/auth.py",
    f"app/api/routes/admin.py",
    f"app/api/dependencies.py",
    f"app/api/middleware.py",
    
    # Agents - root
    f"app/agents/__init__.py",
    f"app/agents/graph.py",
    f"app/agents/state.py",
    
    # Agents - supervisor
    f"app/agents/supervisor/__init__.py",
    f"app/agents/supervisor/agent.py",
    f"app/agents/supervisor/prompts.py",
    
    # Agents - information
    f"app/agents/information/__init__.py",
    f"app/agents/information/agent.py",
    f"app/agents/information/prompts.py",
    
    # Agents - booking
    f"app/agents/booking/__init__.py",
    f"app/agents/booking/agent.py",
    f"app/agents/booking/slot_filler.py",
    f"app/agents/booking/prompts.py",
    
    # Agents - cancellation
    f"app/agents/cancellation/__init__.py",
    f"app/agents/cancellation/agent.py",
    f"app/agents/cancellation/prompts.py",
    
    # Agents - rescheduling
    f"app/agents/rescheduling/__init__.py",
    f"app/agents/rescheduling/agent.py",
    f"app/agents/rescheduling/prompts.py",
    
    # Agents - records
    f"app/agents/records/__init__.py",
    f"app/agents/records/agent.py",
    f"app/agents/records/prompts.py",
    
    # Agents - billing
    f"app/agents/billing/__init__.py",
    f"app/agents/billing/agent.py",
    f"app/agents/billing/prompts.py",
    
    # Agents - medication
    f"app/agents/medication/__init__.py",
    f"app/agents/medication/agent.py",
    f"app/agents/medication/prompts.py",
    
    # Agents - emergency
    f"app/agents/emergency/__init__.py",
    f"app/agents/emergency/agent.py",
    f"app/agents/emergency/prompts.py",
    
    # Agents - feedback
    f"app/agents/feedback/__init__.py",
    f"app/agents/feedback/agent.py",
    f"app/agents/feedback/prompts.py",
    
    # Agents - shared
    f"app/agents/shared/__init__.py",
    f"app/agents/shared/confirmation_handler.py",
    f"app/agents/shared/fallback.py",
    f"app/agents/shared/auth_agent.py",
    
    # Tools
    f"app/tools/__init__.py",
    f"app/tools/hospital_info_tools.py",
    f"app/tools/appointment_tools.py",
    f"app/tools/patient_record_tools.py",
    f"app/tools/billing_tools.py",
    f"app/tools/medication_tools.py",
    f"app/tools/feedback_tools.py",
    f"app/tools/emergency_tools.py",
    f"app/tools/utility_tools.py",
    
    # Memory
    f"app/memory/__init__.py",
    f"app/memory/redis_history.py",
    f"app/memory/mysql_archive.py",
    f"app/memory/session_manager.py",
    f"app/memory/patient_context.py",
    
    # Database
    f"app/db/__init__.py",
    f"app/db/base.py",
    f"app/db/session.py",
    
    # Database models
    f"app/db/models/__init__.py",
    f"app/db/models/patient.py",
    f"app/db/models/doctor.py",
    f"app/db/models/appointment.py",
    f"app/db/models/medical_record.py",
    f"app/db/models/billing.py",
    f"app/db/models/medication.py",
    f"app/db/models/feedback.py",
    f"app/db/models/audit_log.py",
    f"app/db/models/memory.py",
    
    # Database repositories
    f"app/db/repositories/__init__.py",
    f"app/db/repositories/appointment_repo.py",
    f"app/db/repositories/patient_repo.py",
    f"app/db/repositories/doctor_repo.py",
    f"app/db/repositories/billing_repo.py",
    f"app/db/repositories/medication_repo.py",
    f"app/db/repositories/audit_repo.py",
    
    # RAG
    f"app/rag/__init__.py",
    f"app/rag/vector_store.py",
    f"app/rag/ingestion.py",
    f"app/rag/retriever.py",
    
    # LLM
    f"app/llm/__init__.py",
    f"app/llm/factory.py",
    f"app/llm/groq_client.py",
    f"app/llm/ollama_client.py",
    
    # Notifications
    f"app/notifications/__init__.py",
    f"app/notifications/tasks.py",
    f"app/notifications/sms.py",
    f"app/notifications/email.py",
    
    # Utils
    f"app/utils/__init__.py",
    f"app/utils/audit.py",
    f"app/utils/security.py",
    f"app/utils/datetime_utils.py",
    f"app/utils/id_generator.py",
    
    # Alembic
    f"alembic/__init__.py",
    f"alembic/env.py",
    "alembic.ini",
    
    # Data seed files
    "data/seed/hospital_info.sql",
    "data/seed/departments.sql",
    "data/seed/doctors.sql",
    "data/seed/medications.sql",
    
    # Tests - unit
    "tests/unit/test_tools.py",
    "tests/unit/test_agents.py",
    "tests/unit/test_memory.py",
    
    # Tests - integration
    "tests/integration/test_booking_flow.py",
    "tests/integration/test_cancel_flow.py",
    "tests/integration/test_emergency_flow.py",
    
    # Tests - e2e
    "tests/e2e/test_full_conversation.py",
    
    # Scripts
    "scripts/seed_db.py",
    "scripts/ingest_rag_docs.py",
    "scripts/health_check.py",
    
    # Documentation
    "docs/architecture.md",
    "docs/agent_prompts.md",
    "docs/api_reference.md",
    "docs/deployment_guide.md",
    
    # Root config files
    "requirements.txt",
    "setup.py",
    "Dockerfile",
    ".dockerignore",
    ".gitignore",
    
    # Additional configs
    "pyproject.toml",
    "Makefile",
    ".env",
]

# Create all directories and files
for filepath in list_of_files:
    filepath = Path(filepath)
    filedir, filename = os.path.split(filepath)
    
    # Create directory if it doesn't exist
    if filedir != "":
        os.makedirs(filedir, exist_ok=True)
        logging.info(f"Creating directory: {filedir} for the file: {filename}")
    
    # Create file if it doesn't exist or is empty
    if (not os.path.exists(filepath)) or (os.path.getsize(filepath) == 0):
        with open(filepath, "w") as f:
            # Add boilerplate content for __init__.py files
            if filename == "__init__.py":
                f.write("# This file makes the directory a Python package\n")
            elif filename in ["README.md", "requirements.txt", ".gitignore", "Dockerfile"]:
                # Let these stay empty for now
                pass
            else:
                # Add simple docstring for other Python files
                if filepath.suffix == ".py":
                    module_path = str(filepath).replace("/", ".").replace("\\", ".").replace(".py", "")
                    f.write(f'"""\n{module_path} module for Hospital AI Agent System\n"""\n\n')
        
        logging.info(f"Creating empty file: {filepath}")
    else:
        logging.info(f"{filename} already exists")

# Create __init__.py files for all test directories
test_init_dirs = [
    "tests/__init__.py",
    "tests/unit/__init__.py",
    "tests/integration/__init__.py",
    "tests/e2e/__init__.py",
]

for init_file in test_init_dirs:
    filepath = Path(init_file)
    if not os.path.exists(filepath):
        with open(filepath, "w") as f:
            f.write("# This file makes the directory a Python package\n")
        logging.info(f"Creating: {init_file}")

# Create empty version directory with __init__.py
alembic_versions_dir = Path("alembic/versions")
os.makedirs(alembic_versions_dir, exist_ok=True)
init_file = alembic_versions_dir / "__init__.py"
if not init_file.exists():
    with open(init_file, "w") as f:
        f.write("# Alembic migrations versions\n")
    logging.info(f"Creating: {init_file}")

logging.info("=" * 50)
logging.info(f"Project '{project_name}' structure created successfully!")
logging.info(f"Total files/directories created: {len(list_of_files)}")
logging.info("=" * 50)