FROM python:3.11-slim

WORKDIR /app

# Copy dependency file and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy environment file if present
COPY .env ./

# Copy all source files
COPY ./src .

# Expose the port the app runs on
EXPOSE 8001

# Run the FastAPI application with uvicorn
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8001"]
