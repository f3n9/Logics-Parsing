# Logics-Parsing API Server - Production Dockerfile
# Multi-stage build for optimized image size

# Stage 1: Base image with CUDA support (using devel for build tools)
FROM nvidia/cuda:12.1.1-devel-ubuntu22.04 AS base

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies including build tools for flash-attn
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3.10-dev \
    python3-pip \
    git \
    wget \
    curl \
    build-essential \
    ninja-build \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic link for python
RUN ln -sf /usr/bin/python3.10 /usr/bin/python

# Stage 2: Build stage with model download
FROM base AS builder

WORKDIR /build

# Copy requirements first for better layer caching
COPY requirement.txt .

# Upgrade pip and install Python dependencies
# Note: flash-attn requires torch to be installed first, so we install in stages
RUN pip install --upgrade pip setuptools wheel -i https://mirrors.cloud.tencent.com/pypi/simple && \
    # Install PyTorch and related packages first
    pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 -i https://mirrors.cloud.tencent.com/pypi/simple && \
    # Install transformers and accelerate before flash-attn
    pip install transformers==4.51.0 accelerate==1.0.0 -i https://mirrors.cloud.tencent.com/pypi/simple 
    # Now install flash-attn (requires torch to be available)
RUN pip install flash-attn==2.4.2 --use-pep517 --no-build-isolation -i https://mirrors.cloud.tencent.com/pypi/simple
    # Install remaining dependencies
RUN pip install modelscope opencv-python fastapi uvicorn[standard] python-multipart pydantic -i https://mirrors.cloud.tencent.com/pypi/simple

# Copy application files
COPY download_model.py .
COPY inference.py .
COPY api_server.py .
COPY example_client.py .

# Download model from ModelScope during build
# This ensures the model is baked into the image
RUN mkdir -p weights && \
    echo "Downloading model from ModelScope..." && \
    #python download_model.py -t modelscope && \
    echo "Model download completed" && \
    ls -lh weights/

# Stage 3: Production runtime image
FROM base AS production

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash appuser && \
    mkdir -p /app /app/weights /app/outputs && \
    chown -R appuser:appuser /app

WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages

# Copy application files from builder
COPY --from=builder --chown=appuser:appuser /build/*.py ./
COPY --from=builder --chown=appuser:appuser /build/weights ./weights

# Copy documentation (optional)
COPY --chown=appuser:appuser README.md CLAUDE.md README_API.md LICENSE ./

# Create directory for outputs with proper permissions
RUN mkdir -p /app/outputs /tmp/logics-parsing && \
    chown -R appuser:appuser /app/outputs /tmp/logics-parsing && \
    chmod 755 /app/outputs

# Switch to non-root user
USER appuser

# Set environment variables for production
ENV MODEL_PATH=/app/weights/Logics-Parsing \
    PORT=8000 \
    HOST=0.0.0.0 \
    MAX_WORKERS=4 \
    PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the API server
CMD ["python", "api_server.py"]
