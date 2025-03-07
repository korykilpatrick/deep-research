FROM python:3.12-slim

WORKDIR /app

# Copy dependency file and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy environment file if present
COPY .env.local ./

# Copy all source files
COPY . .

CMD ["python", "src/run.py"]
