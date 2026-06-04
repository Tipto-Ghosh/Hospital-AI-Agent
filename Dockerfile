FROM python:3.11-slim

# 1. Set optimized system environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WORKDIR=/app

# Set the working directory
WORKDIR ${WORKDIR}

# 2. Install native system dependencies for MySQL compiling and networking tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    pkg-config \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# 3. Upgrade pip to prevent modern build wheels from failing
RUN pip install --no-cache-dir --upgrade pip

# 4. Leverage Docker Layer Caching for dependency isolation
# If requirements.txt doesn't change, Docker skips compiling packages on subsequent builds
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy your application source code into the execution workspace
COPY . .

# Expose the API communication port
EXPOSE 8000

# 6. Default execution fallback (will be overridden by the Celery worker service automatically)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]