# Docker Deployment Guide for Logics-Parsing API

This guide explains how to build and deploy the Logics-Parsing API using Docker.

## Prerequisites

1. **Docker**: Version 20.10 or later
   ```bash
   docker --version
   ```

2. **NVIDIA Container Toolkit** (for GPU support):
   ```bash
   # Install nvidia-docker2
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
   curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

   sudo apt-get update
   sudo apt-get install -y nvidia-docker2
   sudo systemctl restart docker

   # Test GPU access
   docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
   ```

3. **Disk Space**: ~20GB free space for the model and image

## Quick Start

### Option 1: Using Docker Compose (Recommended)

```bash
# Build and start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Check health
curl http://localhost:8000/health

# Stop the service
docker-compose down
```

### Option 2: Using Docker CLI

```bash
# Build the image
docker build -t logics-parsing-api:latest .

# Run the container
docker run -d \
  --name logics-parsing-api \
  --gpus all \
  -p 8000:8000 \
  -e MAX_WORKERS=4 \
  -v $(pwd)/outputs:/app/outputs \
  --restart unless-stopped \
  logics-parsing-api:latest

# View logs
docker logs -f logics-parsing-api

# Stop and remove
docker stop logics-parsing-api
docker rm logics-parsing-api
```

## Build Process

The Dockerfile uses a multi-stage build process:

### Stage 1: Base Image
- Uses NVIDIA CUDA 12.1.0 runtime on Ubuntu 22.04
- Installs system dependencies (Python, OpenCV libraries, etc.)

### Stage 2: Builder Stage
- Downloads model from ModelScope during build
- Installs Python dependencies
- Model is baked into the Docker image (~10GB)

### Stage 3: Production Image
- Copies dependencies and model from builder
- Runs as non-root user (`appuser`) for security
- Minimal attack surface

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_PATH` | `/app/weights/Logics-Parsing` | Path to model weights |
| `PORT` | `8000` | Server port |
| `HOST` | `0.0.0.0` | Server host |
| `MAX_WORKERS` | `4` | Number of worker threads |

### Customizing Configuration

**Via docker-compose.yml:**
```yaml
environment:
  - MAX_WORKERS=8  # Increase for more concurrency
  - PORT=9000      # Change port
```

**Via Docker CLI:**
```bash
docker run -d \
  --gpus all \
  -p 9000:9000 \
  -e PORT=9000 \
  -e MAX_WORKERS=8 \
  logics-parsing-api:latest
```

## Build Options

### Build with Custom Model Source

By default, the model is downloaded from ModelScope. To use HuggingFace instead:

```dockerfile
# Modify Dockerfile line 49:
RUN python download_model.py -t huggingface
```

### Build for Different CUDA Versions

```dockerfile
# Change base image (line 6):
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04 AS base
```

### Build Without Model (Smaller Image)

If you want to mount the model externally:

```bash
# Build without downloading model
docker build --target base -t logics-parsing-api:no-model .

# Run with external model mount
docker run -d \
  --gpus all \
  -p 8000:8000 \
  -v $(pwd)/weights:/app/weights \
  logics-parsing-api:no-model
```

## Production Deployment

### 1. Build Production Image

```bash
# Build with optimizations
docker build \
  --target production \
  --tag logics-parsing-api:v1.0.0 \
  --tag logics-parsing-api:latest \
  .
```

### 2. Push to Registry

```bash
# Tag for your registry
docker tag logics-parsing-api:v1.0.0 your-registry.com/logics-parsing-api:v1.0.0

# Push to registry
docker push your-registry.com/logics-parsing-api:v1.0.0
```

### 3. Deploy on Server

```bash
# Pull from registry
docker pull your-registry.com/logics-parsing-api:v1.0.0

# Run in production
docker run -d \
  --name logics-parsing-api \
  --gpus all \
  -p 8000:8000 \
  -e MAX_WORKERS=8 \
  -v /data/outputs:/app/outputs \
  --restart always \
  --memory="16g" \
  --cpus="8" \
  your-registry.com/logics-parsing-api:v1.0.0
```

### 4. Behind Nginx Reverse Proxy

**nginx.conf:**
```nginx
upstream logics_parsing {
    server localhost:8000;
}

server {
    listen 80;
    server_name api.yourdomain.com;

    client_max_body_size 50M;

    location / {
        proxy_pass http://logics_parsing;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    location /health {
        proxy_pass http://logics_parsing/health;
        access_log off;
    }
}
```

## Monitoring and Maintenance

### View Logs

```bash
# Real-time logs
docker logs -f logics-parsing-api

# Last 100 lines
docker logs --tail 100 logics-parsing-api

# With timestamps
docker logs -t logics-parsing-api
```

### Health Checks

```bash
# Check container health
docker ps --filter name=logics-parsing-api

# Check API health
curl http://localhost:8000/health

# Detailed health with jq
curl -s http://localhost:8000/health | jq
```

### Resource Monitoring

```bash
# Monitor resource usage
docker stats logics-parsing-api

# Check GPU usage
nvidia-smi

# Inside container GPU usage
docker exec logics-parsing-api nvidia-smi
```

### Update Deployment

```bash
# Pull new version
docker pull your-registry.com/logics-parsing-api:v1.1.0

# Stop old container
docker stop logics-parsing-api
docker rm logics-parsing-api

# Start new container
docker run -d \
  --name logics-parsing-api \
  --gpus all \
  -p 8000:8000 \
  -v /data/outputs:/app/outputs \
  --restart always \
  your-registry.com/logics-parsing-api:v1.1.0
```

## Troubleshooting

### GPU Not Detected

```bash
# Check NVIDIA runtime
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi

# Verify Docker daemon configuration
cat /etc/docker/daemon.json
# Should contain:
# {
#   "runtimes": {
#     "nvidia": {
#       "path": "nvidia-container-runtime",
#       "runtimeArgs": []
#     }
#   }
# }
```

### Model Not Loading

```bash
# Check if model exists in container
docker exec logics-parsing-api ls -lh /app/weights/Logics-Parsing/

# Check model download logs
docker logs logics-parsing-api | grep -i "model"

# Verify MODEL_PATH environment variable
docker exec logics-parsing-api env | grep MODEL_PATH
```

### Out of Memory Errors

```bash
# Reduce worker count
docker run -d --gpus all -e MAX_WORKERS=2 ...

# Increase container memory limit
docker run -d --gpus all --memory="24g" ...

# Check GPU memory
docker exec logics-parsing-api nvidia-smi
```

### Port Already in Use

```bash
# Find process using port 8000
sudo lsof -i :8000

# Use different port
docker run -d --gpus all -p 9000:8000 ...
```

### Build Fails During Model Download

```bash
# Check network connectivity
docker run --rm ubuntu:22.04 ping -c 4 modelscope.cn

# Use build cache to resume
docker build --cache-from logics-parsing-api:latest .

# Build with increased timeout
docker build --network=host .
```

## Performance Tuning

### Optimize for Your GPU

```bash
# For GPUs with more memory (24GB+)
docker run -d \
  --gpus all \
  -e MAX_WORKERS=8 \
  -e CUDA_VISIBLE_DEVICES=0 \
  ...

# For multiple GPUs
docker run -d \
  --gpus '"device=0,1"' \
  -e MAX_WORKERS=16 \
  ...
```

### Shared Memory Size

```bash
# Increase shared memory for PyTorch
docker run -d \
  --gpus all \
  --shm-size=8g \
  ...
```

### CPU Affinity

```bash
# Pin to specific CPUs
docker run -d \
  --gpus all \
  --cpuset-cpus="0-7" \
  ...
```

## Security Best Practices

1. **Run as Non-Root**: Already configured in Dockerfile
2. **Read-Only Root Filesystem**: Add `--read-only` flag
3. **Drop Capabilities**: Add `--cap-drop=ALL`
4. **Security Scanning**:
   ```bash
   docker scan logics-parsing-api:latest
   ```
5. **Resource Limits**: Always set memory and CPU limits
6. **Network Isolation**: Use Docker networks
7. **Secrets Management**: Use Docker secrets or environment files

## Image Size Optimization

Current image size: ~15-20GB (includes model)

To reduce size:
1. Use external model mounts (reduces to ~5GB)
2. Multi-stage builds (already implemented)
3. Minimize layers (already optimized)
4. Use `.dockerignore` (already included)

## License

See main repository LICENSE file.
