"""
RESTful API Server for Logics-Parsing with Multi-threaded Support

This server provides HTTP endpoints for document parsing with concurrent request handling.
"""

import torch
import os
import io
import base64
import uuid
import tempfile
from typing import Optional, Dict, Any
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
from PIL import Image
import cv2
import re

from inference import inference, plot_bbox, qwenvl_pred_cast_tag, smart_resize


# Global model management
class ModelManager:
    """Singleton class to manage model loading and inference with thread safety."""

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.initialized = False
        return cls._instance

    def initialize(self, model_path: str):
        """Initialize the model and processor."""
        if self.initialized:
            return

        with self._lock:
            if not self.initialized:
                print(f"Loading model from {model_path}...")
                self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    model_path,
                    torch_dtype=torch.bfloat16,
                    attn_implementation="flash_attention_2",
                    device_map="cuda"
                )
                self.processor = AutoProcessor.from_pretrained(model_path)
                self.model_path = model_path
                self.initialized = True
                print("Model loaded successfully")

    def run_inference(self, image_path: str, prompt: str = "QwenVL HTML",
                     system_prompt: str = "You are a helpful assistant"):
        """Run inference with thread safety."""
        if not self.initialized:
            raise RuntimeError("Model not initialized")

        # The model itself handles CUDA synchronization
        # Multiple threads can call this, PyTorch handles GPU scheduling
        image = Image.open(image_path)
        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "image": image_path
                    }
                ]
            }
        ]

        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(
            text=[text], images=[image], padding=True, return_tensors="pt"
        ).to('cuda')

        output_ids = self.model.generate(**inputs, max_new_tokens=8192)
        generated_ids = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(inputs.input_ids, output_ids)
        ]
        output_text = self.processor.batch_decode(
            generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=True
        )

        input_height = inputs['image_grid_thw'][0][1] * 14
        input_width = inputs['image_grid_thw'][0][2] * 14

        return output_text[0], input_height, input_width


# Request/Response models
class ParseRequest(BaseModel):
    """Request model for document parsing."""
    prompt: str = Field(default="QwenVL HTML", description="Prompt for the model")
    system_prompt: str = Field(
        default="You are a helpful assistant",
        description="System prompt for the model"
    )
    include_visualization: bool = Field(
        default=True,
        description="Whether to include bounding box visualization"
    )
    strip_tags: bool = Field(
        default=False,
        description="Whether to apply tag stripping post-processing"
    )


class ParseResponse(BaseModel):
    """Response model for document parsing."""
    request_id: str = Field(description="Unique request identifier")
    html_output: str = Field(description="Parsed HTML output")
    visualization_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded visualization image (if requested)"
    )
    input_dimensions: Dict[str, int] = Field(
        description="Model input dimensions (height, width)"
    )


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    model_loaded: bool
    model_path: Optional[str] = None


# Application lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    # Startup
    model_path = os.getenv("MODEL_PATH", "weights/Logics-Parsing")
    if not os.path.exists(model_path):
        print(f"Warning: Model path {model_path} does not exist")
        print("Set MODEL_PATH environment variable or ensure model is downloaded")
    else:
        model_manager = ModelManager()
        model_manager.initialize(model_path)

    yield

    # Shutdown
    print("Shutting down API server...")


# Create FastAPI app
app = FastAPI(
    title="Logics-Parsing API",
    description="RESTful API for document parsing with multi-threaded support",
    version="1.0.0",
    lifespan=lifespan
)

# Thread pool for concurrent processing
executor = ThreadPoolExecutor(max_workers=int(os.getenv("MAX_WORKERS", "4")))


def cleanup_temp_files(*file_paths):
    """Clean up temporary files."""
    for file_path in file_paths:
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Error cleaning up {file_path}: {e}")


async def process_image(
    image_path: str,
    prompt: str,
    system_prompt: str,
    include_visualization: bool,
    strip_tags: bool,
    request_id: str
) -> ParseResponse:
    """Process image in thread pool to avoid blocking."""
    loop = asyncio.get_event_loop()

    def _process():
        model_manager = ModelManager()

        # Run inference
        prediction, input_height, input_width = model_manager.run_inference(
            image_path, prompt, system_prompt
        )

        # Apply post-processing if requested
        if strip_tags:
            prediction = qwenvl_pred_cast_tag(prediction)

        # Generate visualization if requested
        viz_base64 = None
        if include_visualization:
            try:
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_viz:
                    viz_path = tmp_viz.name

                plot_bbox(image_path, prediction, input_height, input_width, viz_path)

                with open(viz_path, 'rb') as f:
                    viz_bytes = f.read()
                    viz_base64 = base64.b64encode(viz_bytes).decode('utf-8')

                os.remove(viz_path)
            except Exception as e:
                print(f"Error generating visualization: {e}")

        return ParseResponse(
            request_id=request_id,
            html_output=prediction,
            visualization_base64=viz_base64,
            input_dimensions={
                "height": int(input_height),
                "width": int(input_width)
            }
        )

    return await loop.run_in_executor(executor, _process)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    model_manager = ModelManager()
    return HealthResponse(
        status="healthy" if model_manager.initialized else "model_not_loaded",
        model_loaded=model_manager.initialized,
        model_path=model_manager.model_path if model_manager.initialized else None
    )


@app.post("/parse", response_model=ParseResponse)
async def parse_document(
    file: UploadFile = File(..., description="Document image to parse"),
    prompt: str = "QwenVL HTML",
    system_prompt: str = "You are a helpful assistant",
    include_visualization: bool = True,
    strip_tags: bool = False,
    background_tasks: BackgroundTasks = None
):
    """
    Parse a document image and return structured HTML output.

    Args:
        file: Image file to parse (PNG, JPG, etc.)
        prompt: Model prompt (default: "QwenVL HTML")
        system_prompt: System prompt for the model
        include_visualization: Include bounding box visualization in response
        strip_tags: Apply tag stripping post-processing

    Returns:
        ParseResponse with HTML output and optional visualization
    """
    model_manager = ModelManager()
    if not model_manager.initialized:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Check server logs and MODEL_PATH configuration."
        )

    # Validate file type
    if not file.content_type.startswith('image/'):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Only images are supported."
        )

    # Generate request ID
    request_id = str(uuid.uuid4())

    # Save uploaded file to temporary location
    temp_input = None
    try:
        suffix = Path(file.filename).suffix or '.png'
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            temp_input = tmp.name

        # Process image asynchronously
        response = await process_image(
            temp_input,
            prompt,
            system_prompt,
            include_visualization,
            strip_tags,
            request_id
        )

        # Schedule cleanup
        background_tasks.add_task(cleanup_temp_files, temp_input)

        return response

    except Exception as e:
        # Clean up on error
        if temp_input:
            cleanup_temp_files(temp_input)
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")


@app.post("/parse_base64", response_model=ParseResponse)
async def parse_document_base64(
    image_base64: str,
    prompt: str = "QwenVL HTML",
    system_prompt: str = "You are a helpful assistant",
    include_visualization: bool = True,
    strip_tags: bool = False,
    background_tasks: BackgroundTasks = None
):
    """
    Parse a base64-encoded document image.

    Args:
        image_base64: Base64-encoded image data
        prompt: Model prompt
        system_prompt: System prompt for the model
        include_visualization: Include bounding box visualization
        strip_tags: Apply tag stripping post-processing

    Returns:
        ParseResponse with HTML output and optional visualization
    """
    model_manager = ModelManager()
    if not model_manager.initialized:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Check server logs and MODEL_PATH configuration."
        )

    # Generate request ID
    request_id = str(uuid.uuid4())

    # Decode and save base64 image
    temp_input = None
    try:
        image_data = base64.b64decode(image_base64)

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp.write(image_data)
            temp_input = tmp.name

        # Process image asynchronously
        response = await process_image(
            temp_input,
            prompt,
            system_prompt,
            include_visualization,
            strip_tags,
            request_id
        )

        # Schedule cleanup
        background_tasks.add_task(cleanup_temp_files, temp_input)

        return response

    except Exception as e:
        # Clean up on error
        if temp_input:
            cleanup_temp_files(temp_input)
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")

    print(f"Starting Logics-Parsing API server on {host}:{port}")
    print(f"Max workers: {os.getenv('MAX_WORKERS', '4')}")
    print(f"Model path: {os.getenv('MODEL_PATH', 'weights/Logics-Parsing')}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
