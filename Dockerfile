FROM python:3.11-slim
WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx pydantic

# Copy hub files
COPY backend/ backend/
COPY index.html .

# Expose port
EXPOSE 8081

# Run FastAPI
CMD ["python", "backend/main.py"]
