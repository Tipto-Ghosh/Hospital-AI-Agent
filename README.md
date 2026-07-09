# Hospital-AI-Agent

To start docker image: docker compose up -d
Run this to see the database: docker exec -it hospital_ai_db mysql -u hospital_user -phospital-ai-agent-1234 hospital_ai


For docker:
Dev(core only) `docker compose up -d`

Dev + GPU `docker compose --profile gpu up -d`

Dev + Monitoring `docker compose --profile observability up -d`

Production `docker compose -f docker-compose.yml -f docker-compose-prod.yml up -d`