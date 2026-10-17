# Optional container: serves the dashboard from the committed snapshot (no network needed).
#   docker build -t copenhagen-data-lab .
#   docker run --rm -p 8501:8501 copenhagen-data-lab
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml requirements.txt README.md ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard ./dashboard
COPY docs ./docs
COPY data/snapshot ./data/snapshot
COPY .streamlit ./.streamlit

# Build the warehouse at image build time so the container starts instantly.
RUN python -m copenhagen_data_lab.pipeline --source snapshot

EXPOSE 8501
CMD ["streamlit", "run", "dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
