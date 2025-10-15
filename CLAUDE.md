# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Logics-Parsing is an end-to-end document parsing model based on Qwen2.5-VL (Vision-Language Model). It parses complex documents with challenging layouts and STEM content, outputting structured HTML with bounding boxes, categories, and OCR text. The model excels at:
- Complex scientific formulas
- Chemical structures (SMILES format)
- Tables and intricate layouts
- Handwritten content
- Multi-language documents (English and Chinese)

The codebase includes:
- Model download script (`download_model.py`)
- Command-line inference script (`inference.py`)
- RESTful API server with multi-threading (`api_server.py`)
- Example API client (`example_client.py`)

## Development Setup

### Environment
```bash
# Create and activate conda environment
conda create -n logis-parsing python=3.10
conda activate logis-parsing

# Install dependencies
pip install -r requirement.txt
```

### Model Download
```bash
# From ModelScope (Alibaba)
pip install modelscope
python download_model.py -t modelscope

# From HuggingFace
pip install huggingface_hub
python download_model.py -t huggingface
```

Model is downloaded to `weights/Logics-Parsing/` directory.

## Running Inference

### Basic Usage
```bash
python3 inference.py \
  --image_path PATH_TO_INPUT_IMG \
  --output_path PATH_TO_OUTPUT \
  --model_path PATH_TO_MODEL
```

### Optional Parameters
- `--prompt`: Custom prompt (default: "QwenVL HTML")

### Outputs
1. **HTML file**: Structured output saved to `--output_path`
2. **Visualization**: Image with bounding boxes saved as `{input_image_name}_vis.png`

## Key Architecture Components

### Model Configuration (inference.py)
- **Base Model**: Qwen2_5_VLForConditionalGeneration
- **Precision**: bfloat16
- **Attention**: flash_attention_2 (requires GPU)
- **Device**: CUDA (GPU required)
- **Max tokens**: 8192

### Image Processing
- Uses `smart_resize()` function to ensure dimensions are:
  - Divisible by 28 (factor)
  - Between min_pixels (3136) and max_pixels (1024×1024)
  - Aspect ratio maintained and < 200:1

### Output Format
The model generates HTML with special attributes:
- `data-bbox="x1,y1,x2,y2"`: Bounding box coordinates
- Content wrapped in semantic tags: `<div class="table">`, `<div class="formula">`, `<div class="chemistry">`, etc.

### Post-Processing Functions
- `qwenvl_pred_cast_tag()`: Strips/simplifies HTML tags (currently commented out in main flow)
- `plot_bbox()`: Extracts bounding boxes and visualizes them on the original image

## Important Implementation Notes

1. **GPU Required**: Model uses CUDA and flash_attention_2 - CPU inference not supported
2. **Coordinate Scaling**: Bounding boxes are in model input resolution and must be scaled to original image dimensions using the ratio of `image_grid_thw` values
3. **Image Grid**: The model internally resizes images to multiples of 14×14 patches; `inputs['image_grid_thw']` contains [temporal, height_patches, width_patches]
4. **Prompt Format**: Uses chat template with system and user roles; image is passed as part of user content

## Model Download Locations
- **ModelScope**: `Alibaba-DT/Logics-Parsing`
- **HuggingFace**: `Logics-MLLM/Logics-Parsing`

## RESTful API Server

### Starting the Server
```bash
# Set environment variables (optional)
export MODEL_PATH="weights/Logics-Parsing"  # Default: weights/Logics-Parsing
export PORT=8000                             # Default: 8000
export HOST="0.0.0.0"                        # Default: 0.0.0.0
export MAX_WORKERS=4                         # Default: 4

# Start the server
python api_server.py
```

The server starts on `http://0.0.0.0:8000` by default and provides automatic API documentation at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### API Endpoints

#### Health Check
```bash
GET /health
```
Returns server status and model loading state.

#### Parse Document (File Upload)
```bash
POST /parse
Content-Type: multipart/form-data

Parameters:
- file: Image file (required)
- prompt: Model prompt (default: "QwenVL HTML")
- system_prompt: System prompt (default: "You are a helpful assistant")
- include_visualization: Include bbox visualization (default: true)
- strip_tags: Apply tag stripping (default: false)

Response:
{
  "request_id": "uuid",
  "html_output": "parsed HTML",
  "visualization_base64": "base64 image data",
  "input_dimensions": {"height": 1024, "width": 768}
}
```

#### Parse Document (Base64)
```bash
POST /parse_base64
Content-Type: application/json

Body:
{
  "image_base64": "base64 encoded image",
  "prompt": "QwenVL HTML",
  "system_prompt": "You are a helpful assistant",
  "include_visualization": true,
  "strip_tags": false
}
```

### Using the API Client

```bash
# Basic usage
python example_client.py --image path/to/image.png

# Custom server URL
python example_client.py --image path/to/image.png --url http://server:8000

# Use base64 endpoint
python example_client.py --image path/to/image.png --use-base64

# Skip visualization
python example_client.py --image path/to/image.png --no-viz

# Custom output directory
python example_client.py --image path/to/image.png --output-dir my_outputs
```

### Multi-Threading Architecture

The API server implements multi-threaded request handling:

1. **Model Singleton**: Single model instance shared across threads with thread-safe access via locks
2. **Thread Pool**: Configurable worker pool (default 4 workers) handles concurrent inference requests
3. **Async Processing**: FastAPI's async capabilities combined with ThreadPoolExecutor for non-blocking I/O
4. **Automatic Cleanup**: Background tasks handle temporary file cleanup after response is sent

**Concurrency Notes**:
- Multiple requests can be processed in parallel up to `MAX_WORKERS` limit
- PyTorch handles GPU synchronization internally
- Each request gets isolated temporary files to avoid conflicts
- Model loading happens once at startup, not per-request
