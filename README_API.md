# Logics-Parsing API Server

This guide explains how to run and use the Logics-Parsing model as a RESTful API service with multi-threaded capabilities.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirement.txt
```

This installs all required dependencies including FastAPI, uvicorn, and the ML frameworks.

### 2. Download the Model

```bash
# From ModelScope
python download_model.py -t modelscope

# Or from HuggingFace
python download_model.py -t huggingface
```

### 3. Start the API Server

```bash
python api_server.py
```

The server will start on `http://0.0.0.0:8000` by default.

## Configuration

Configure the server using environment variables:

```bash
export MODEL_PATH="weights/Logics-Parsing"  # Path to model weights
export PORT=8000                             # Server port
export HOST="0.0.0.0"                        # Server host
export MAX_WORKERS=4                         # Number of concurrent workers
```

## API Documentation

Once the server is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## API Endpoints

### Health Check

Check if the server is running and the model is loaded:

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "model_loaded": true,
  "model_path": "weights/Logics-Parsing"
}
```

### Parse Document (File Upload)

Upload an image file for parsing:

```bash
curl -X POST "http://localhost:8000/parse" \
  -F "file=@/path/to/document.png" \
  -F "prompt=QwenVL HTML" \
  -F "include_visualization=true"
```

Response:
```json
{
  "request_id": "123e4567-e89b-12d3-a456-426614174000",
  "html_output": "<div class=\"table\" data-bbox=\"10,20,200,150\">...</div>",
  "visualization_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
  "input_dimensions": {
    "height": 1024,
    "width": 768
  }
}
```

### Parse Document (Base64)

Send a base64-encoded image:

```bash
curl -X POST "http://localhost:8000/parse_base64" \
  -H "Content-Type: application/json" \
  -d '{
    "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
    "prompt": "QwenVL HTML",
    "include_visualization": true
  }'
```

## Using the Python Client

A convenient Python client is provided in `example_client.py`:

```python
from example_client import LogicsParsingClient

# Create client
client = LogicsParsingClient(base_url="http://localhost:8000")

# Check health
health = client.health_check()
print(f"Server status: {health['status']}")

# Parse a document
result = client.parse_file(
    image_path="document.png",
    prompt="QwenVL HTML",
    include_visualization=True,
    save_output=True,
    output_dir="outputs"
)

print(f"Request ID: {result['request_id']}")
print(f"HTML saved to outputs/")
```

### Command Line Usage

```bash
# Basic usage
python example_client.py --image document.png

# With custom server
python example_client.py --image document.png --url http://server:8000

# Use base64 endpoint
python example_client.py --image document.png --use-base64

# Skip visualization
python example_client.py --image document.png --no-viz
```

## Multi-Threading and Concurrency

The API server is designed for high-throughput concurrent processing:

### Architecture

1. **Model Singleton**: The model is loaded once at startup and shared across all worker threads using thread-safe locks
2. **Thread Pool**: A configurable pool of worker threads (default: 4) processes requests concurrently
3. **Async I/O**: FastAPI's async capabilities handle I/O operations without blocking
4. **Automatic Cleanup**: Temporary files are cleaned up automatically after each request

### Performance Tuning

Adjust `MAX_WORKERS` based on your GPU memory:

```bash
# For GPUs with more memory, increase workers
export MAX_WORKERS=8
python api_server.py

# For GPUs with less memory, decrease workers
export MAX_WORKERS=2
python api_server.py
```

**Guidelines**:
- Each concurrent request requires GPU memory for processing
- Monitor GPU memory usage with `nvidia-smi`
- Start with 2-4 workers and increase based on available memory
- Too many workers may cause OOM (Out of Memory) errors

### Load Testing

Test concurrent request handling:

```bash
# Using Apache Bench
ab -n 100 -c 4 -p request.json -T application/json http://localhost:8000/parse_base64

# Using Python
python -c "
import concurrent.futures
from example_client import LogicsParsingClient

client = LogicsParsingClient()

def parse_doc(i):
    return client.parse_file(f'test_{i}.png')

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(parse_doc, range(10)))
"
```

## Request Parameters

### Common Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | string | "QwenVL HTML" | Instruction prompt for the model |
| `system_prompt` | string | "You are a helpful assistant" | System-level prompt |
| `include_visualization` | boolean | true | Generate bounding box visualization |
| `strip_tags` | boolean | false | Apply HTML tag simplification |

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | string | Unique identifier for the request |
| `html_output` | string | Parsed HTML with structure and bounding boxes |
| `visualization_base64` | string | Base64-encoded visualization image (if requested) |
| `input_dimensions` | object | Model input dimensions (height, width) |

## Error Handling

The API returns standard HTTP status codes:

- `200`: Success
- `400`: Bad request (invalid file type, missing parameters)
- `500`: Internal server error (processing failure)
- `503`: Service unavailable (model not loaded)

Example error response:
```json
{
  "detail": "Invalid file type: application/pdf. Only images are supported."
}
```

## Production Deployment

### Using Gunicorn

For production, use Gunicorn with multiple workers:

```bash
gunicorn api_server:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120
```

### Using Docker

Create a `Dockerfile`:

```dockerfile
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y python3 python3-pip
WORKDIR /app

COPY requirement.txt .
RUN pip3 install -r requirement.txt

COPY . .

ENV MODEL_PATH=weights/Logics-Parsing
ENV PORT=8000
ENV MAX_WORKERS=4

CMD ["python3", "api_server.py"]
```

Build and run:

```bash
docker build -t logics-parsing-api .
docker run --gpus all -p 8000:8000 -v $(pwd)/weights:/app/weights logics-parsing-api
```

### Behind a Reverse Proxy (Nginx)

```nginx
upstream logics_parsing {
    server localhost:8000;
}

server {
    listen 80;
    server_name api.example.com;

    client_max_body_size 20M;

    location / {
        proxy_pass http://logics_parsing;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }
}
```

## Troubleshooting

### Model Not Loading

**Problem**: `Model not loaded` in health check

**Solutions**:
1. Check `MODEL_PATH` environment variable
2. Verify model files exist in the specified directory
3. Check server logs for error messages
4. Ensure CUDA/GPU is available

### Out of Memory Errors

**Problem**: CUDA out of memory during processing

**Solutions**:
1. Reduce `MAX_WORKERS`
2. Process smaller images
3. Use a GPU with more memory
4. Enable model quantization (requires code modification)

### Slow Response Times

**Problem**: Requests taking too long

**Solutions**:
1. Increase `MAX_WORKERS` (if GPU memory allows)
2. Use flash_attention_2 (already enabled by default)
3. Reduce image resolution before uploading
4. Check GPU utilization with `nvidia-smi`

## API Client Examples

### JavaScript/Node.js

```javascript
const FormData = require('form-data');
const fs = require('fs');
const axios = require('axios');

const form = new FormData();
form.append('file', fs.createReadStream('document.png'));
form.append('prompt', 'QwenVL HTML');

axios.post('http://localhost:8000/parse', form, {
  headers: form.getHeaders()
})
.then(response => {
  console.log('Request ID:', response.data.request_id);
  console.log('HTML:', response.data.html_output);
})
.catch(error => console.error(error));
```

### cURL with Base64

```bash
# Encode image to base64
IMAGE_BASE64=$(base64 -i document.png)

# Send request
curl -X POST "http://localhost:8000/parse_base64" \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$IMAGE_BASE64\", \"prompt\": \"QwenVL HTML\"}"
```

### Python Requests

```python
import requests

# File upload
with open('document.png', 'rb') as f:
    response = requests.post(
        'http://localhost:8000/parse',
        files={'file': f},
        data={'prompt': 'QwenVL HTML'}
    )

result = response.json()
print(f"Request ID: {result['request_id']}")
```

## License

See main repository LICENSE file.
